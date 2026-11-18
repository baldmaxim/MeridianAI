//! The tap on the capture: what the two channels record is also copied here,
//! mixed into one mono stream for the server and measured for the levels of
//! the two sources.
//!
//! The tap never blocks a capture thread and never grows without bound: each
//! channel keeps the last few seconds and drops the oldest audio beyond that
//! (the disk has all of it anyway). While there is no connection the tap is
//! off and keeps nothing, so a reconnect sends the present, not the past.

use std::collections::VecDeque;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Mutex, MutexGuard};

use super::live_proto::SourceLevels;

/// Samples a channel may hold before the oldest are dropped (10 s).
pub(super) const TAP_CAPACITY: usize = 16_000 * 10;
/// How far one channel may run ahead of the other before the slow one is
/// padded with silence (0.5 s). Loopback adds silence every 250 ms, so in
/// practice the channels stay closer than this.
pub(super) const MAX_SKEW: usize = 8_000;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(super) enum Source {
    Mic,
    System,
}

/// Sum of squares, count and peak of a run of samples.
#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub(super) struct LevelAcc {
    sum_sq: f64,
    count: u64,
    peak: f32,
}

impl LevelAcc {
    fn add(&mut self, sample: f32) {
        self.sum_sq += f64::from(sample) * f64::from(sample);
        self.count += 1;
        self.peak = self.peak.max(sample.abs());
    }

    pub(super) fn merge(&mut self, other: LevelAcc) {
        self.sum_sq += other.sum_sq;
        self.count += other.count;
        self.peak = self.peak.max(other.peak);
    }

    pub(super) fn rms(&self) -> f32 {
        if self.count == 0 {
            0.0
        } else {
            (self.sum_sq / self.count as f64).sqrt() as f32
        }
    }

    pub(super) fn peak(&self) -> f32 {
        self.peak
    }
}

/// Levels of both sources collected over a time, for `audio_source_levels`.
#[derive(Clone, Copy, Debug, Default)]
pub(super) struct LevelsAcc {
    pub(super) mic: LevelAcc,
    pub(super) system: LevelAcc,
}

impl LevelsAcc {
    pub(super) fn take(&mut self) -> SourceLevels {
        let levels = SourceLevels {
            mic_rms: self.mic.rms(),
            mic_peak: self.mic.peak(),
            system_rms: self.system.rms(),
            system_peak: self.system.peak(),
        };
        *self = Self::default();
        levels
    }
}

/// What one look at the tap yields.
#[derive(Debug, Default)]
pub(super) struct Drained {
    /// Both channels mixed, s16 mono 16 kHz.
    pub(super) pcm: Vec<i16>,
    pub(super) mic: LevelAcc,
    pub(super) system: LevelAcc,
}

#[derive(Default)]
struct Buffers {
    mic: VecDeque<f32>,
    system: VecDeque<f32>,
}

pub(super) struct LiveTap {
    enabled: AtomicBool,
    /// Two channels (an online meeting) or the microphone alone.
    two_channels: bool,
    buffers: Mutex<Buffers>,
    /// Samples dropped for want of room, for the log.
    dropped: AtomicU64,
}

fn to_i16(sample: f32) -> i16 {
    (sample.clamp(-1.0, 1.0) * f32::from(i16::MAX)).round() as i16
}

/// Takes the audio both buffers have and mixes it (the sum, clipped to the
/// range). The channel that runs ahead by more than `MAX_SKEW` is cut back
/// to it and the slow one is padded with silence; otherwise both give the
/// same number of samples and the rest waits for the next look.
fn mix_buffers(mic: &mut VecDeque<f32>, system: &mut VecDeque<f32>, two_channels: bool) -> Drained {
    let take = if two_channels {
        let (short, long) = (mic.len().min(system.len()), mic.len().max(system.len()));
        short.max(long.saturating_sub(MAX_SKEW))
    } else {
        mic.len()
    };
    let mut out = Drained {
        pcm: Vec::with_capacity(take),
        ..Drained::default()
    };
    for _ in 0..take {
        let a = mic.pop_front().unwrap_or(0.0);
        let b = if two_channels {
            system.pop_front().unwrap_or(0.0)
        } else {
            0.0
        };
        out.mic.add(a);
        if two_channels {
            out.system.add(b);
        }
        out.pcm.push(to_i16(a + b));
    }
    out
}

impl LiveTap {
    pub(super) fn new(two_channels: bool) -> Self {
        Self {
            enabled: AtomicBool::new(false),
            two_channels,
            buffers: Mutex::new(Buffers::default()),
            dropped: AtomicU64::new(0),
        }
    }

