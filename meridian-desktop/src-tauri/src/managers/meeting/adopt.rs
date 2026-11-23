//! A meeting of the server this device has no copy of (made on the site or on
//! another PC), taken into the app to continue it ("Continue in the app").
//!
//! The local row is only a shell: the phrases of the server are not imported.
//! It starts "now", so the phrases recorded from here on land after the old
//! ones on the server (their wall clock goes from this moment), and the audio
//! goes under a revision the server does not hold yet.

use anyhow::Result;

use super::db::{CaptureMode, MeetingDb, MeetingInfo, MeetingStatus};
use super::{
    clean_context, clean_name, now_iso, MeetingManager, MAX_CONTEXT_TEXT_CHARS,
    MAX_NEGOTIATION_TYPE_CHARS,
};

/// What the server answered to `adopt`, as the app needs it.
#[derive(Clone, Debug, PartialEq)]
pub struct AdoptedMeeting {
    /// The id the server links the meeting under: the local meeting's id.
    pub client_uuid: String,
    pub server_meeting_id: i64,
    pub title: Option<String>,
    pub capture_mode: String,
    pub customer_id: Option<i64>,
    pub object_id: Option<i64>,
    pub customer_name: Option<String>,
    pub object_name: Option<String>,
    pub max_speakers: Option<i64>,
    /// The context of the meeting on the server; kept as the local one.
    pub negotiation_type: Option<String>,
    pub key_terms: Option<String>,
    pub opponent_weaknesses: Option<String>,
    pub next_audio_revision: u32,
}

impl MeetingDb {
    /// Makes sure the adopted meeting is in the local database, stopped and
    /// synced, ready for `resume_reopened_meeting`. A local row with that id
    /// (the meeting was linked from this very app) is kept as it is; only its
    /// audio revision is raised so the next upload cannot meet an old name.
    pub fn register_adopted(&self, adopted: &AdoptedMeeting, started_at: &str) -> Result<()> {
        if self.get_meeting(&adopted.client_uuid)?.is_some() {
            self.set_server_meeting_id_if_missing(&adopted.client_uuid, adopted.server_meeting_id)?;
            return self.raise_audio_revision(&adopted.client_uuid, adopted.next_audio_revision);
        }
        // A meeting without a title stays without one: the app does not make
        // up a name that would then go to the server (which ignores a blank
        // title anyway); the screens show "Untitled" for it.
        let title = adopted.title.as_deref().map_or("", str::trim).to_string();
        let meeting = MeetingInfo {
            id: adopted.client_uuid.clone(),
            title,
            capture_mode: CaptureMode::parse(&adopted.capture_mode)
                .unwrap_or(CaptureMode::InPerson),
            started_at: started_at.to_string(),
            ended_at: Some(started_at.to_string()),
            status: MeetingStatus::Stopped,
            duration_seconds: 0.0,
            server_meeting_id: Some(adopted.server_meeting_id),
            sync_state: "synced".to_string(),
            sync_error: None,
            synced_at: Some(started_at.to_string()),
            customer_id: adopted.customer_id,
            object_id: adopted.object_id,
            customer_name: clean_name(adopted.customer_name.as_deref()),
            object_name: clean_name(adopted.object_name.as_deref()),
            audio_state: "pending".to_string(),
            negotiation_type: clean_context(
                adopted.negotiation_type.as_deref(),
                MAX_NEGOTIATION_TYPE_CHARS,
            ),
            key_terms: clean_context(adopted.key_terms.as_deref(), MAX_CONTEXT_TEXT_CHARS),
            opponent_weaknesses: clean_context(
                adopted.opponent_weaknesses.as_deref(),
                MAX_CONTEXT_TEXT_CHARS,
            ),
            max_speakers: adopted.max_speakers.filter(|n| (2..=10).contains(n)),
            web_url: None,
        };
        self.insert_meeting_with_revision(&meeting, adopted.next_audio_revision)
    }

    fn set_server_meeting_id_if_missing(&self, id: &str, server_meeting_id: i64) -> Result<()> {
        self.conn().execute(
            "UPDATE meetings SET server_meeting_id = ?2 WHERE id = ?1 AND server_meeting_id IS NULL",
            rusqlite::params![id, server_meeting_id],
        )?;
        Ok(())
    }

    /// The revision the audio of the *next* recording gets is at least
    /// `revision`: continuing a sent meeting adds one when a channel was
    /// confirmed (`mark_recording_reopened`), so that one is counted in here.
    fn raise_audio_revision(&self, id: &str, revision: u32) -> Result<()> {
        self.conn().execute(
            "UPDATE meetings SET audio_revision = MAX(audio_revision, ?2 - (audio_done != ''))
             WHERE id = ?1",
            rusqlite::params![id, i64::from(revision)],
        )?;
        Ok(())
    }
}

impl MeetingManager {
    /// Puts an adopted meeting into the local database; the caller continues
    /// it with `resume_reopened_meeting` (the server has reopened it already).
    pub fn register_adopted(&self, adopted: &AdoptedMeeting) -> Result<(), String> {
        self.db
            .register_adopted(adopted, &now_iso())
            .map_err(|e| format!("Ошибка базы встреч: {e:#}"))
    }
}
