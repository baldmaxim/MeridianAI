//! Sends one meeting to the server. Every step is idempotent and its result is
//! written to `meetings.db` straight away, so a meeting interrupted anywhere
//! (no network, a crash) continues from where it stopped:
//!
//! 1. create the meeting (`server_meeting_id`),
//! 2. segments in batches of 500 (`segments.synced`),
//! 3. title, end time and the whole list of notes,
//! 4. audio, channel by channel (`audio_state`, `audio_done`),
//! 5. finalize.

use std::path::{Path, PathBuf};
use std::sync::Arc;

use chrono::{DateTime, Duration, SecondsFormat, Utc};
use log::{info, warn};

use super::client::{
    ApiClient, ApiError, AudioUploadBody, MeetingBody, NoteBody, PatchBody, SegmentBody,
};
use crate::managers::meeting::{
    export_channel_wav, recorded_channels, CaptureMode, MeetingDb, MeetingInfo, MeetingStatus,
    Segment,
};

/// The server takes at most this many segments per request.
pub const SEGMENT_BATCH: usize = 500;
/// The server refuses audio files above this size.
const MAX_AUDIO_BYTES: u64 = 500 * 1024 * 1024;
const MAX_TITLE_CHARS: usize = 255;
const MAX_NOTES: usize = 1000;
const MAX_NOTE_CHARS: usize = 5000;

/// How one attempt to sync a meeting ended.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Outcome {
    Synced,
    /// Try again later (the meeting stays in the queue).
    Retry {
        message: String,
        reachable: bool,
    },
    /// The server refused; the meeting waits for the user's retry.
    Failed(String),
    /// The device token is not accepted.
    Unauthorized,
    /// The meeting was deleted or is being recorded again: nothing to do now.
    Postponed,
}

pub struct Engine<'a> {
    pub db: &'a Arc<MeetingDb>,
    pub root: &'a Path,
    pub client: &'a ApiClient,
    pub upload_audio: bool,
}

fn now_iso() -> String {
    Utc::now().to_rfc3339_opts(SecondsFormat::Millis, true)
}

fn db_error(e: impl std::fmt::Display) -> ApiError {
    ApiError::Local(format!("Ошибка базы встреч: {e}"))
}

fn truncated(text: &str, max_chars: usize) -> String {
    text.chars().take(max_chars).collect()
}

fn capture_mode(mode: CaptureMode) -> &'static str {
    match mode {
        CaptureMode::Online => "online",
        CaptureMode::InPerson => "in_person",
    }
}

fn wall_clock(started_at: &str, offset_seconds: f64) -> Option<String> {
    let started = DateTime::parse_from_rfc3339(started_at).ok()?;
    let offset = Duration::milliseconds((offset_seconds * 1000.0).round() as i64);
    Some((started.with_timezone(&Utc) + offset).to_rfc3339_opts(SecondsFormat::Millis, true))
}

fn segment_body(started_at: &str, segment: Segment) -> SegmentBody {
    SegmentBody {
        wall_clock: wall_clock(started_at, segment.start_time),
        client_segment_id: segment.id,
        text: segment.text,
        start_time: segment.start_time.max(0.0),
        end_time: segment.end_time.max(0.0),
        channel: segment.channel,
    }
}

