//! Upload of meeting sources (files dropped onto the window, see
//! `meeting/documents.rs`). Per file: claim the row, ask the server for an
//! upload session, PUT the bytes to the storage, confirm. The server's document
//! id is written down right after the session, so a crash between the PUT and
//! the confirm continues with the confirm.

use log::{info, warn};

use super::client::{ApiError, DocumentUploadBody};
use super::engine::{db_error, Engine};
use crate::managers::meeting::{DocumentRow, DOC_ERROR, DOC_PENDING};

/// What to do with a queue row after a failed step.
#[derive(Debug, Clone, PartialEq, Eq)]
pub(super) enum DocFailure {
    /// Back to the queue, try again on the next pass.
    Retry(String),
    /// The server no longer knows the document it gave us: forget its id and
    /// upload from the start.
    Restart(String),
    /// The server refused or the file is unusable: the row stays in `error`.
    Permanent(String),
    /// The device token is not accepted.
    SignedOut,
}

/// How the row is written down after a failure.
#[derive(Debug, Clone, PartialEq, Eq)]
pub(super) struct DocTransition {
    pub state: &'static str,
    pub error: Option<String>,
    pub bump_attempts: bool,
    pub forget_document: bool,
}

/// `resumed_confirm`: the step that failed was the confirm of a document whose
/// upload session was made by an earlier attempt.
pub(super) fn classify(error: &ApiError, resumed_confirm: bool) -> DocFailure {
    match error {
        ApiError::Unauthorized => DocFailure::SignedOut,
        ApiError::Retry { message, .. } => DocFailure::Retry(message.clone()),
        // Request timeout: worth another try, unlike the other 4xx.
        ApiError::Rejected {
            status: 408,
            message,
        } => DocFailure::Retry(message.clone()),
        ApiError::Rejected { message, .. } if resumed_confirm => {
            DocFailure::Restart(message.clone())
        }
        ApiError::Rejected { message, .. } | ApiError::Local(message) => {
            DocFailure::Permanent(message.clone())
        }
    }
}

pub(super) fn transition(failure: &DocFailure) -> DocTransition {
    match failure {
        DocFailure::Retry(message) => DocTransition {
            state: DOC_PENDING,
            error: Some(message.clone()),
            bump_attempts: true,
            forget_document: false,
        },
        DocFailure::Restart(message) => DocTransition {
            state: DOC_PENDING,
            error: Some(message.clone()),
            bump_attempts: true,
            forget_document: true,
        },
        DocFailure::Permanent(message) => DocTransition {
            state: DOC_ERROR,
            error: Some(message.clone()),
            bump_attempts: true,
            forget_document: false,
        },
        DocFailure::SignedOut => DocTransition {
            state: DOC_PENDING,
            error: Some("Войдите в аккаунт заново".to_string()),
            bump_attempts: false,
            forget_document: false,
        },
    }
}

/// How a pass over the queue ended.
#[derive(Debug, Default, PartialEq, Eq)]
pub(super) struct DocumentsReport {
    pub uploaded: u32,
    /// The server could not be reached (or the storage is not set up): the
    /// rest of the queue was left for the next pass.
    pub stopped_by: Option<ApiError>,
}

