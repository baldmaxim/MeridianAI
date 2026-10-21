//! Reading and editing meetings, notes and exported audio.

use std::sync::Arc;

use log::warn;
use tauri::Manager;

use super::session::Slot;
use super::{
    clean_name, export_channel_wav, io_err, now_iso, short_id, storage, ActiveMeetingState, AudioFile,
    MeetingDetails, MeetingInfo, MeetingManager, Note, NoteInput, AUDIO_CHANNELS,
};
use crate::managers::sync::account::{meeting_web_url, AccountStore};

impl MeetingManager {
    /* -------------------------- queries and edits -------------------------- */

    /// Adds the link to the site for a meeting the server has.
    fn with_web_url(&self, mut meeting: MeetingInfo) -> MeetingInfo {
        let server_url = self
            .app
            .try_state::<Arc<AccountStore>>()
            .and_then(|accounts| accounts.get())
            .map(|account| account.server_url);
        if let (Some(server_url), Some(id)) = (server_url, meeting.server_meeting_id) {
            meeting.web_url = Some(meeting_web_url(&server_url, id));
        }
        meeting
    }

    pub fn get_active_meeting(&self) -> Result<Option<ActiveMeetingState>, String> {
        let (id, elapsed, queue_len, levels) = {
            let slot = self.slot();
            let Slot::Active(session) = &*slot else {
                return Ok(None);
            };
            (
                session.meeting_id.clone(),
                session.base_seconds + session.started.elapsed().as_secs_f64(),
                session.queue.len(),
                session.levels.load(),
            )
        };
        let meeting = self
            .db
            .get_meeting(&id)
            .map_err(io_err)?
            .ok_or_else(|| "Встреча не найдена".to_string())?;
        Ok(Some(ActiveMeetingState {
            meeting: self.with_web_url(meeting),
            elapsed_seconds: elapsed,
            queue_len: queue_len as u32,
            levels,
        }))
    }

    pub fn list_meetings(&self) -> Result<Vec<MeetingInfo>, String> {
        let meetings = self.db.list_meetings().map_err(io_err)?;
        Ok(meetings.into_iter().map(|m| self.with_web_url(m)).collect())
    }

    pub fn get_meeting(&self, id: &str) -> Result<MeetingDetails, String> {
        let meeting = self
            .db
            .get_meeting(id)
            .map_err(io_err)?
            .ok_or_else(|| "Встреча не найдена".to_string())?;
        Ok(MeetingDetails {
            segments: self.db.list_segments(id).map_err(io_err)?,
            notes: self.db.list_notes(id).map_err(io_err)?,
            meeting: self.with_web_url(meeting),
        })
    }

    pub fn rename_meeting(&self, id: &str, title: &str) -> Result<(), String> {
        let title = title.trim();
        if title.is_empty() {
            return Err("Название не может быть пустым".to_string());
        }
        match self.db.rename_meeting(id, title).map_err(io_err)? {
            true => {
                self.reindex(id);
                Ok(())
            }
            false => Err("Встреча не найдена".to_string()),
        }
    }

    /// Sets or clears the meeting's project. A meeting that is not on the server
    /// yet takes it along with its first upload; the server does not change the
    /// project of a meeting it already has, so for those it stays local.
    pub fn set_meeting_project(
        &self,
        id: &str,
        customer_id: Option<i64>,
        object_id: Option<i64>,
        customer_name: Option<String>,
        object_name: Option<String>,
    ) -> Result<MeetingInfo, String> {
        let customer_name = clean_name(customer_name.as_deref());
        let object_name = clean_name(object_name.as_deref());
        let found = self
            .db
            .set_meeting_project(
                id,
                customer_id,
                customer_name.as_deref(),
                object_id,
                object_name.as_deref(),
            )
            .map_err(io_err)?;
        if !found {
            return Err("Встреча не найдена".to_string());
        }
        let meeting = self
            .db
            .get_meeting(id)
            .map_err(io_err)?
            .ok_or_else(|| "Встреча не найдена".to_string())?;
        Ok(self.with_web_url(meeting))
    }

    /// Whether a meeting is being recorded, set up or wound up right now.
    fn is_busy_with(&self, id: &str) -> bool {
        match &*self.slot() {
            Slot::Idle => false,
            Slot::Busy => true,
            Slot::Active(session) => session.meeting_id == id,
        }
    }

    pub fn delete_meeting(&self, id: &str) -> Result<(), String> {
        if self.is_busy_with(id) {
            return Err("Активную встречу удалить нельзя: сначала остановите её".to_string());
        }
        if !self.db.delete_meeting(id).map_err(io_err)? {
            return Err("Встреча не найдена".to_string());
        }
        if let Err(e) = self.db.remove_local_index(id) {
            warn!("Cannot drop meeting {id} from the search index: {e:#}");
        }
        match std::fs::remove_dir_all(storage::meeting_dir(&self.root, id)) {
            Ok(()) => Ok(()),
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(()),
            Err(e) => Err(format!(
                "Встреча удалена, но папку со звуком удалить не удалось: {e}"
            )),
        }
    }

    pub fn upsert_note(&self, input: NoteInput) -> Result<Note, String> {
        if self
            .db
            .get_meeting(&input.meeting_id)
            .map_err(io_err)?
            .is_none()
        {
            return Err("Встреча не найдена".to_string());
        }
        let note = Note {
            id: input
                .id
                .filter(|id| !id.is_empty())
                .unwrap_or_else(short_id),
            meeting_id: input.meeting_id,
            at_seconds: input.at_seconds.max(0.0),
            text: input.text,
            updated_at: now_iso(),
        };
        self.db.upsert_note(&note).map_err(io_err)?;
        self.reindex(&note.meeting_id);
        Ok(note)
    }

    pub fn delete_note(&self, id: &str) -> Result<(), String> {
        let meeting_id = self.db.note_meeting_id(id).map_err(io_err)?;
        self.db.delete_note(id).map_err(io_err)?;
        if let Some(meeting_id) = meeting_id {
            self.reindex(&meeting_id);
        }
        Ok(())
    }

    /// WAV files of the meeting's channels, joined from the recorded pieces.
    pub fn export_meeting_audio(&self, id: &str) -> Result<Vec<AudioFile>, String> {
        if self.is_busy_with(id) {
            return Err("Звук активной встречи можно выгрузить после остановки".to_string());
        }
        if self.db.get_meeting(id).map_err(io_err)?.is_none() {
            return Err("Встреча не найдена".to_string());
        }
        let audio = storage::audio_dir(&self.root, id);
        let mut files = Vec::new();
        for channel in AUDIO_CHANNELS {
            if storage::list_pieces(&audio, channel).is_empty() {
                continue;
            }
            let path = export_channel_wav(&self.root, id, channel).map_err(|e| format!("{e:#}"))?;
            files.push(AudioFile {
                channel: channel.to_string(),
                path: path.to_string_lossy().into_owned(),
            });
        }
        if files.is_empty() {
            return Err("У встречи нет записанного звука".to_string());
        }
        Ok(files)
    }
}
