//! «Расшифровка файлов»: audio files are queued for the server, which
//! recognizes them; the list shows the queue and the transcripts kept here.

use std::sync::Arc;

use tauri::{AppHandle, Manager};

use crate::managers::meeting::{MeetingManager, TranscriptionDetail, TranscriptionItem};
use crate::managers::sync::{ApiError, SyncManager};

fn manager(app: &AppHandle) -> Arc<MeetingManager> {
    Arc::clone(&app.state::<Arc<MeetingManager>>())
}

fn db_error(e: impl std::fmt::Display) -> String {
    format!("Ошибка базы встреч: {e}")
}

/// Copies the files into the app's data folder and queues them; the upload
/// starts at once when there is a connection. A refused file comes back as an
/// item in `error` and does not stop the others.
#[tauri::command]
#[specta::specta]
pub async fn transcriptions_add(
    app: AppHandle,
    paths: Vec<String>,
) -> Result<Vec<TranscriptionItem>, String> {
    let meetings = manager(&app);
    let worker = Arc::clone(&meetings);
    let items = tauri::async_runtime::spawn_blocking(move || worker.add_transcriptions(paths))
        .await
        .map_err(|e| format!("Фоновая задача завершилась ошибкой: {e}"))??;
    if !items.is_empty() {
        meetings.emit_transcriptions_changed(None);
        app.state::<Arc<SyncManager>>().sync_now();
    }
    Ok(items)
}

/// Newest first, without the transcripts.
#[tauri::command]
#[specta::specta]
pub fn transcriptions_list(app: AppHandle) -> Result<Vec<TranscriptionItem>, String> {
    manager(&app).db().list_transcriptions().map_err(db_error)
}

#[tauri::command]
#[specta::specta]
pub fn transcription_get(app: AppHandle, id: String) -> Result<TranscriptionDetail, String> {
    manager(&app)
        .db()
        .get_transcription_detail(&id)
        .map_err(db_error)?
        .ok_or_else(|| "Файл не найден".to_string())
}

/// The link to the recording of a file (its job on the server). `None`: no
/// audio (404, an old server, the file has no job yet, no account or no
/// connection). The link is a secret: it is neither stored nor logged.
#[tauri::command]
#[specta::specta]
pub async fn transcription_audio_url(app: AppHandle, id: String) -> Result<Option<String>, String> {
    let Some(job_id) = manager(&app)
        .db()
        .transcription_server_job_id(&id)
        .map_err(db_error)?
    else {
        return Ok(None);
    };
    let Some(client) = super::library::client(&app) else {
        return Ok(None);
    };
    match client.get_transcription_audio_url(job_id).await {
        Ok(url) => Ok(url),
        Err(ApiError::Unauthorized) => Err(super::library::failure(&app, ApiError::Unauthorized)),
        Err(_) => Ok(None),
    }
}

/// Takes the file out of the list and deletes its local copy (the server keeps
/// its own). Allowed in any state.
#[tauri::command]
#[specta::specta]
pub fn transcriptions_remove(app: AppHandle, id: String) -> Result<(), String> {
    let meetings = manager(&app);
    meetings.remove_transcription(&id)?;
    meetings.emit_transcriptions_changed(Some(&id));
    Ok(())
}
