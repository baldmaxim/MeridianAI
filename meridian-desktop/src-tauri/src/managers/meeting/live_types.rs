//! Types of the live recognition on the server: the link state shown in the
//! UI, its events, and the pure rules of how the state changes.

use serde::Serialize;
use specta::Type;
use tauri_specta::Event;

/// How the live text of the meeting is doing.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Type)]
#[serde(rename_all = "snake_case")]
pub enum LiveState {
    /// No live text from the server: the local model recognizes (or nothing).
    #[default]
    Off,
    /// The first connection is being made.
    Connecting,
    /// The server recognizes the sound as it is recorded.
    Online,
    /// The link was lost; a new connection is being made.
    Reconnecting,
    /// No link: the meeting is recorded like a dictaphone (the text comes
    /// after the stop). The next attempt follows, unless the message says why
    /// it will not.
    Recorder,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Type)]
pub struct LiveStatus {
    pub state: LiveState,
    /// Why there is no link (shown to the user).
    pub message: Option<String>,
}

/// The state of the live link changed.
#[derive(Clone, Debug, Serialize, Type, Event)]
pub struct MeetingLive {
    pub meeting_id: String,
    pub status: LiveStatus,
}

/// The phrase the server is hearing right now (not final; empty: gone).
#[derive(Clone, Debug, Serialize, Type, Event)]
pub struct MeetingPartial {
    pub meeting_id: String,
    pub text: String,
}

/// What happened to the link.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(super) enum LinkEvent {
    /// A connection attempt begins.
    Attempt,
    /// The socket is open.
    Connected,
    /// The link dropped, or the attempt failed.
    Lost,
}

/// The state after `event`.
pub(super) fn next_state(current: LiveState, event: LinkEvent) -> LiveState {
    match (current, event) {
        (LiveState::Off, _) => LiveState::Off,
        (_, LinkEvent::Connected) => LiveState::Online,
        (_, LinkEvent::Lost) => LiveState::Recorder,
        (LiveState::Connecting, LinkEvent::Attempt) => LiveState::Connecting,
        (_, LinkEvent::Attempt) => LiveState::Reconnecting,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn online_goes_to_recorder_and_back() {
        let mut state = LiveState::Connecting;
        state = next_state(state, LinkEvent::Attempt);
        assert_eq!(state, LiveState::Connecting);
        state = next_state(state, LinkEvent::Connected);
        assert_eq!(state, LiveState::Online);
        state = next_state(state, LinkEvent::Lost);
        assert_eq!(state, LiveState::Recorder);
        state = next_state(state, LinkEvent::Attempt);
        assert_eq!(state, LiveState::Reconnecting);
        // An attempt that fails goes back to the dictaphone.
        state = next_state(state, LinkEvent::Lost);
        assert_eq!(state, LiveState::Recorder);
        state = next_state(state, LinkEvent::Attempt);
        state = next_state(state, LinkEvent::Connected);
        assert_eq!(state, LiveState::Online);
    }

    #[test]
    fn a_meeting_without_the_server_stays_off() {
        for event in [LinkEvent::Attempt, LinkEvent::Connected, LinkEvent::Lost] {
            assert_eq!(next_state(LiveState::Off, event), LiveState::Off);
        }
    }
}
