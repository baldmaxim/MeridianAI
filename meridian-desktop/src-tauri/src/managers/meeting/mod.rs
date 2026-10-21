//! Meeting mode: hours-long recording of one or two channels straight to disk,
//! phrase-by-phrase recognition while it goes on, and a local database of
//! meetings, segments and notes. Everything works offline.
//!
//! Threads of an active meeting:
//!
//! ```text
//! capture (per channel) -> ChannelPipe: PCM file, then ChanMsg
//!   -> phrase cutter (per channel, VAD) -> PhraseQueue
//!   -> recognizer (one) -> meetings.db + `meeting-segment`
//! ticker: `meeting-levels` ~10 Hz, queue length and device errors
//! ```

mod api;
mod capture;
mod db;
mod db_sync;
mod queries;
mod recognizer;
mod segmenter;
mod session;
mod storage;
#[cfg(test)]
mod tests;
mod workers;

use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex, MutexGuard};
use std::time::Duration;

use anyhow::Result;
use chrono::{Local, SecondsFormat, Utc};
use log::{info, warn};
use tauri::AppHandle;
use tauri_specta::Event;

pub use api::{
    ActiveMeetingState, AudioFile, CaptureDevices, MeetingDetails, MeetingLevels, MeetingSegment,
    MeetingState, MeetingStateKind, NoteInput, StartMeetingRequest,
};
pub use capture::CaptureDevice;
pub use db::{CaptureMode, MeetingDb, MeetingInfo, MeetingStatus, Note, Segment};
use session::{Session, Slot};
pub use storage::export_channel_wav;

/// How long `stop` waits for the queue to drain before giving up on the rest.
const DRAIN_TIMEOUT: Duration = Duration::from_secs(60);
/// `meeting-levels` rate.
const TICK: Duration = Duration::from_millis(100);

const CHANNEL_MIC: &str = "mic";
const CHANNEL_SYSTEM: &str = "system";
const CHANNEL_MIXED: &str = "mixed";
const AUDIO_CHANNELS: [&str; 2] = [CHANNEL_MIC, CHANNEL_SYSTEM];

/// Whether this OS can capture what the computer plays.
const SYSTEM_AUDIO_SUPPORTED: bool = !cfg!(target_os = "macos");

/* ------------------------------ helpers ------------------------------ */

fn now_iso() -> String {
    Utc::now().to_rfc3339_opts(SecondsFormat::Millis, true)
}

fn short_id() -> String {
    uuid::Uuid::new_v4().simple().to_string()[..16].to_string()
}

/// A project's name as stored: trimmed, `None` when empty.
fn clean_name(name: Option<&str>) -> Option<String> {
    name.map(str::trim)
        .filter(|name| !name.is_empty())
        .map(str::to_string)
}

fn io_err(e: impl std::fmt::Display) -> String {
    e.to_string()
}

/// Marks meetings left in `recording` by a crash or a kill as `interrupted`,
/// with the time of their last audio and the duration the files add up to.
pub fn recover_interrupted(db: &MeetingDb, meetings_root: &Path) -> Result<usize> {
    let ids = db.recording_meeting_ids()?;
    for id in &ids {
        let audio = storage::audio_dir(meetings_root, id);
        let duration = AUDIO_CHANNELS
            .iter()
            .map(|channel| storage::channel_duration_seconds(&audio, channel))
            .fold(0.0, f64::max);
        let ended_at = storage::last_audio_write(&audio)
            .map(|time| {
                chrono::DateTime::<Utc>::from(time).to_rfc3339_opts(SecondsFormat::Millis, true)
            })
            .or_else(|| db.get_meeting(id).ok().flatten().map(|m| m.started_at))
            .unwrap_or_else(now_iso);
        db.finish_meeting(id, MeetingStatus::Interrupted, &ended_at, duration)?;
    }
    Ok(ids.len())
}

