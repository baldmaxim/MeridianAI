//! Threads of an active meeting: recognizer, levels ticker, phrase cutter.

use std::sync::mpsc::{Receiver, RecvTimeoutError, Sender};
use std::sync::Arc;
use std::thread::JoinHandle;
use std::time::Instant;

use log::{error, warn};
use tauri::Manager;
use tauri_specta::Event;

use super::capture::{ChanMsg, ChannelShared};
use super::recognizer::{run_recognizer, PhraseJob, PhraseQueue};
use super::segmenter::PhraseSegmenter;
use super::session::{ChannelRuntime, LastLevels};
use super::silence::SilenceDetector;
use super::sink::SegmentSink;
use super::voices::{embed_fn, EmbedderCell};
use super::{
    now_iso, short_id, MeetingLevels, MeetingManager, MeetingSegment, MeetingSegmentRemoved,
    MeetingState, MeetingStateKind, MeetingSystemSilent, MeetingVoices, CHANNEL_SYSTEM, TICK,
};
use crate::audio_toolkit::vad::SpeechScorer;
use crate::managers::transcription::TranscriptionManager;
use crate::settings::get_settings;

impl MeetingManager {
    pub(super) fn spawn_recognizer(
        &self,
        meeting_id: &str,
        queue: &Arc<PhraseQueue>,
        done: Sender<()>,
    ) {
        let app = self.app.clone();
        let db = Arc::clone(&self.db);
        let queue = Arc::clone(queue);
        let meeting_id = meeting_id.to_string();
        let embedder: EmbedderCell = Arc::clone(&self.voice_embedder);
        let spawned = std::thread::Builder::new()
            .name("meeting-recognizer".into())
            .spawn(move || {
                let tm = Arc::clone(&app.state::<Arc<TranscriptionManager>>());
                let model_id = get_settings(&app).selected_model;
                // A resumed meeting carries on with the voices it already has.
                let voices = db.voice_centroids(&meeting_id).unwrap_or_else(|e| {
                    warn!("Cannot read the voices of {meeting_id}: {e:#}");
                    Vec::new()
                });
                let sink = SegmentSink::new(
                    Arc::clone(&db),
                    &meeting_id,
                    embed_fn(&app, &embedder),
                    voices,
                );
                run_recognizer(
                    &queue,
                    &meeting_id,
                    |samples| {
                        // The idle timer or a dictation may have unloaded the model.
                        if !tm.is_model_loaded() {
                            tm.load_model(&model_id)?;
                        }
                        tm.transcribe_phrase(samples.to_vec())
                    },
                    |segment, samples| {
                        let stored = sink.store(segment, samples)?;
                        if let Some(voices) = stored.new_voices {
                            let _ = MeetingVoices {
                                meeting_id: meeting_id.clone(),
                                voices,
                            }
                            .emit(&app);
                        }
                        for segment_id in stored.removed {
                            let _ = MeetingSegmentRemoved {
                                meeting_id: meeting_id.clone(),
                                segment_id,
                            }
                            .emit(&app);
                        }
                        if let Some(segment) = stored.segment {
                            let _ = MeetingSegment { segment }.emit(&app);
                        }
                        Ok(())
                    },
                    |message| {
                        warn!("{message}");
                        let _ = MeetingState {
                            kind: MeetingStateKind::RecognitionError,
                            meeting_id: meeting_id.clone(),
                            queue_len: queue.len() as u32,
                            channel: None,
                            message: Some(message),
                        }
                        .emit(&app);
                    },
                    short_id,
                    now_iso,
                );
                let _ = done.send(());
            });
        if let Err(e) = spawned {
            // Without a recognizer the audio is still recorded.
            error!("Cannot start the meeting recognizer: {e}");
        }
    }

    pub(super) fn spawn_ticker(
        &self,
        meeting_id: &str,
        channels: &[ChannelRuntime],
        queue: &Arc<PhraseQueue>,
        last: &Arc<LastLevels>,
        stop: Receiver<()>,
    ) -> JoinHandle<()> {
        let app = self.app.clone();
        let meeting_id = meeting_id.to_string();
        let queue = Arc::clone(queue);
        let last = Arc::clone(last);
        let shared: Vec<(&'static str, Arc<ChannelShared>)> = channels
            .iter()
            .map(|c| (c.audio_name, Arc::clone(&c.shared)))
            .collect();
        // Only an online meeting has the computer's sound to lose.
        let mut system_silence = shared
            .iter()
            .any(|(name, _)| *name == CHANNEL_SYSTEM)
            .then(SilenceDetector::default);
        std::thread::spawn(move || {
            let mut reported_queue = 0usize;
            let began = Instant::now();
            loop {
                let mut levels = MeetingLevels::default();
                for (name, shared) in &shared {
                    let level = shared.take_level();
                    if *name == CHANNEL_SYSTEM {
                        levels.system = level;
                        let change = system_silence
                            .as_mut()
                            .and_then(|d| d.update(level, began.elapsed()));
                        if let Some(silent) = change {
                            let _ = MeetingSystemSilent {
                                meeting_id: meeting_id.clone(),
                                silent,
                            }
                            .emit(&app);
                        }
                    } else {
                        levels.mic = level;
                    }
                    if let Some(message) = shared.take_error() {
                        let _ = MeetingState {
                            kind: MeetingStateKind::DeviceError,
                            meeting_id: meeting_id.clone(),
                            queue_len: queue.len() as u32,
                            channel: Some((*name).to_string()),
                            message: Some(message),
                        }
                        .emit(&app);
                    }
                }
                last.store(levels);
                let _ = levels.emit(&app);

                let queued = queue.len();
                if queued != reported_queue {
                    reported_queue = queued;
                    let _ = MeetingState {
                        kind: MeetingStateKind::Queue,
                        meeting_id: meeting_id.clone(),
                        queue_len: queued as u32,
                        channel: None,
                        message: None,
                    }
                    .emit(&app);
                }
                match stop.recv_timeout(TICK) {
                    Err(RecvTimeoutError::Timeout) => {}
                    _ => break,
                }
            }
        })
    }
}

/// One channel's phrase cutter: audio in, phrases to the queue.
pub(super) fn cut_phrases(
    rx: Receiver<ChanMsg>,
    scorer: Box<dyn SpeechScorer>,
    queue: &PhraseQueue,
    label: &str,
) {
    let mut scorer = Some(scorer);
    let mut segmenter: Option<PhraseSegmenter> = None;
    let mut enqueue = |phrase| {
        queue.push(PhraseJob {
            channel: label.to_string(),
            phrase,
        });
    };
    for message in rx {
        match message {
            ChanMsg::Start { offset_secs } => {
                if let Some(scorer) = scorer.take() {
                    segmenter = Some(PhraseSegmenter::new(scorer, offset_secs));
                }
            }
            ChanMsg::Samples(samples) => {
                if let Some(segmenter) = segmenter.as_mut() {
                    segmenter.push(&samples).into_iter().for_each(&mut enqueue);
                }
            }
        }
    }
    if let Some(phrase) = segmenter.as_mut().and_then(PhraseSegmenter::finish) {
        enqueue(phrase);
    }
}