    fn buffers(&self) -> MutexGuard<'_, Buffers> {
        self.buffers.lock().unwrap_or_else(|e| e.into_inner())
    }

    /// Called by a capture thread with the samples it has just written to disk.
    pub(super) fn push(&self, source: Source, samples: &[f32]) {
        if !self.enabled.load(Ordering::Relaxed) {
            return;
        }
        let mut buffers = self.buffers();
        let queue = match source {
            Source::Mic => &mut buffers.mic,
            Source::System => &mut buffers.system,
        };
        queue.extend(samples.iter().copied());
        if queue.len() > TAP_CAPACITY {
            let excess = queue.len() - TAP_CAPACITY;
            queue.drain(..excess);
            self.dropped.fetch_add(excess as u64, Ordering::Relaxed);
        }
    }

    /// On: starts from the present (nothing older is kept). Off: forgets everything.
    pub(super) fn set_enabled(&self, on: bool) {
        let mut buffers = self.buffers();
        buffers.mic.clear();
        buffers.system.clear();
        self.enabled.store(on, Ordering::Relaxed);
    }

    /// Everything that can be sent now.
    pub(super) fn drain(&self) -> Drained {
        let mut buffers = self.buffers();
        let Buffers { mic, system } = &mut *buffers;
        mix_buffers(mic, system, self.two_channels)
    }

    pub(super) fn two_channels(&self) -> bool {
        self.two_channels
    }

    pub(super) fn dropped(&self) -> u64 {
        self.dropped.load(Ordering::Relaxed)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn deque(samples: &[f32]) -> VecDeque<f32> {
        samples.iter().copied().collect()
    }

    #[test]
    fn a_disabled_tap_keeps_nothing() {
        let tap = LiveTap::new(false);
        tap.push(Source::Mic, &[0.5; 100]);
        assert!(tap.drain().pcm.is_empty());
        tap.set_enabled(true);
        tap.push(Source::Mic, &[0.5; 100]);
        assert_eq!(tap.drain().pcm.len(), 100);
        // Turning it off drops what was waiting.
        tap.push(Source::Mic, &[0.5; 100]);
        tap.set_enabled(false);
        assert!(tap.drain().pcm.is_empty());
    }

    #[test]
    fn a_full_tap_drops_the_oldest_audio() {
        let tap = LiveTap::new(false);
        tap.set_enabled(true);
        // 12 s of a rising ramp: the first 2 s do not fit.
        let total = TAP_CAPACITY + 32_000;
        let ramp: Vec<f32> = (0..total).map(|i| i as f32 / total as f32).collect();
        tap.push(Source::Mic, &ramp);
        assert_eq!(tap.dropped(), 32_000);
        let drained = tap.drain();
        assert_eq!(drained.pcm.len(), TAP_CAPACITY);
        // The newest audio is what stayed: the ramp ends near 1.0.
        assert!(*drained.pcm.last().unwrap() > 32_000);
        assert!(drained.pcm[0] > to_i16(0.16));
    }

    #[test]
    fn two_channels_are_summed_and_clipped() {
        let mut mic = deque(&[0.25, 0.9, -0.9]);
        let mut system = deque(&[0.25, 0.9, -0.9]);
        let out = mix_buffers(&mut mic, &mut system, true);
        assert_eq!(out.pcm, vec![to_i16(0.5), i16::MAX, -i16::MAX]);
        assert!(mic.is_empty() && system.is_empty());
    }

    #[test]
    fn the_channels_give_equal_parts_and_the_rest_waits() {
        let mut mic = deque(&[0.1; 300]);
        let mut system = deque(&[0.1; 200]);
        let out = mix_buffers(&mut mic, &mut system, true);
        assert_eq!(out.pcm.len(), 200);
        assert_eq!(mic.len(), 100);
        assert!(system.is_empty());
    }

    #[test]
    fn a_stalled_channel_does_not_hold_the_other_back() {
        let mut mic = deque(&vec![0.1; MAX_SKEW + 4_000]);
        let mut system = VecDeque::new();
        let out = mix_buffers(&mut mic, &mut system, true);
        // The microphone is cut back to the allowed lead; the system part is silence.
        assert_eq!(out.pcm.len(), 4_000);
        assert_eq!(mic.len(), MAX_SKEW);
        assert_eq!(out.system.rms(), 0.0);
        assert!(out.mic.rms() > 0.09);
    }

    #[test]
    fn the_microphone_alone_is_passed_through() {
        let mut mic = deque(&[0.5; 10]);
        let mut system = deque(&[0.5; 10]);
        // An in-person meeting: the system buffer is never read.
        let out = mix_buffers(&mut mic, &mut system, false);
        assert_eq!(out.pcm, vec![to_i16(0.5); 10]);
        assert_eq!(system.len(), 10);
    }

    #[test]
    fn levels_are_linear_rms_and_peak_and_reset_when_taken() {
        let mut mic = deque(&[0.5, -0.5, 0.5, -0.5]);
        let mut system = deque(&[0.0, 0.0, 0.0, 1.0]);
        let drained = mix_buffers(&mut mic, &mut system, true);
        let mut acc = LevelsAcc::default();
        acc.mic.merge(drained.mic);
        acc.system.merge(drained.system);
        let levels = acc.take();
        assert!((levels.mic_rms - 0.5).abs() < 1e-6);
        assert!((levels.mic_peak - 0.5).abs() < 1e-6);
        assert!((levels.system_rms - 0.5).abs() < 1e-6);
        assert!((levels.system_peak - 1.0).abs() < 1e-6);
        assert_eq!(acc.take(), SourceLevels::default());
    }
}