impl Engine<'_> {
    /// Runs the steps and records the result in the database.
    pub async fn sync_meeting(&self, meeting_id: &str) -> Outcome {
        let outcome = match self.run(meeting_id).await {
            Ok(Some(())) => Outcome::Synced,
            Ok(None) => Outcome::Postponed,
            Err(ApiError::Unauthorized) => Outcome::Unauthorized,
            Err(ApiError::Retry { status, message }) => Outcome::Retry {
                message,
                reachable: status.is_some(),
            },
            Err(ApiError::Rejected { message, .. }) | Err(ApiError::Local(message)) => {
                Outcome::Failed(message)
            }
        };
        let recorded = match &outcome {
            Outcome::Synced => self
                .db
                .set_sync_state(meeting_id, "synced", None, Some(&now_iso())),
            Outcome::Retry { message, .. } => {
                self.db
                    .set_sync_state(meeting_id, "pending", Some(message), None)
            }
            Outcome::Failed(message) => {
                self.db
                    .set_sync_state(meeting_id, "error", Some(message), None)
            }
            Outcome::Unauthorized => self.db.set_sync_state(
                meeting_id,
                "pending",
                Some("Войдите в аккаунт заново"),
                None,
            ),
            Outcome::Postponed => Ok(()),
        };
        if let Err(e) = recorded {
            warn!("Cannot record the sync result of {meeting_id}: {e:#}");
        }
        outcome
    }

    /// `Ok(None)`: the meeting is gone or recording again.
    async fn run(&self, meeting_id: &str) -> Result<Option<()>, ApiError> {
        let Some(meeting) = self.db.get_meeting(meeting_id).map_err(db_error)? else {
            return Ok(None);
        };
        if meeting.status == MeetingStatus::Recording {
            return Ok(None);
        }
        // Старт и сразу стоп: протокол из пустоты не нужен, на сервер не шлём.
        if meeting.server_meeting_id.is_none()
            && self
                .db
                .list_segments(meeting_id)
                .map_err(db_error)?
                .is_empty()
            && self.db.list_notes(meeting_id).map_err(db_error)?.is_empty()
        {
            self.db
                .set_sync_state(meeting_id, "empty", None, None)
                .map_err(db_error)?;
            return Ok(None);
        }
        let server_id = self.create_meeting(&meeting).await?;
        self.send_segments(&meeting, server_id).await?;
        self.send_details(&meeting, server_id).await?;
        self.send_audio(&meeting, server_id).await?;

        // Recorded again while we were sending: finalize after the next stop.
        match self.db.get_meeting(meeting_id).map_err(db_error)? {
            Some(now) if now.status != MeetingStatus::Recording => {}
            _ => return Ok(None),
        }
        self.client.finalize(server_id).await?;
        info!("Meeting {meeting_id} is synced (server id {server_id})");
        Ok(Some(()))
    }

    async fn create_meeting(&self, meeting: &MeetingInfo) -> Result<i64, ApiError> {
        if let Some(id) = meeting.server_meeting_id {
            return Ok(id);
        }
        let title = truncated(&meeting.title, MAX_TITLE_CHARS);
        let response = self
            .client
            .upsert_meeting(&MeetingBody {
                client_uuid: &meeting.id,
                title: &title,
                started_at: &meeting.started_at,
                ended_at: meeting.ended_at.as_deref(),
                capture_mode: capture_mode(meeting.capture_mode),
                customer_id: meeting.customer_id,
                object_id: meeting.object_id,
            })
            .await?;
        self.db
            .set_server_meeting_id(&meeting.id, response.meeting_id)
            .map_err(db_error)?;
        Ok(response.meeting_id)
    }

    async fn send_segments(&self, meeting: &MeetingInfo, server_id: i64) -> Result<(), ApiError> {
        loop {
            let batch = self
                .db
                .unsynced_segments(&meeting.id, SEGMENT_BATCH)
                .map_err(db_error)?;
            if batch.is_empty() {
                return Ok(());
            }
            let ids: Vec<String> = batch.iter().map(|s| s.id.clone()).collect();
            let bodies: Vec<SegmentBody> = batch
                .into_iter()
                .map(|s| segment_body(&meeting.started_at, s))
                .collect();
            self.client.put_segments(server_id, &bodies).await?;
            self.db.mark_segments_synced(&ids).map_err(db_error)?;
        }
    }

    /// Title, end time and notes. Notes always go as the whole list, so
    /// edits and deletions reach the server too.
    async fn send_details(&self, meeting: &MeetingInfo, server_id: i64) -> Result<(), ApiError> {
        // The title may have been renamed since the pass began.
        let current = self
            .db
            .get_meeting(&meeting.id)
            .map_err(db_error)?
            .unwrap_or_else(|| meeting.clone());
        let notes = self
            .db
            .list_notes(&meeting.id)
            .map_err(db_error)?
            .into_iter()
            .take(MAX_NOTES)
            .map(|note| NoteBody {
                at_seconds: note.at_seconds.max(0.0),
                text: truncated(&note.text, MAX_NOTE_CHARS),
            })
            .collect();
        let title = truncated(&current.title, MAX_TITLE_CHARS);
        self.client
            .patch_meeting(
                server_id,
                &PatchBody {
                    title: &title,
                    ended_at: current.ended_at.as_deref(),
                    notes,
                },
            )
            .await
    }

    async fn send_audio(&self, meeting: &MeetingInfo, server_id: i64) -> Result<(), ApiError> {
        // Anything but `pending` is a final answer about the audio.
        if !self.upload_audio || meeting.audio_state != "pending" {
            return Ok(());
        }
        let channels = recorded_channels(self.root, &meeting.id);
        if channels.is_empty() {
            return self
                .db
                .set_audio_state(&meeting.id, "none")
                .map_err(db_error);
        }
        let done = self.db.audio_done_channels(&meeting.id).map_err(db_error)?;
        let mut skipped = false;
        for (channel, estimate) in channels {
            if done.iter().any(|c| c == channel) {
                continue;
            }
            if estimate > MAX_AUDIO_BYTES {
                warn!(
                    "Audio '{channel}' of {} is too big to send; skipped",
                    meeting.id
                );
                skipped = true;
                continue;
            }
            match self.send_channel(meeting, server_id, channel).await? {
                ChannelResult::Sent => {}
                ChannelResult::Skipped => skipped = true,
                ChannelResult::NoStorage => {
                    info!(
                        "The server has no file storage; audio of {} is not sent",
                        meeting.id
                    );
                    return self
                        .db
                        .set_audio_state(&meeting.id, "no_storage")
                        .map_err(db_error);
                }
            }
        }
        let state = if skipped { "skipped" } else { "done" };
        self.db
            .set_audio_state(&meeting.id, state)
            .map_err(db_error)
    }

    async fn send_channel(
        &self,
        meeting: &MeetingInfo,
        server_id: i64,
        channel: &'static str,
    ) -> Result<ChannelResult, ApiError> {
        let root = self.root.to_path_buf();
        let id = meeting.id.clone();
        let wav = tokio::task::spawn_blocking(move || export_channel_wav(&root, &id, channel))
            .await
            .map_err(|e| ApiError::Local(format!("Не удалось подготовить звук: {e}")))?
            .map_err(|e| ApiError::Local(format!("Не удалось подготовить звук: {e:#}")))?;
        // The WAV is a throwaway copy of the recorded pieces.
        let _cleanup = RemoveOnDrop(wav.clone());
        let size = std::fs::metadata(&wav)
            .map_err(|e| ApiError::Local(format!("Не удалось прочитать файл звука: {e}")))?
            .len();
        if size > MAX_AUDIO_BYTES {
            return Ok(ChannelResult::Skipped);
        }

        let filename = format!("{channel}.wav");
        let upload = match self
            .client
            .audio_upload(
                server_id,
                &AudioUploadBody {
                    filename: &filename,
                    size,
                    channel,
                },
            )
            .await
        {
            Ok(upload) => upload,
            Err(ApiError::Retry {
                status: Some(503), ..
            }) => return Ok(ChannelResult::NoStorage),
            Err(ApiError::Rejected { status: 400, .. }) => return Ok(ChannelResult::Skipped),
            Err(e) => return Err(e),
        };
        if let Some(url) = &upload.upload_url {
            self.client.put_file(url, &wav, size).await?;
            self.client.audio_confirm(server_id, upload.file_id).await?;
        }
        self.db
            .add_audio_done_channel(&meeting.id, channel)
            .map_err(db_error)?;
        Ok(ChannelResult::Sent)
    }
}

enum ChannelResult {
    Sent,
    Skipped,
    NoStorage,
}

struct RemoveOnDrop(PathBuf);

impl Drop for RemoveOnDrop {
    fn drop(&mut self) {
        let _ = std::fs::remove_file(&self.0);
    }
}