impl Engine<'_> {
    /// Uploads the pending files whose meeting is on the server (`meeting_id`:
    /// only those of this local meeting). Failures are written to the rows;
    /// only a refused token comes back as an error.
    pub(super) async fn send_documents(
        &self,
        meeting_id: Option<&str>,
    ) -> Result<DocumentsReport, ApiError> {
        self.db
            .link_documents_to_server_meetings()
            .map_err(db_error)?;
        let rows = self.db.documents_to_send(meeting_id).map_err(db_error)?;
        let mut report = DocumentsReport::default();
        for row in rows {
            if !self.db.claim_document(row.id).map_err(db_error)? {
                continue;
            }
            match self.upload_document(&row).await {
                Ok(()) => report.uploaded += 1,
                Err((error, resumed_confirm)) => {
                    let failure = classify(&error, resumed_confirm);
                    self.record_failure(&row, &failure);
                    match failure {
                        DocFailure::SignedOut => return Err(ApiError::Unauthorized),
                        // No connection or the storage is off: the next files
                        // would fail the same way.
                        DocFailure::Retry(_) => {
                            report.stopped_by = Some(error);
                            break;
                        }
                        DocFailure::Restart(_) | DocFailure::Permanent(_) => {}
                    }
                }
            }
        }
        Ok(report)
    }

    /// The error comes with whether it was a confirm of an earlier session.
    async fn upload_document(&self, row: &DocumentRow) -> Result<(), (ApiError, bool)> {
        let Some(server_meeting_id) = row.server_meeting_id else {
            return Err((
                ApiError::Local("Встреча ещё не на сервере".to_string()),
                false,
            ));
        };
        let path = std::path::Path::new(&row.file_path);
        if !path.is_file() {
            return Err((ApiError::Local("Файл не найден".to_string()), false));
        }
        let (document_id, resumed) = match row.server_document_id {
            Some(id) => (id, true),
            None => {
                let session = self
                    .client
                    .document_upload_session(&DocumentUploadBody {
                        filename: &row.original_name,
                        size: row.size.max(0) as u64,
                        mime_type: &row.mime,
                        meeting_id: server_meeting_id,
                    })
                    .await
                    .map_err(|e| (e, false))?;
                self.db
                    .set_document_server_id(row.id, Some(session.document_id))
                    .map_err(|e| (db_error(e), false))?;
                if let Some(url) = &session.upload_url {
                    if let Err(e) = self
                        .client
                        .put_file(url, path, row.size.max(0) as u64, &row.mime)
                        .await
                    {
                        // The next attempt starts with a fresh session: the
                        // confirm alone would find nothing in the storage.
                        let _ = self.db.set_document_server_id(row.id, None);
                        return Err((e, false));
                    }
                }
                (session.document_id, false)
            }
        };
        self.client
            .document_confirm(document_id, server_meeting_id)
            .await
            .map_err(|e| (e, resumed))?;
        self.db
            .mark_document_uploaded(row.id, document_id)
            .map_err(|e| (db_error(e), false))?;
        // The server has the file; the local copy is not needed any more.
        if let Err(e) = std::fs::remove_file(path) {
            warn!("Cannot delete the copy of an uploaded source: {e}");
        }
        info!(
            "Source '{}' of meeting {server_meeting_id} is uploaded",
            row.original_name
        );
        Ok(())
    }

    fn record_failure(&self, row: &DocumentRow, failure: &DocFailure) {
        let change = transition(failure);
        warn!(
            "Upload of source '{}' ({}): {:?}",
            row.original_name, change.state, failure
        );
        let result = (|| {
            if change.forget_document {
                self.db.set_document_server_id(row.id, None)?;
            }
            self.db.set_document_state(
                row.id,
                change.state,
                change.error.as_deref(),
                change.bump_attempts,
            )
        })();
        if let Err(e) = result {
            warn!("Cannot record the upload state of a source: {e:#}");
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn retry(status: Option<u16>) -> ApiError {
        ApiError::Retry {
            status,
            message: "сеть".to_string(),
        }
    }

    fn rejected(status: u16) -> ApiError {
        ApiError::Rejected {
            status,
            message: "отказ".to_string(),
        }
    }

    #[test]
    fn network_and_server_errors_are_retried() {
        for error in [
            retry(None),
            retry(Some(503)),
            retry(Some(500)),
            retry(Some(429)),
        ] {
            let change = transition(&classify(&error, false));
            assert_eq!(change.state, DOC_PENDING, "{error:?}");
            assert!(change.bump_attempts);
            assert!(!change.forget_document);
            assert_eq!(change.error.as_deref(), Some("сеть"));
        }
    }

    #[test]
    fn request_timeout_is_retried_other_4xx_are_final() {
        assert_eq!(
            transition(&classify(&rejected(408), false)).state,
            DOC_PENDING
        );
        for status in [400, 403, 404, 409, 413, 422] {
            let change = transition(&classify(&rejected(status), false));
            assert_eq!(change.state, DOC_ERROR, "{status}");
            assert!(change.bump_attempts);
        }
    }

    #[test]
    fn local_problems_are_final() {
        let change = transition(&classify(&ApiError::Local("Файл не найден".into()), false));
        assert_eq!(change.state, DOC_ERROR);
        assert_eq!(change.error.as_deref(), Some("Файл не найден"));
    }

    #[test]
    fn a_refused_confirm_of_an_old_session_starts_over() {
        let change = transition(&classify(&rejected(400), true));
        assert_eq!(change.state, DOC_PENDING);
        assert!(change.forget_document);
        // A fresh session that is refused is final.
        assert_eq!(
            transition(&classify(&rejected(400), false)).state,
            DOC_ERROR
        );
        // ...and a timeout stays a plain retry that keeps the id.
        assert!(!transition(&classify(&rejected(408), true)).forget_document);
    }

    #[test]
    fn a_refused_token_signs_out_without_counting_an_attempt() {
        let failure = classify(&ApiError::Unauthorized, false);
        assert_eq!(failure, DocFailure::SignedOut);
        let change = transition(&failure);
        assert_eq!(change.state, DOC_PENDING);
        assert!(!change.bump_attempts);
    }
}
