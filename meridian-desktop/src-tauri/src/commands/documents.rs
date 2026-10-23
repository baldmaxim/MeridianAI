//! Sources of a meeting: files dropped onto the window are queued for the
//! server, and the list shows the queue next to what the server has.

use std::sync::Arc;

use log::warn;
use serde::Serialize;
use specta::Type;
use tauri::{AppHandle, Manager};

use super::library::{client, failure};
use crate::managers::meeting::{AddDocumentsResult, MeetingManager, QueuedDocument};
use crate::managers::sync::{ApiError, ServerDocument, SyncManager};

const MSG_NO_ACCOUNT: &str = "Войдите в аккаунт Meridian";

/// Files of a meeting: the queue, and the server's list when it could be had.
#[derive(Clone, Debug, Serialize, Type)]
pub struct MeetingDocuments {
    /// Not on the server yet: waiting, being uploaded, or refused.
    pub queued: Vec<QueuedDocument>,
    /// `None`: not asked or no answer (see `offline`).
    pub server: Option<Vec<ServerDocument>>,
    /// The server could not be reached.
    pub offline: bool,
}

fn manager(app: &AppHandle) -> Arc<MeetingManager> {
    Arc::clone(&app.state::<Arc<MeetingManager>>())
}

/// Copies the files into the app's data folder and queues them; the upload
/// starts at once when there is a connection. A refused file is reported in
/// the result and does not stop the others.
#[tauri::command]
#[specta::specta]
pub async fn meeting_documents_add(
    app: AppHandle,
    meeting_id: Option<String>,
    server_meeting_id: Option<i64>,
    paths: Vec<String>,
) -> Result<AddDocumentsResult, String> {
    let meetings = manager(&app);
    let result = tauri::async_runtime::spawn_blocking(move || {
        meetings.add_documents(meeting_id.as_deref(), server_meeting_id, paths)
    })
    .await
    .map_err(|e| format!("Фоновая задача завершилась ошибкой: {e}"))??;
    if result.added > 0 {
        app.state::<Arc<SyncManager>>().wake();
    }
    Ok(result)
}

#[tauri::command]
#[specta::specta]
pub async fn meeting_documents_list(
    app: AppHandle,
    meeting_id: Option<String>,
    server_meeting_id: Option<i64>,
) -> Result<MeetingDocuments, String> {
    let meetings = manager(&app);
    let db = meetings.db();
    let server_meeting_id = match meeting_id.as_deref() {
        Some(id) => db
            .get_meeting(id)
            .map_err(|e| format!("Ошибка базы встреч: {e:#}"))?
            .ok_or_else(|| "Встреча не найдена".to_string())?
            .server_meeting_id
            .or(server_meeting_id),
        None => server_meeting_id,
    };
    let queued = db
        .list_queued_documents(meeting_id.as_deref(), server_meeting_id)
        .map_err(|e| format!("Ошибка базы встреч: {e:#}"))?;

    let (Some(server_id), Some(client)) = (server_meeting_id, client(&app)) else {
        return Ok(MeetingDocuments {
            queued,
            server: None,
            offline: false,
        });
    };
    let (server, offline) = match client.get_meeting_documents(server_id).await {
        Ok(items) => (Some(items), false),
        Err(ApiError::Unauthorized) => {
            failure(&app, ApiError::Unauthorized);
            (None, false)
        }
        Err(ApiError::Retry { .. }) => (None, true),
        Err(e) => {
            warn!("The documents of meeting {server_id} were not loaded: {e}");
            (None, false)
        }
    };
    Ok(MeetingDocuments {
        queued,
        server,
        offline,
    })
}

/// Includes a document into the meeting's context or leaves it out.
#[tauri::command]
#[specta::specta]
pub async fn meeting_document_set_included(
    app: AppHandle,
    server_meeting_id: i64,
    document_id: i64,
    included: bool,
) -> Result<(), String> {
    let client = client(&app).ok_or_else(|| MSG_NO_ACCOUNT.to_string())?;
    client
        .set_document_included(server_meeting_id, document_id, included)
        .await
        .map_err(|e| failure(&app, e))
}

/// Takes a file out of the upload queue and deletes its local copy.
#[tauri::command]
#[specta::specta]
pub fn meeting_document_remove_queued(app: AppHandle, queue_id: i64) -> Result<(), String> {
    if manager(&app).remove_queued_document(queue_id)? {
        Ok(())
    } else {
        Err("Файл загружается: подождите окончания".to_string())
    }
}
