//! Cuts a live channel into phrases at pauses, so each can be recognized while
//! the meeting goes on.
//!
//! Frame probabilities come from a [`SpeechScorer`] (Silero). Thresholds are
//! the ones `chunking` uses; pre-roll, post-speech tail and onset are the
//! offline VAD profile of `vad`. A phrase never runs past [`MAX_PHRASE_SECONDS`]:
//! longer speech is cut there, as long-form chunking does with its hard cut.

use std::collections::VecDeque;

use log::warn;

use crate::audio_toolkit::constants::WHISPER_SAMPLE_RATE;
use crate::audio_toolkit::vad::{
    frames_for_duration_ms, SpeechScorer, VAD_OFFLINE_HANGOVER_MS, VAD_ONSET_MS, VAD_PREFILL_MS,
};

const RATE: usize = WHISPER_SAMPLE_RATE as usize;

pub const MAX_PHRASE_SECONDS: f64 = 25.0;
/// Speech shorter than this (clicks, coughs) is not worth recognizing.
const MIN_SPEECH_MS: u64 = 250;
/// Silence kept after the last voiced frame when a phrase ends.
const TAIL_MS: u64 = 150;

// Silero's `get_speech_timestamps` defaults, as in `chunking`.
const THRESHOLD: f32 = 0.5;
const NEG_THRESHOLD: f32 = THRESHOLD - 0.15;

/// One phrase: 16 kHz mono audio and its place in the meeting, in seconds
/// from the meeting's start.
#[derive(Debug, Clone, PartialEq)]
pub struct Phrase {
    pub samples: Vec<f32>,
    pub start: f64,
    pub end: f64,
}

enum State {
    /// Waiting for speech; `recent` is the pre-roll candidate.
    Idle {
        recent: VecDeque<Vec<f32>>,
        onset: usize,
    },
    Speech {
        start_frame: u64,
        audio: Vec<f32>,
        voiced_frames: usize,
        /// Frames up to and including the last voiced one.
        last_voiced_end: usize,
        silence_run: usize,
    },
}

pub struct PhraseSegmenter {
    scorer: Box<dyn SpeechScorer>,
    frame: usize,
    prefill_frames: usize,
    hangover_frames: usize,
    onset_frames: usize,
    tail_frames: usize,
    min_speech_frames: usize,
    max_frames: usize,
    /// Meeting time of this channel's first sample.
    offset_secs: f64,
    carry: Vec<f32>,
    frames_seen: u64,
    scoring_failed: bool,
    state: State,
}

impl PhraseSegmenter {
    pub fn new(scorer: Box<dyn SpeechScorer>, offset_secs: f64) -> Self {
        let frame = scorer.frame_samples();
        assert!(frame > 0, "VAD frame size must be non-zero");
        Self {
            scorer,
            frame,
            prefill_frames: frames_for_duration_ms(VAD_PREFILL_MS, frame),
            hangover_frames: frames_for_duration_ms(VAD_OFFLINE_HANGOVER_MS, frame),
            onset_frames: frames_for_duration_ms(VAD_ONSET_MS, frame),
            tail_frames: frames_for_duration_ms(TAIL_MS, frame),
            min_speech_frames: frames_for_duration_ms(MIN_SPEECH_MS, frame),
            max_frames: ((MAX_PHRASE_SECONDS * RATE as f64) / frame as f64).ceil() as usize,
            offset_secs,
            carry: Vec::new(),
            frames_seen: 0,
            scoring_failed: false,
            state: Self::idle(),
        }
    }

    fn idle() -> State {
        State::Idle {
            recent: VecDeque::new(),
            onset: 0,
        }
    }

    /// Adds audio; returns the phrases it completes.
    pub fn push(&mut self, samples: &[f32]) -> Vec<Phrase> {
        self.carry.extend_from_slice(samples);
        let whole = self.carry.len() / self.frame * self.frame;
        let mut phrases = Vec::new();
        if whole == 0 {
            return phrases;
        }
        let rest = self.carry.split_off(whole);
        let frames = std::mem::replace(&mut self.carry, rest);
        for frame in frames.chunks_exact(self.frame) {
            let prob = self.score(frame);
            if let Some(phrase) = self.step(frame, prob) {
                phrases.push(phrase);
            }
        }
        phrases
    }

    /// The channel ended: a phrase still in progress is closed.
    pub fn finish(&mut self) -> Option<Phrase> {
        match std::mem::replace(&mut self.state, Self::idle()) {
            State::Speech {
                start_frame,
                audio,
                voiced_frames,
                last_voiced_end,
                ..
            } => self.close(start_frame, audio, voiced_frames, last_voiced_end),
            State::Idle { .. } => None,
        }
    }

