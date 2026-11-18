//! An interrupted meeting (the app crashed, the computer went to sleep for
//! good, the power was cut) is not finalized on the server at once: the user
//! may continue it. Its text and notes still go, so they are safe on the
//! server; the audio and the finalization wait for the user's "Finish" or for
//! the hold to run out.

use chrono::{DateTime, Duration, Utc};

use std::time::Instant;

use super::{SyncCore, SyncManager};
use crate::managers::meeting::{MeetingInfo, MeetingStatus};

/// How long an interrupted meeting waits for the user before it is finished.
pub const INTERRUPTED_HOLD: Duration = Duration::hours(12);

/// Between two looks at a held meeting (it only waits, nothing to send).
pub const HOLD_RECHECK: std::time::Duration = std::time::Duration::from_secs(10 * 60);

/// Whether the hold of an interrupted meeting is over. An end time that does
/// not parse counts as over: a meeting must not hang for ever.
pub fn hold_expired(ended_at: Option<&str>, now: DateTime<Utc>) -> bool {
    let Some(ended) = ended_at.and_then(|t| DateTime::parse_from_rfc3339(t).ok()) else {
        return true;
    };
    now.signed_duration_since(ended.with_timezone(&Utc)) >= INTERRUPTED_HOLD
}

/// Whether the meeting is interrupted and still held back at `now`.
pub fn is_held(meeting: &MeetingInfo, now: DateTime<Utc>) -> bool {
    meeting.status == MeetingStatus::Interrupted && !hold_expired(meeting.ended_at.as_deref(), now)
}

impl SyncCore {
    /// Nothing more to send until the user decides: look again rarely.
    pub(super) fn hold_back(&self, id: &str) {
        // The user may have pressed "Finish" while the pass ran: then the
        // meeting must not wait.
        let still_held = self
            .db
            .get_meeting(id)
            .ok()
            .flatten()
            .is_some_and(|m| m.status == MeetingStatus::Interrupted);
        if still_held {
            self.inner()
                .backoff
                .insert(id.to_string(), (0, Instant::now() + HOLD_RECHECK));
        }
    }

    /// Forgets the waiting time of one meeting (it was held, now it may go).
    pub fn release(&self, id: &str) {
        self.inner().backoff.remove(id);
    }
}

impl SyncManager {
    /// The user finished an interrupted meeting: send the rest now.
    pub fn release_meeting(&self, id: &str) {
        self.core.release(id);
        self.wake();
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn at(text: &str) -> DateTime<Utc> {
        DateTime::parse_from_rfc3339(text)
            .unwrap()
            .with_timezone(&Utc)
    }

    #[test]
    fn the_hold_lasts_twelve_hours() {
        let ended = Some("2026-01-01T10:00:00.000Z");
        assert!(!hold_expired(ended, at("2026-01-01T10:00:01Z")));
        assert!(!hold_expired(ended, at("2026-01-01T21:59:59Z")));
        assert!(hold_expired(ended, at("2026-01-01T22:00:00Z")));
        assert!(hold_expired(ended, at("2026-01-03T00:00:00Z")));
    }

    #[test]
    fn a_missing_or_broken_end_time_does_not_hold() {
        assert!(hold_expired(None, at("2026-01-01T10:00:00Z")));
        assert!(hold_expired(Some("вчера"), at("2026-01-01T10:00:00Z")));
    }
}
