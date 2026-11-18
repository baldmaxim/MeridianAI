//! The pieces of the live link that carry no network: the pause between
//! attempts and the reporting of its state to the UI.

use std::sync::{Arc, Mutex, MutexGuard};
use std::time::Duration;

use tauri::AppHandle;
use tauri_specta::Event;

use super::live_types::{next_state, LinkEvent, LiveState, LiveStatus, MeetingLive};

/// The pause before the next attempt: 1, 2, 4, 8, 15, 30 s.
#[derive(Debug, Default)]
pub(super) struct Backoff {
    attempt: u32,
}

impl Backoff {
    pub(super) fn next_delay(&mut self) -> Duration {
        const STEPS: [u64; 6] = [1, 2, 4, 8, 15, 30];
        let step = STEPS[(self.attempt as usize).min(STEPS.len() - 1)];
        self.attempt = self.attempt.saturating_add(1);
        Duration::from_secs(step)
    }

    pub(super) fn reset(&mut self) {
        self.attempt = 0;
    }
}

/// Tells the UI what the link is doing (only when it changes).
pub(super) struct Reporter {
    pub(super) app: AppHandle,
    pub(super) meeting_id: String,
    pub(super) status: Arc<Mutex<LiveStatus>>,
}

impl Reporter {
    fn lock(&self) -> MutexGuard<'_, LiveStatus> {
        self.status.lock().unwrap_or_else(|e| e.into_inner())
    }

    pub(super) fn state(&self) -> LiveState {
        self.lock().state
    }

    pub(super) fn set(&self, state: LiveState, message: Option<String>) {
        let status = LiveStatus { state, message };
        {
            let mut current = self.lock();
            if *current == status {
                return;
            }
            *current = status.clone();
        }
        let _ = MeetingLive {
            meeting_id: self.meeting_id.clone(),
            status,
        }
        .emit(&self.app);
    }

    pub(super) fn link(&self, event: LinkEvent, message: Option<String>) {
        self.set(next_state(self.state(), event), message);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn pauses_grow_and_start_over_after_a_good_connection() {
        let mut backoff = Backoff::default();
        let secs: Vec<u64> = (0..8).map(|_| backoff.next_delay().as_secs()).collect();
        assert_eq!(secs, [1, 2, 4, 8, 15, 30, 30, 30]);
        backoff.reset();
        assert_eq!(backoff.next_delay().as_secs(), 1);
    }
}