    fn score(&mut self, frame: &[f32]) -> f32 {
        if self.scoring_failed {
            return 1.0;
        }
        match self.scorer.score(frame) {
            Ok(probs) if probs.len() == 1 => probs[0],
            result => {
                // Without scores every phrase is cut at the maximum length,
                // which still recognizes everything said.
                warn!("Meeting VAD failed, cutting phrases by length only: {result:?}");
                self.scoring_failed = true;
                1.0
            }
        }
    }

    fn step(&mut self, frame: &[f32], prob: f32) -> Option<Phrase> {
        let index = self.frames_seen;
        self.frames_seen += 1;

        match &mut self.state {
            State::Idle { recent, onset } => {
                recent.push_back(frame.to_vec());
                if recent.len() > self.prefill_frames + self.onset_frames {
                    recent.pop_front();
                }
                *onset = if prob >= THRESHOLD { *onset + 1 } else { 0 };
                if *onset >= self.onset_frames {
                    let start_frame = index + 1 - recent.len() as u64;
                    let audio: Vec<f32> = recent.drain(..).flatten().collect();
                    let frames = audio.len() / self.frame;
                    self.state = State::Speech {
                        start_frame,
                        audio,
                        voiced_frames: *onset,
                        last_voiced_end: frames,
                        silence_run: 0,
                    };
                }
                None
            }
            State::Speech {
                start_frame,
                audio,
                voiced_frames,
                last_voiced_end,
                silence_run,
            } => {
                audio.extend_from_slice(frame);
                let frames = audio.len() / self.frame;
                if prob >= THRESHOLD {
                    *voiced_frames += 1;
                    *last_voiced_end = frames;
                    *silence_run = 0;
                } else if prob < NEG_THRESHOLD {
                    *silence_run += 1;
                }
                let pause = *silence_run >= self.hangover_frames;
                if !pause && frames < self.max_frames {
                    return None;
                }
                let (start_frame, audio, voiced, voiced_end) = (
                    *start_frame,
                    std::mem::take(audio),
                    *voiced_frames,
                    *last_voiced_end,
                );
                self.state = Self::idle();
                if pause {
                    self.close(start_frame, audio, voiced, voiced_end)
                } else {
                    // Cut by length: the speech goes on, so nothing is trimmed.
                    let end_frame = audio.len() / self.frame;
                    self.close(start_frame, audio, voiced, end_frame)
                }
            }
        }
    }

