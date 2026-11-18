//! Finds that the computer was asleep (or frozen) by the gap between two looks
//! of a thread that looks every few hundred milliseconds. No OS API: a thread
//! that ticks often and finds the wall clock — or the monotonic one — several
//! seconds further on was not running in between. Which clocks keep going
//! through a sleep differs by OS (`Instant` does on Windows, not on Linux or
//! macOS), so the larger of the two gaps is taken. A clock set backwards is no gap.

use std::time::{Duration, Instant, SystemTime};

/// A thread that ticks every few hundred ms was away this long: a sleep.
pub(super) const SLEEP_GAP: Duration = Duration::from_secs(5);

/// A stretch the computer did not run.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(super) struct Gap {
    /// The wall clock at the look before it, and at the look after.
    pub(super) from: SystemTime,
    pub(super) to: SystemTime,
    pub(super) length: Duration,
}

pub(super) struct GapDetector {
    wall: SystemTime,
    mono: Instant,
}

impl GapDetector {
    pub(super) fn new() -> Self {
        Self {
            wall: SystemTime::now(),
            mono: Instant::now(),
        }
    }

    /// A look at the clocks: `Some` when more than [`SLEEP_GAP`] has passed
    /// since the previous look, by either clock.
    pub(super) fn observe(&mut self, wall: SystemTime, mono: Instant) -> Option<Gap> {
        let wall_gap = wall.duration_since(self.wall).unwrap_or_default();
        let mono_gap = mono.saturating_duration_since(self.mono);
        let from = self.wall;
        self.wall = wall;
        self.mono = mono;
        let length = wall_gap.max(mono_gap);
        (length > SLEEP_GAP).then_some(Gap {
            from,
            to: wall,
            length,
        })
    }

    pub(super) fn look(&mut self) -> Option<Gap> {
        self.observe(SystemTime::now(), Instant::now())
    }

    /// Forgets the time since the last look (after work that took long on purpose).
    pub(super) fn touch(&mut self) {
        self.wall = SystemTime::now();
        self.mono = Instant::now();
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn detector() -> (GapDetector, SystemTime, Instant) {
        let (wall, mono) = (SystemTime::now(), Instant::now());
        (GapDetector { wall, mono }, wall, mono)
    }

    #[test]
    fn ordinary_ticks_are_no_gap() {
        let (mut d, wall, mono) = detector();
        let tick = Duration::from_millis(250);
        assert_eq!(d.observe(wall + tick, mono + tick), None);
        assert_eq!(d.observe(wall + tick * 2, mono + tick * 2), None);
        // A stall of a few seconds is still no sleep.
        let stall = Duration::from_secs(4);
        assert_eq!(d.observe(wall + stall, mono + stall), None);
    }

    #[test]
    fn a_sleep_is_seen_whether_the_monotonic_clock_ran_through_it_or_not() {
        let night = Duration::from_secs(8 * 3600);
        // Windows: both clocks went on.
        let (mut d, wall, mono) = detector();
        let gap = d.observe(wall + night, mono + night).expect("a gap");
        assert_eq!(gap.length, night);
        assert_eq!(gap.from, wall);
        // Linux and macOS: only the wall clock did.
        let (mut d, wall, mono) = detector();
        let gap = d
            .observe(wall + night, mono + Duration::from_millis(250))
            .expect("a gap");
        assert_eq!(gap.length, night);
        // And the look after it is quiet again.
        assert_eq!(
            d.observe(
                wall + night + Duration::from_millis(250),
                mono + Duration::from_millis(500)
            ),
            None
        );
    }

    #[test]
    fn a_clock_set_backwards_is_no_gap() {
        let (mut d, wall, mono) = detector();
        let back = wall - Duration::from_secs(3600);
        assert_eq!(d.observe(back, mono + Duration::from_millis(250)), None);
    }
}
