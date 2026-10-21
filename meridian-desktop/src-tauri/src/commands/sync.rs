//! Sync of meetings with the server: start it now, retry a failed meeting,
//! and the current status.

use std::sync::Arc;

use tauri::{AppHandle, Manager};

use crate::managers::sync::{SyncManager, SyncStatus};

fn manager(app: &AppHandle) -> Arc<SyncManager> {
    Arc::clone(&app.state::<Arc<SyncManager>>())
}

#[tauri::command]
#[specta::specta]
pub fn sync_now(app: AppHandle) {
    manager(&app).sync_now();
}

/// Puts a meeting the server refused back in the queue.
#[tauri::command]
#[specta::specta]
pub fn retry_meeting_sync(app: AppHandle, id: String) -> Result<(), String> {
    manager(&app).retry_meeting(&id)
}

#[tauri::command]
#[specta::specta]
pub fn get_sync_status(app: AppHandle) -> SyncStatus {
    manager(&app).core().status()
}