    /// Trims the silence past the last voiced frame (keeping a short tail) and
    /// drops phrases with too little speech.
    fn close(
        &self,
        start_frame: u64,
        mut audio: Vec<f32>,
        voiced_frames: usize,
        last_voiced_end: usize,
    ) -> Option<Phrase> {
        if voiced_frames < self.min_speech_frames {
            return None;
        }
        let keep = ((last_voiced_end + self.tail_frames) * self.frame).min(audio.len());
        audio.truncate(keep);
        let start = self.offset_secs + (start_frame * self.frame as u64) as f64 / RATE as f64;
        let end = start + audio.len() as f64 / RATE as f64;
        Some(Phrase {
            samples: audio,
            start,
            end,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::audio_toolkit::vad::{VadFrame, VoiceActivityDetector};
    use anyhow::Result;

    const FRAME: usize = 512;

    /// Loud frames are speech: stands in for Silero.
    struct LoudnessScorer;

    impl VoiceActivityDetector for LoudnessScorer {
        fn push_frame<'a>(&'a mut self, frame: &'a [f32]) -> Result<VadFrame<'a>> {
            Ok(VadFrame::Speech(frame))
        }
        fn frame_samples(&self) -> usize {
            FRAME
        }
    }

    impl SpeechScorer for LoudnessScorer {
        fn score(&mut self, frames: &[f32]) -> Result<Vec<f32>> {
            Ok(frames
                .chunks(FRAME)
                .map(|f| {
                    let rms = (f.iter().map(|s| s * s).sum::<f32>() / f.len() as f32).sqrt();
                    if rms > 0.05 {
                        1.0
                    } else {
                        0.0
                    }
                })
                .collect())
        }
    }

    fn segmenter(offset: f64) -> PhraseSegmenter {
        PhraseSegmenter::new(Box::new(LoudnessScorer), offset)
    }

    fn silence(seconds: f64) -> Vec<f32> {
        vec![0.0; (seconds * RATE as f64) as usize]
    }

    fn tone(seconds: f64) -> Vec<f32> {
        (0..(seconds * RATE as f64) as usize)
            .map(|i| 0.5 * (i as f32 * 0.2).sin())
            .collect()
    }

    fn run(seg: &mut PhraseSegmenter, audio: &[f32], piece: usize) -> Vec<Phrase> {
        let mut phrases: Vec<Phrase> = audio.chunks(piece).flat_map(|c| seg.push(c)).collect();
        phrases.extend(seg.finish());
        phrases
    }

    fn signal(parts: &[&[f32]]) -> Vec<f32> {
        parts.iter().flat_map(|p| p.iter().copied()).collect()
    }

    #[test]
    fn silence_tone_silence_gives_one_phrase_with_times() {
        let audio = signal(&[&silence(1.0), &tone(2.0), &silence(1.5)]);
        let phrases = run(&mut segmenter(0.0), &audio, 4096);
        assert_eq!(phrases.len(), 1);
        let p = &phrases[0];
        // Pre-roll of 450 ms before the tone, which starts at 1.0 s.
        assert!((p.start - 0.512).abs() < 0.05, "start {}", p.start);
        // Tone ends at 3.0 s; a 150 ms tail is kept.
        assert!((p.end - 3.16).abs() < 0.07, "end {}", p.end);
        assert_eq!(p.samples.len() as f64 / RATE as f64, p.end - p.start);
    }

    #[test]
    fn offset_shifts_phrase_times() {
        let audio = signal(&[&silence(1.0), &tone(1.0), &silence(1.0)]);
        let plain = run(&mut segmenter(0.0), &audio, 1000);
        let shifted = run(&mut segmenter(100.0), &audio, 1000);
        assert_eq!(plain.len(), 1);
        assert!((shifted[0].start - plain[0].start - 100.0).abs() < 1e-9);
        assert!((shifted[0].end - plain[0].end - 100.0).abs() < 1e-9);
    }

    #[test]
    fn two_phrases_split_by_a_pause() {
        let audio = signal(&[
            &silence(0.5),
            &tone(1.0),
            &silence(2.0),
            &tone(1.0),
            &silence(1.0),
        ]);
        let phrases = run(&mut segmenter(0.0), &audio, 3000);
        assert_eq!(phrases.len(), 2);
        assert!(phrases[0].end < phrases[1].start);
        assert!(
            (phrases[1].start - 3.5 + 0.45).abs() < 0.1,
            "{}",
            phrases[1].start
        );
    }

    #[test]
    fn short_blip_is_dropped() {
        let audio = signal(&[&silence(1.0), &tone(0.1), &silence(2.0)]);
        assert!(run(&mut segmenter(0.0), &audio, 2048).is_empty());
    }

    #[test]
    fn long_speech_is_cut_at_the_maximum_length() {
        let audio = tone(60.0);
        let phrases = run(&mut segmenter(0.0), &audio, 8000);
        assert_eq!(phrases.len(), 3);
        assert!(phrases[0].start.abs() < 1e-9);
        for p in &phrases[..2] {
            let len = p.end - p.start;
            assert!(
                (MAX_PHRASE_SECONDS..MAX_PHRASE_SECONDS + 0.05).contains(&len),
                "len {len}"
            );
        }
        // The cuts are contiguous: nothing is lost between phrases.
        assert!((phrases[1].start - phrases[0].end).abs() < 0.05);
        assert!((phrases[2].start - phrases[1].end).abs() < 0.05);
        let total: f64 = phrases.iter().map(|p| p.end - p.start).sum();
        assert!((total - 60.0).abs() < 0.1, "total {total}");
    }

    #[test]
    fn speech_running_to_the_end_is_flushed_by_finish() {
        let audio = signal(&[&silence(0.5), &tone(2.0)]);
        let phrases = run(&mut segmenter(0.0), &audio, 777);
        assert_eq!(phrases.len(), 1);
        assert!(
            (phrases[0].end - 2.5).abs() < 0.05,
            "end {}",
            phrases[0].end
        );
    }

    #[test]
    fn piece_size_does_not_change_the_result() {
        let audio = signal(&[
            &silence(1.0),
            &tone(1.5),
            &silence(1.0),
            &tone(1.5),
            &silence(1.0),
        ]);
        let whole = run(&mut segmenter(2.0), &audio, audio.len());
        let odd = run(&mut segmenter(2.0), &audio, 333);
        assert_eq!(whole, odd);
    }
}
