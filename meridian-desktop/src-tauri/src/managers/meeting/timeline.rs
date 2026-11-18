//! Where the recording is now, counted in samples written to the audio files.
//!
//! The audio on disk is the truth about meeting time: a phrase's time, the
//! offset of a live connection and the catching up of a restarted channel all
//! read it, and none reads a clock. A clock gives different answers across a
//! sleep (`Instant` keeps ticking on Windows and stops on Linux and macOS),
//! while samples simply do not arrive while the computer sleeps.

use std::sync::atomic::{AtomicU64, Ordering};

use super::live_mix::Source;
use super::storage::SAMPLE_RATE;

/// Samples each channel has recorded in the meeting so far, those of the
/// earlier sessions of a resumed meeting included.
#[derive(Debug, Default)]
pub(super) struct Timeline {
    mic: AtomicU64,
    system: AtomicU64,
}

impl Timeline {
    /// A meeting that already has `mic` and `system` samples on disk.
    pub(super) fn new(mic: u64, system: u64) -> Self {
        Self {
            mic: AtomicU64::new(mic),
            system: AtomicU64::new(system),
        }
    }

    fn counter(&self, source: Source) -> &AtomicU64 {
        match source {
            Source::Mic => &self.mic,
            Source::System => &self.system,
        }
    }

    pub(super) fn add(&self, source: Source, samples: usize) {
        self.counter(source)
            .fetch_add(samples as u64, Ordering::Relaxed);
    }

    pub(super) fn samples(&self, source: Source) -> u64 {
        self.counter(source).load(Ordering::Relaxed)
    }

    /// The channel that is furthest on sets the meeting time.
    pub(super) fn max_samples(&self) -> u64 {
        self.samples(Source::Mic).max(self.samples(Source::System))
    }

    /// Meeting time in seconds.
    pub(super) fn seconds(&self) -> f64 {
        self.max_samples() as f64 / f64::from(SAMPLE_RATE)
    }

    /// How far `source` is behind the furthest channel: the silence it needs
    /// to be level with it again.
    pub(super) fn lag(&self, source: Source) -> usize {
        (self.max_samples() - self.samples(source)) as usize
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn time_follows_the_furthest_channel_and_the_lag_of_the_other() {
        let t = Timeline::new(0, 0);
        t.add(Source::Mic, 32_000);
        t.add(Source::System, 16_000);
        assert_eq!(t.seconds(), 2.0);
        assert_eq!(t.lag(Source::System), 16_000);
        assert_eq!(t.lag(Source::Mic), 0);
        // The channel caught up with silence: level again.
        t.add(Source::System, t.lag(Source::System));
        assert_eq!(t.lag(Source::System), 0);
    }

    #[test]
    fn a_resumed_meeting_starts_where_its_audio_ends() {
        let t = Timeline::new(48_000, 40_000);
        assert_eq!(t.seconds(), 3.0);
        // The shorter channel is padded at the start of the new session.
        assert_eq!(t.lag(Source::System), 8_000);
    }
}
