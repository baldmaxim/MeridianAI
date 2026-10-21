//! Types of the meeting commands and events.

use serde::{Deserialize, Serialize};
use specta::Type;
use tauri_specta::Event;

use super::{CaptureDevice, CaptureMode, MeetingInfo, Note, Segment};

#[derive(Clone, Debug, Deserialize, Type)]
pub struct StartMeetingRequest {
    pub title: String,
    pub capture_mode: CaptureMode,
    /// `None`: the microphone chosen in settings, else the system default.
    pub mic_device_id: Option<String>,
    /// `None`: the default playback device (Windows) or the first monitor (Linux).
    pub system_device_id: Option<String>,
    /// The project of the meeting (ids from the site's reference book and their
    /// names, for showing offline). All optional.
    #[serde(default)]
    #[specta(optional)]
    pub customer_id: Option<i64>,
    #[serde(default)]
    #[specta(optional)]
    pub object_id: Option<i64>,
    #[serde(default)]
    #[specta(optional)]
    pub customer_name: Option<String>,
    #[serde(default)]
    #[specta(optional)]
    pub object_name: Option<String>,
}

#[derive(Clone, Debug, Serialize, Type)]
pub struct CaptureDevices {
    pub inputs: Vec<CaptureDevice>,
    pub system_sources: Vec<CaptureDevice>,
    pub system_supported: bool,
}

#[derive(Clone, Debug, Serialize, Type)]
pub struct MeetingDetails {
    pub meeting: MeetingInfo,
    pub segments: Vec<Segment>,
    pub notes: Vec<Note>,
}

#[derive(Clone, Debug, Serialize, Type)]
pub struct ActiveMeetingState {
    pub meeting: MeetingInfo,
    pub elapsed_seconds: f64,
    pub queue_len: u32,
    pub levels: MeetingLevels,
}

#[derive(Clone, Debug, Deserialize, Type)]
pub struct NoteInput {
    /// Set to edit an existing note.
    pub id: Option<String>,
    pub meeting_id: String,
    pub at_seconds: f64,
    pub text: String,
}

#[derive(Clone, Debug, Serialize, Type)]
pub struct AudioFile {
    pub channel: String,
    pub path: String,
}

/// A recognized phrase, as it is stored.
#[derive(Clone, Debug, Serialize, Type, Event)]
pub struct MeetingSegment {
    pub segment: Segment,
}

/// Input levels 0..1 of the two channels.
#[derive(Clone, Copy, Debug, Default, Serialize, Type, Event)]
pub struct MeetingLevels {
    pub mic: f32,
    pub system: f32,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Type)]
#[serde(rename_all = "snake_case")]
pub enum MeetingStateKind {
    Started,
    /// Capture is closed; the rest of the queue is being recognized.
    Stopping,
    Stopped,
    /// A channel's device failed or its audio can't be written.
    DeviceError,
    /// A phrase could not be recognized or stored.
    RecognitionError,
    /// The queue length changed.
    Queue,
}

#[derive(Clone, Debug, Serialize, Type, Event)]
pub struct MeetingState {
    pub kind: MeetingStateKind,
    pub meeting_id: String,
    pub queue_len: u32,
    pub channel: Option<String>,
    pub message: Option<String>,
}
