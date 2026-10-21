//! Meeting mode commands. The work is in `managers::meeting`; anything that
//! touches devices, disk or the model runs off the UI thread.

use std::sync::Arc;

use tauri::{AppHandle, Manager};

use crate::managers::meeting::{
    ActiveMeetingState, AudioFile, CaptureDevices, MeetingDetails, MeetingInfo, MeetingManager,
    Note, NoteInput, StartMeetingRequest,
};
use crate::managers::sync::SyncManager;

fn manager(app: &AppHandle) -> Arc<MeetingManager> {
    Arc::clone(&app.state::<Arc<MeetingManager>>())
}

/// Runs blocking manager work on the blocking pool.
async fn blocking<T, F>(app: &AppHandle, work: F) -> Result<T, String>
where
    T: Send + 'static,
    F: FnOnce(&MeetingManager) -> Result<T, String> + Send + 'static,
{
    let manager = manager(app);
    tauri::async_runtime::spawn_blocking(move || work(&manager))
        .await
        .map_err(|e| format!("Фоновая задача завершилась ошибкой: {e}"))?
}

#[tauri::command]
#[specta::specta]
pub async fn list_capture_devices(app: AppHandle) -> Result<CaptureDevices, String> {
    blocking(&app, |m| Ok(m.list_capture_devices())).await
}

#[tauri::command]
#[specta::specta]
pub async fn start_meeting(
    app: AppHandle,
    request: StartMeetingRequest,
) -> Result<MeetingInfo, String> {
    blocking(&app, move |m| m.start_meeting(request)).await
}

#[tauri::command]
#[specta::specta]
pub async fn stop_meeting(app: AppHandle) -> Result<MeetingInfo, String> {
    let meeting = blocking(&app, |m| m.stop_meeting()).await?;
    // The stopped meeting goes to the server at once, if there is a connection.
    app.state::<Arc<SyncManager>>().wake();
    Ok(meeting)
}

#[tauri::command]
#[specta::specta]
pub async fn resume_meeting(app: AppHandle, id: String) -> Result<MeetingInfo, String> {
    blocking(&app, move |m| m.resume_meeting(&id)).await
}

#[tauri::command]
#[specta::specta]
pub fn get_active_meeting(app: AppHandle) -> Result<Option<ActiveMeetingState>, String> {
    manager(&app).get_active_meeting()
}

#[tauri::command]
#[specta::specta]
pub fn list_meetings(app: AppHandle) -> Result<Vec<MeetingInfo>, String> {
    manager(&app).list_meetings()
}

#[tauri::command]
#[specta::specta]
pub fn get_meeting(app: AppHandle, id: String) -> Result<MeetingDetails, String> {
    manager(&app).get_meeting(&id)
}

#[tauri::command]
#[specta::specta]
pub fn rename_meeting(app: AppHandle, id: String, title: String) -> Result<(), String> {
    manager(&app).rename_meeting(&id, &title)
}

/// Sets (or, with `None`s, clears) the project of a local meeting.
#[tauri::command]
#[specta::specta]
pub fn set_meeting_project(
    app: AppHandle,
    meeting_id: String,
    customer_id: Option<i64>,
    object_id: Option<i64>,
    customer_name: Option<String>,
    object_name: Option<String>,
) -> Result<MeetingInfo, String> {
    manager(&app).set_meeting_project(
        &meeting_id,
        customer_id,
        object_id,
        customer_name,
        object_name,
    )
}

#[tauri::command]
#[specta::specta]
pub async fn delete_meeting(app: AppHandle, id: String) -> Result<(), String> {
    blocking(&app, move |m| m.delete_meeting(&id)).await
}

#[tauri::command]
#[specta::specta]
pub fn upsert_note(app: AppHandle, input: NoteInput) -> Result<Note, String> {
    manager(&app).upsert_note(input)
}

#[tauri::command]
#[specta::specta]
pub fn delete_note(app: AppHandle, id: String) -> Result<(), String> {
    manager(&app).delete_note(&id)
}

#[tauri::command]
#[specta::specta]
pub async fn export_meeting_audio(app: AppHandle, id: String) -> Result<Vec<AudioFile>, String> {
    blocking(&app, move |m| m.export_meeting_audio(&id)).await
}