/// Channels of the meeting that have audio on disk, with the size of their WAV.
pub fn recorded_channels(meetings_root: &Path, meeting_id: &str) -> Vec<(&'static str, u64)> {
    let audio = storage::audio_dir(meetings_root, meeting_id);
    AUDIO_CHANNELS
        .iter()
        .filter(|channel| !storage::list_pieces(&audio, channel).is_empty())
        .map(|channel| (*channel, storage::channel_wav_size(&audio, channel)))
        .collect()
}

/// Writes `samples` as the meeting's audio for `channel` (a test fixture).
#[cfg(test)]
pub(crate) fn write_test_audio(
    meetings_root: &Path,
    meeting_id: &str,
    channel: &str,
    samples: &[i16],
) {
    let audio = storage::audio_dir(meetings_root, meeting_id);
    let mut writer = storage::PcmWriter::new(&audio, channel, 16_000).expect("writer");
    writer.write(samples).expect("write");
    writer.finish().expect("finish");
}

fn meeting_duration(meetings_root: &Path, meeting_id: &str) -> f64 {
    let audio = storage::audio_dir(meetings_root, meeting_id);
    AUDIO_CHANNELS
        .iter()
        .map(|channel| storage::channel_duration_seconds(&audio, channel))
        .fold(0.0, f64::max)
}

pub struct MeetingManager {
    app: AppHandle,
    db: Arc<MeetingDb>,
    root: PathBuf,
    slot: Mutex<Slot>,
}

impl MeetingManager {
    pub fn new(app: &AppHandle) -> Result<Self> {
        let root = crate::portable::app_data_dir(app)?.join("meetings");
        std::fs::create_dir_all(&root)?;
        let db = MeetingDb::open(&crate::portable::app_data_dir(app)?.join("meetings.db"))?;
        let cut_off = db.recording_meeting_ids()?;
        let recovered = recover_interrupted(&db, &root)?;
        // Their index entry (made by a note while recording) lacks the last phrases.
        for id in &cut_off {
            if let Err(e) = db.index_local_meeting(id) {
                warn!("Cannot index meeting {id}: {e:#}");
            }
        }
        if recovered > 0 {
            info!("{recovered} meeting(s) were interrupted by the previous exit");
        }
        // Meetings from before the search index (or cut off): index them now.
        match db.index_missing_local() {
            Ok(0) => {}
            Ok(count) => info!("{count} meeting(s) added to the search index"),
            Err(e) => warn!("Cannot build the search index: {e:#}"),
        }
        Ok(Self {
            app: app.clone(),
            db: Arc::new(db),
            root,
            slot: Mutex::new(Slot::Idle),
        })
    }

    /// Brings the meeting's entry in the search index up to date. A failure
    /// only costs the search, so it is logged and not reported.
    fn reindex(&self, id: &str) {
        if let Err(e) = self.db.index_local_meeting(id) {
            warn!("Cannot index meeting {id}: {e:#}");
        }
    }

    /// The meetings database, shared with the sync.
    pub fn db(&self) -> Arc<MeetingDb> {
        Arc::clone(&self.db)
    }

    /// The folder with the meetings' audio.
    pub fn root(&self) -> &Path {
        &self.root
    }

