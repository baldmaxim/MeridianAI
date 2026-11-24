//! The «Расшифровка файлов» calls of `/api/desktop`: upload a file for
//! transcription, confirm it, ask for the job.

use serde::{Deserialize, Serialize};

use super::{send_json, ApiClient, ApiError};

#[derive(Serialize)]
pub struct TranscriptionUploadBody<'a> {
    pub filename: &'a str,
    pub size: u64,
}

#[derive(Deserialize)]
pub struct TranscriptionUploadResponse {
    pub file_id: i64,
    pub upload_url: String,
}

/// One phrase as the server sends it; every part may be missing.
#[derive(Deserialize)]
pub struct ServerSegment {
    /// A name or a number, whatever the server uses.
    #[serde(default)]
    pub speaker: Option<serde_json::Value>,
    #[serde(default)]
    pub start: Option<f64>,
    #[serde(default)]
    pub end: Option<f64>,
    #[serde(default)]
    pub text: Option<String>,
}

/// The job of a file: the answer of the confirm and of the status request
/// (the latter has the transcript once the job is done).
#[derive(Deserialize)]
pub struct ServerTranscription {
    pub id: i64,
    pub status: String,
    #[serde(default)]
    pub error_message: Option<String>,
    #[serde(default)]
    pub transcription_text: Option<String>,
    #[serde(default)]
    pub segments: Option<Vec<ServerSegment>>,
}

/// A job of the list of the user's files (any device, the site): no transcript.
#[derive(Deserialize)]
pub struct ServerTranscriptionSummary {
    pub id: i64,
    pub status: String,
    #[serde(default)]
    pub original_filename: String,
    #[serde(default)]
    pub original_size: i64,
    #[serde(default)]
    pub error_message: Option<String>,
    /// A naive UTC time of the server (`2026-11-20T10:00:00.123456`).
    pub created_at: String,
}

impl ApiClient {
    pub async fn transcription_upload_session(
        &self,
        body: &TranscriptionUploadBody<'_>,
    ) -> Result<TranscriptionUploadResponse, ApiError> {
        let url = self.url("transcriptions/upload-session");
        send_json(self.authorized(self.http.post(url).json(body))).await
    }

    /// Starts the job; the server takes it twice.
    pub async fn transcription_confirm(
        &self,
        file_id: i64,
    ) -> Result<ServerTranscription, ApiError> {
        let url = self.url(&format!("transcriptions/{file_id}/confirm"));
        send_json(self.authorized(self.http.post(url).json(&serde_json::json!({})))).await
    }

    /// All the user's jobs, newest first.
    pub async fn list_transcriptions(&self) -> Result<Vec<ServerTranscriptionSummary>, ApiError> {
        let url = self.url("transcriptions");
        send_json(self.authorized(self.http.get(url))).await
    }

    pub async fn get_transcription(&self, job_id: i64) -> Result<ServerTranscription, ApiError> {
        let url = self.url(&format!("transcriptions/{job_id}"));
        send_json(self.authorized(self.http.get(url))).await
    }
}
