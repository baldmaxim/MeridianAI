//! "The computer's sound is silent": the system channel of an online meeting
//! stays quiet for a minute (the wrong device chosen, or the call is muted).

use std::time::Duration;

/// Level on `level_of`'s -60..0 dBFS scale: 0.05 = -57 dBFS, under any real sound and room noise (a muted or wrong device gives digital zero).
pub(super) const SILENCE_LEVEL: f32 = 0.05;
/// How long the channel must stay under the level, without a break.
pub(super) const SILENCE_AFTER: Duration = Duration::from_secs(60);

#[derive(Default)]
pub(super) struct SilenceDetector {
    /// Since when the level has been under the threshold, without a break.
    quiet_since: Option<Duration>,
    reported: bool,
}

impl SilenceDetector {
    /// Feed the channel's level at time `now` (any fixed start). `Some(true)`:
    /// it just became silent, once; `Some(false)`: the sound came back after that.
    pub(super) fn update(&mut self, level: f32, now: Duration) -> Option<bool> {
        if level >= SILENCE_LEVEL {
            self.quiet_since = None;
            return std::mem::take(&mut self.reported).then_some(false);
        }
        let since = *self.quiet_since.get_or_insert(now);
        if !self.reported && now.saturating_sub(since) >= SILENCE_AFTER {
            self.reported = true;
            return Some(true);
        }
        None
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn secs(n: u64) -> Duration {
        Duration::from_secs(n)
    }

    #[test]
    fn reports_silence_once_after_a_minute() {
        let mut d = SilenceDetector::default();
        assert_eq!(d.update(0.0, secs(0)), None);
        assert_eq!(d.update(0.01, secs(59)), None);
        assert_eq!(d.update(0.0, secs(60)), Some(true));
        assert_eq!(d.update(0.0, secs(61)), None);
        assert_eq!(d.update(0.0, secs(500)), None);
    }

    #[test]
    fn sound_resets_the_count_and_a_report_is_followed_by_the_return() {
        let mut d = SilenceDetector::default();
        d.update(0.0, secs(0));
        // A sound at 50 s: the minute starts over, nothing was reported.
        assert_eq!(d.update(0.3, secs(50)), None);
        assert_eq!(d.update(0.0, secs(51)), None);
        assert_eq!(d.update(0.0, secs(110)), None);
        assert_eq!(d.update(0.0, secs(111)), Some(true));
        assert_eq!(d.update(0.2, secs(120)), Some(false));
        assert_eq!(d.update(0.2, secs(121)), None);
        // And again: a new silence is reported anew.
        assert_eq!(d.update(0.0, secs(122)), None);
        assert_eq!(d.update(0.0, secs(182)), Some(true));
    }

    #[test]
    fn a_level_at_the_threshold_is_sound() {
        let mut d = SilenceDetector::default();
        d.update(0.0, secs(0));
        assert_eq!(d.update(SILENCE_LEVEL, secs(100)), None);
        assert_eq!(d.update(0.0, secs(101)), None);
    }
}