    fn slot(&self) -> MutexGuard<'_, Slot> {
        self.slot.lock().unwrap_or_else(|e| e.into_inner())
    }

    fn emit_state(
        &self,
        kind: MeetingStateKind,
        meeting_id: &str,
        queue_len: usize,
        channel: Option<&str>,
        message: Option<String>,
    ) {
        let _ = MeetingState {
            kind,
            meeting_id: meeting_id.to_string(),
            queue_len: queue_len as u32,
            channel: channel.map(str::to_string),
            message,
        }
        .emit(&self.app);
    }

    /* -------------------------- start / resume -------------------------- */

    /// A new meeting, recording.
    pub fn start_meeting(&self, request: StartMeetingRequest) -> Result<MeetingInfo, String> {
        self.claim_slot()?;
        let result = self.start_inner(&request);
        if result.is_err() {
            *self.slot() = Slot::Idle;
        }
        result
    }

    fn claim_slot(&self) -> Result<(), String> {
        let mut slot = self.slot();
        match *slot {
            Slot::Idle => {
                *slot = Slot::Busy;
                Ok(())
            }
            _ => Err("Встреча уже идёт: сначала остановите её".to_string()),
        }
    }

    fn start_inner(&self, request: &StartMeetingRequest) -> Result<MeetingInfo, String> {
        self.require_model()?;
        let title = match request.title.trim() {
            "" => format!("Встреча {}", Local::now().format("%d.%m.%Y %H:%M")),
            title => title.to_string(),
        };
        let meeting = MeetingInfo {
            id: uuid::Uuid::new_v4().to_string(),
            title,
            capture_mode: request.capture_mode,
            started_at: now_iso(),
            ended_at: None,
            status: MeetingStatus::Recording,
            duration_seconds: 0.0,
            server_meeting_id: None,
            sync_state: "pending".to_string(),
            sync_error: None,
            synced_at: None,
            customer_id: request.customer_id,
            object_id: request.object_id,
            customer_name: clean_name(request.customer_name.as_deref()),
            object_name: clean_name(request.object_name.as_deref()),
            audio_state: "pending".to_string(),
            web_url: None,
        };
        let devices = self.devices_for(Some(request));
        let session = match self.launch(&meeting, 0.0, &devices) {
            Ok(session) => session,
            Err(e) => {
                let _ = std::fs::remove_dir_all(storage::meeting_dir(&self.root, &meeting.id));
                return Err(e);
            }
        };
        if let Err(e) = self.db.insert_meeting(&meeting) {
            self.discard_session(session);
            let _ = std::fs::remove_dir_all(storage::meeting_dir(&self.root, &meeting.id));
            return Err(io_err(e));
        }
        self.activate(session, &meeting);
        Ok(meeting)
    }

    /// Continues a stopped or interrupted meeting: time carries on from what
    /// is already recorded, and new audio goes into the next pieces.
    pub fn resume_meeting(&self, id: &str) -> Result<MeetingInfo, String> {
        self.claim_slot()?;
        let result = self.resume_inner(id);
        if result.is_err() {
            *self.slot() = Slot::Idle;
        }
        result
    }

    fn resume_inner(&self, id: &str) -> Result<MeetingInfo, String> {
        let previous = self
            .db
            .get_meeting(id)
            .map_err(io_err)?
            .ok_or_else(|| "Встреча не найдена".to_string())?;
        if previous.status == MeetingStatus::Recording {
            return Err("Встреча уже записывается".to_string());
        }
        // На сервере она уже финализирована и новых фраз не примет.
        if previous.sync_state == "synced" {
            return Err("Встреча уже отправлена на сервер — начните новую".to_string());
        }
        self.require_model()?;
        let base_seconds = meeting_duration(&self.root, id);
        let devices = self.devices_for(None);
        let session = self.launch(&previous, base_seconds, &devices)?;
        if let Err(e) = self.db.mark_recording(id) {
            self.discard_session(session);
            return Err(io_err(e));
        }
        let meeting = MeetingInfo {
            status: MeetingStatus::Recording,
            ended_at: None,
            ..previous
        };
        self.activate(session, &meeting);
        Ok(meeting)
    }

    fn activate(&self, session: Session, meeting: &MeetingInfo) {
        *self.slot() = Slot::Active(Box::new(session));
        self.emit_state(MeetingStateKind::Started, &meeting.id, 0, None, None);
    }
    /* -------------------------- stop -------------------------- */

    /// Stops capture, lets the recognizer finish the queue (up to a minute),
    /// closes the files and marks the meeting stopped.
    pub fn stop_meeting(&self) -> Result<MeetingInfo, String> {
        let session = {
            let mut slot = self.slot();
            match std::mem::replace(&mut *slot, Slot::Busy) {
                Slot::Active(session) => session,
                other => {
                    *slot = other;
                    return Err("Нет активной встречи".to_string());
                }
            }
        };
        let result = self.finish_session(*session);
        *self.slot() = Slot::Idle;
        if let Ok(meeting) = &result {
            self.reindex(&meeting.id);
        }
        result
    }
}
