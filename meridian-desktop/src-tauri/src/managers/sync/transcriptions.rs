//! «Расшифровка файлов»: the queue of audio files (see `meeting/transcriptions.rs`).
//! Per file: claim the row, ask for an upload session, PUT the bytes to the
//! storage, confirm. The server's file id is written down right after the
//! session and the `uploaded` flag after the PUT, so a crash between the PUT and
//! the confirm continues with the confirm. Then the job is asked for every pass
//! until it is done or failed.

use log::{info, warn};

use super::client::{ApiError, ServerTranscription, TranscriptionUploadBody};
use super::documents::{classify, DocFailure};
use super::engine::{db_error, Engine};
use crate::managers::meeting::{
    audio_mime, delete_local_copy, StoredTranscript, TranscriptSegment, TranscriptionRow, TR_ERROR,
    TR_PROCESSING, TR_QUEUED,
};

const MSG_JOB_FAILED: &str = "Не удалось распознать файл";
const MSG_JOB_LOST: &str = "Сервер не нашёл задачу распознавания";

/// How a pass over the transcriptions ended.
#[derive(Debug, Default, PartialEq, Eq)]
pub(super) struct TranscriptionsReport {
    /// The server could not be reached (or the storage is not set up): the
    /// rest was left for the next pass.
    pub stopped_by: Option<ApiError>,
    /// The server answered at least once.
    pub reached: bool,
    /// The server answered the list of its files (an old server's refusal
    /// counts): it is not asked again until it is due.
    pub pulled: bool,
}

/// What a queue row becomes after a failed upload step.
#[derive(Debug, Clone, PartialEq, Eq)]
pub(super) struct TranscriptionTransition {
    pub status: &'static str,
    pub error: Option<String>,
    pub bump_attempts: bool,
    pub forget_file: bool,
}

pub(super) fn transition(failure: &DocFailure) -> TranscriptionTransition {
    let (status, error, bump_attempts, forget_file) = match failure {
        DocFailure::Retry(message) => (TR_QUEUED, Some(message.clone()), true, false),
        DocFailure::Restart(message) => (TR_QUEUED, Some(message.clone()), true, true),
        DocFailure::Permanent(message) => (TR_ERROR, Some(message.clone()), true, false),
        DocFailure::SignedOut => (
            TR_QUEUED,
            Some("Войдите в аккаунт заново".to_string()),
            false,
            false,
        ),
    };
    TranscriptionTransition {
        status,
        error,
        bump_attempts,
        forget_file,
    }
}

/// The transcript as stored: the text falls back to the phrases joined.
fn stored_transcript(job: &ServerTranscription) -> StoredTranscript {
    let segments: Vec<TranscriptSegment> = job
        .segments
        .iter()
        .flatten()
        .map(|s| TranscriptSegment {
            speaker: match &s.speaker {
                Some(serde_json::Value::String(name)) => name.clone(),
                Some(serde_json::Value::Number(n)) => n.to_string(),
                _ => String::new(),
            },
            start: s.start.unwrap_or(0.0).max(0.0),
            end: s.end.unwrap_or(0.0).max(0.0),
            text: s.text.clone().unwrap_or_default(),
        })
        .collect();
    let text = match &job.transcription_text {
        Some(text) => text.clone(),
        None => segments
            .iter()
            .map(|s| s.text.as_str())
            .collect::<Vec<_>>()
            .join(" "),
    };
    StoredTranscript { text, segments }
}

