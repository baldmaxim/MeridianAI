//! The app quits while a meeting records.

use std::time::Duration;

use log::{info, warn};

use super::session::Slot;
use super::MeetingManager;

/// On quitting, the recognizer gets this long to finish the phrases in its
/// queue; what is left is dropped (the audio is on disk, the refinement after
/// the stop recognizes it).
const EXIT_DRAIN_TIMEOUT: Duration = Duration::from_secs(5);

impl MeetingManager {
    /// Stops the running meeting properly: the audio files are closed and
    /// forced to the disk, and the meeting counts as stopped (it would be
    /// "interrupted" if the process were just killed). Returns the id of the
    /// meeting that was stopped.
    pub fn stop_for_exit(&self) -> Option<String> {
        let session = {
            let mut slot = self.slot();
            match std::mem::replace(&mut *slot, Slot::Busy) {
                Slot::Active(session) => session,
                other => {
                    *slot = other;
                    return None;
                }
            }
        };
        info!("Stopping the meeting before the app quits");
        let result = self.finish_session(*session, EXIT_DRAIN_TIMEOUT);
        *self.slot() = Slot::Idle;
        match result {
            Ok(meeting) => {
                self.reindex(&meeting.id);
                Some(meeting.id)
            }
            Err(e) => {
                warn!("Stopping the meeting before the quit failed: {e}");
                None
            }
        }
    }
}