impl Engine<'_> {
    /// Uploads the queued files, reads the list of the server's files when `pull`
    /// is set and asks for the jobs in progress. `changed`
    /// is called after each write to the queue. Failures are written to the
    /// rows; only a refused token comes back as an error.
    pub(super) async fn send_transcriptions(
        &self,
        changed: &(dyn Fn() + Sync),
        pull: bool,
    ) -> Result<TranscriptionsReport, ApiError> {
        let mut report = TranscriptionsReport::default();
        for row in self.db.transcriptions_to_send().map_err(db_error)? {
            if !self.db.claim_transcription(&row.id).map_err(db_error)? {
                continue;
            }
            changed();
            let outcome = self.upload_transcription(&row).await;
            match outcome {
                Ok(()) => report.reached = true,
                Err((error, resumed_confirm)) => {
                    let failure = classify(&error, resumed_confirm);
                    self.record_transcription_failure(&row, &failure);
                    changed();
                    match failure {
                        DocFailure::SignedOut => return Err(ApiError::Unauthorized),
                        DocFailure::Retry(_) => {
                            report.stopped_by = Some(error);
                            break;
                        }
                        DocFailure::Restart(_) | DocFailure::Permanent(_) => {
                            report.reached = true;
                        }
                    }
                }
            }
            changed();
        }
        // The jobs are asked for even when the storage is off; a lost
        // connection would fail them the same way.
        let offline = matches!(
            report.stopped_by,
            Some(ApiError::Retry { status: None, .. })
        );
        if !offline {
            if pull {
                match self.pull_server_transcriptions(changed).await {
                    Ok(()) => {
                        report.reached = true;
                        report.pulled = true;
                    }
                    Err(ApiError::Unauthorized) => return Err(ApiError::Unauthorized),
                    Err(error @ ApiError::Retry { .. }) => {
                        if report.stopped_by.is_none() {
                            report.stopped_by = Some(error);
                        }
                    }
                    // An old server without the list, or a refusal: not worth a stop.
                    Err(error) => {
                        report.pulled = true;
                        warn!("Cannot read the list of the server's files: {error}");
                    }
                }
            }
            if report.stopped_by.is_none() {
                match self.backfill_protocols(changed).await {
                    Ok(()) => {}
                    Err(ApiError::Unauthorized) => return Err(ApiError::Unauthorized),
                    Err(error) => report.stopped_by = Some(error),
                }
            }
            for row in self.db.transcriptions_processing().map_err(db_error)? {
                match self.poll_transcription(&row).await {
                    Ok(()) => {
                        report.reached = true;
                        changed();
                    }
                    Err(ApiError::Unauthorized) => return Err(ApiError::Unauthorized),
                    Err(error @ ApiError::Retry { .. }) => {
                        if report.stopped_by.is_none() {
                            report.stopped_by = Some(error);
                        }
                        break;
                    }
                    Err(error) => {
                        report.reached = true;
                        warn!("Job of '{}' failed: {error}", row.filename);
                        let _ = self.db.set_transcription_state(
                            &row.id,
                            TR_ERROR,
                            Some(&error.to_string()),
                            true,
                        );
                        changed();
                    }
                }
            }
        }
        Ok(report)
    }

    /// Adds a row for every job of the user that this PC has no row for (the
    /// site, another PC). A finished or running job waits as `processing`, so
    /// the poll that follows brings its transcript; a failed one is an error row.
    async fn pull_server_transcriptions(
        &self,
        changed: &(dyn Fn() + Sync),
    ) -> Result<(), ApiError> {
        let jobs = self.client.list_transcriptions().await?;
        let known = self.db.known_server_job_ids().map_err(db_error)?;
        let mut added = false;
        // Oldest first: equal times keep the server's order in the list.
        for job in jobs.iter().rev().filter(|job| !known.contains(&job.id)) {
            let (status, error) = if job.status == "error" {
                let message = job
                    .error_message
                    .as_deref()
                    .filter(|m| !m.trim().is_empty())
                    .unwrap_or(MSG_JOB_FAILED);
                (TR_ERROR, Some(message))
            } else {
                (TR_PROCESSING, None)
            };
            let name = if job.original_filename.trim().is_empty() {
                "—"
            } else {
                job.original_filename.as_str()
            };
            added |= self
                .db
                .insert_server_transcription(
                    job.id,
                    name,
                    job.original_size,
                    status,
                    &job.status,
                    error,
                    &job.created_at,
                )
                .map_err(db_error)?;
        }
        if added {
            changed();
        }
        Ok(())
    }

    /// Finished files of an older version have no protocol yet: asked for once.
    /// An answer (even an empty one or a refusal) settles the row; a lost
    /// connection leaves it for the next pass.
    async fn backfill_protocols(&self, changed: &(dyn Fn() + Sync)) -> Result<(), ApiError> {
        for (id, job_id) in self
            .db
            .transcriptions_without_protocol()
            .map_err(db_error)?
        {
            let protocol = match self.client.get_transcription(job_id).await {
                Ok(job) => job.protocol_markdown.unwrap_or_default(),
                Err(error @ (ApiError::Unauthorized | ApiError::Retry { .. })) => {
                    return Err(error)
                }
                Err(error) => {
                    warn!("No protocol of the job {job_id}: {error}");
                    String::new()
                }
            };
            self.db
                .set_transcription_protocol(&id, &protocol)
                .map_err(db_error)?;
            changed();
        }
        Ok(())
    }

    /// The error comes with whether it was a confirm of an earlier upload.
    async fn upload_transcription(&self, row: &TranscriptionRow) -> Result<(), (ApiError, bool)> {
        let path = std::path::Path::new(&row.local_path);
        if !row.uploaded || row.server_file_id.is_none() {
            if !path.is_file() {
                return Err((ApiError::Local("Файл не найден".to_string()), false));
            }
            let size = row.size.max(0) as u64;
            let session = self
                .client
                .transcription_upload_session(&TranscriptionUploadBody {
                    filename: &row.filename,
                    size,
                })
                .await
                .map_err(|e| (e, false))?;
            self.db
                .set_transcription_file(&row.id, Some(session.file_id), false)
                .map_err(|e| (db_error(e), false))?;
            let mime = audio_mime(&row.filename).unwrap_or("application/octet-stream");
            if let Err(e) = self
                .client
                .put_file(&session.upload_url, path, size, mime)
                .await
            {
                // The next attempt starts with a fresh session.
                let _ = self.db.set_transcription_file(&row.id, None, false);
                return Err((e, false));
            }
            self.db
                .set_transcription_file(&row.id, Some(session.file_id), true)
                .map_err(|e| (db_error(e), false))?;
            return self
                .confirm_transcription(row, session.file_id, false)
                .await;
        }
        let file_id = row.server_file_id.unwrap_or_default();
        self.confirm_transcription(row, file_id, true).await
    }

    async fn confirm_transcription(
        &self,
        row: &TranscriptionRow,
        file_id: i64,
        resumed: bool,
    ) -> Result<(), (ApiError, bool)> {
        let job = self
            .client
            .transcription_confirm(file_id)
            .await
            .map_err(|e| (e, resumed))?;
        self.db
            .mark_transcription_confirmed(&row.id, job.id, &job.status)
            .map_err(|e| (db_error(e), false))?;
        // The server has the file; the local copy is not needed any more.
        delete_local_copy(&row.local_path);
        info!("File '{}' is sent for transcription", row.filename);
        self.apply_job(&row.id, &job).map_err(|e| (e, false))
    }

    async fn poll_transcription(&self, row: &TranscriptionRow) -> Result<(), ApiError> {
        let Some(job_id) = row.server_job_id else {
            return Err(ApiError::Local(MSG_JOB_LOST.to_string()));
        };
        let job = self.client.get_transcription(job_id).await?;
        self.apply_job(&row.id, &job)
    }

    /// Writes down what the server says about the job.
    fn apply_job(&self, id: &str, job: &ServerTranscription) -> Result<(), ApiError> {
        match job.status.as_str() {
            "done" => self
                .db
                .finish_transcription(id, &job.status, &stored_transcript(job))
                .and_then(|()| {
                    self.db.set_transcription_protocol(
                        id,
                        job.protocol_markdown.as_deref().unwrap_or_default(),
                    )
                }),
            "error" => {
                let message = job
                    .error_message
                    .as_deref()
                    .filter(|m| !m.trim().is_empty())
                    .unwrap_or(MSG_JOB_FAILED);
                self.db
                    .set_transcription_state(id, TR_ERROR, Some(message), false)
                    .and_then(|()| self.db.set_transcription_server_status(id, &job.status))
            }
            other => self.db.set_transcription_server_status(id, other),
        }
        .map_err(db_error)
    }

    fn record_transcription_failure(&self, row: &TranscriptionRow, failure: &DocFailure) {
        let change = transition(failure);
        warn!(
            "Upload of '{}' ({}): {:?}",
            row.filename, change.status, failure
        );
        let result = (|| {
            if change.forget_file {
                self.db.set_transcription_file(&row.id, None, false)?;
            }
            self.db.set_transcription_state(
                &row.id,
                change.status,
                change.error.as_deref(),
                change.bump_attempts,
            )
        })();
        if let Err(e) = result {
            warn!("Cannot record the upload state of a transcription: {e:#}");
        }
    }
}
