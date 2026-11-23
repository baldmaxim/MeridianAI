//! Meeting mode commands. The work is in `managers::meeting`; anything that
//! touches devices, disk or the model runs off the UI thread.

use std::sync::Arc;

use tauri::{AppHandle, Manager};

use super::library::{client, failure};
use crate::managers::meeting::{
    ActiveMeetingState, AudioFile, CaptureDevices, MeetingDetails, MeetingInfo, MeetingManager,
    MeetingVoice, Note, NoteInput, StartMeetingRequest,
};
use crate::managers::sync::SyncManager;
use crate::settings::{get_settings, write_settings};

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
    // (It may have waited as an interrupted one: that wait is over.)
    app.state::<Arc<SyncManager>>().release_meeting(&meeting.id);
    Ok(meeting)
}

/// "Finish" on an interrupted meeting: no more continuing, send it all.
#[tauri::command]
#[specta::specta]
pub async fn finish_interrupted_meeting(app: AppHandle, id: String) -> Result<MeetingInfo, String> {
    let meeting = blocking(&app, move |m| m.finish_interrupted(&id)).await?;
    app.state::<Arc<SyncManager>>().release_meeting(&meeting.id);
    Ok(meeting)
}

/// Continues a stopped or interrupted meeting. One the server already has
/// (`synced`) is first taken back into work on the server; a refusal (it is
/// still being processed) is the error and the meeting stays as it was. Once the
/// server has taken it back, a failure to start recording puts the meeting back
/// in the sync queue, which finalizes it again with what it already sent.
#[tauri::command]
#[specta::specta]
pub async fn resume_meeting(app: AppHandle, id: String) -> Result<MeetingInfo, String> {
    let meeting = manager(&app)
        .db()
        .get_meeting(&id)
        .map_err(|e| format!("Ошибка базы встреч: {e:#}"))?
        .ok_or_else(|| "Встреча не найдена".to_string())?;
    if meeting.sync_state != "synced" {
        return blocking(&app, move |m| m.resume_meeting(&id)).await;
    }

    let server_id = meeting
        .server_meeting_id
        .ok_or_else(|| "Встреча отправлена на сервер без номера: начните новую".to_string())?;
    // Everything that can be checked here goes before the server is asked.
    let checked = id.clone();
    blocking(&app, move |m| m.check_resumable(&checked, true)).await?;
    let client = client(&app).ok_or_else(|| "Войдите в аккаунт Meridian".to_string())?;
    client
        .reopen_meeting(server_id)
        .await
        .map_err(|e| failure(&app, e))?;

    let resumed = id.clone();
    match blocking(&app, move |m| m.resume_reopened_meeting(&resumed)).await {
        Ok(meeting) => Ok(meeting),
        Err(error) => {
            // The server waits for the end of the meeting: send it again.
            if let Err(e) = manager(&app)
                .db()
                .set_sync_state(&id, "pending", None, None)
            {
                log::warn!("Cannot put meeting {id} back in the sync queue: {e:#}");
            }
            app.state::<Arc<SyncManager>>().release_meeting(&id);
            Err(error)
        }
    }
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

/// Sets the meeting context (`None` or an empty string clears a field) and
/// sends it to the server in the background. Works in any state of the meeting.
#[tauri::command]
#[specta::specta]
pub fn set_meeting_context(
    app: AppHandle,
    meeting_id: String,
    negotiation_type: Option<String>,
    key_terms: Option<String>,
    opponent_weaknesses: Option<String>,
) -> Result<MeetingInfo, String> {
    let meeting = manager(&app).set_meeting_context(
        &meeting_id,
        negotiation_type,
        key_terms,
        opponent_weaknesses,
    )?;
    app.state::<Arc<SyncManager>>().wake();
    Ok(meeting)
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

/// The voices of a meeting, by number.
#[tauri::command]
#[specta::specta]
pub fn meeting_voices_list(
    app: AppHandle,
    meeting_id: String,
) -> Result<Vec<MeetingVoice>, String> {
    manager(&app).list_voices(&meeting_id)
}

/// Sets the side of a voice (`self`, `opponent`, `None` clears it) and sends
/// it to the server in the background.
#[tauri::command]
#[specta::specta]
pub fn meeting_voice_set_side(
    app: AppHandle,
    meeting_id: String,
    label: String,
    side: Option<String>,
) -> Result<(), String> {
    manager(&app).set_voice_side(&meeting_id, &label, side)?;
    app.state::<Arc<SyncManager>>().wake();
    Ok(())
}

/// Remembers the device whose sound online meetings record (`None`: the
/// default one).
#[tauri::command]
#[specta::specta]
pub fn set_meeting_system_device(app: AppHandle, device_id: Option<String>) -> Result<(), String> {
    let mut settings = get_settings(&app);
    settings.meeting_system_device = device_id.filter(|id| !id.is_empty());
    write_settings(&app, settings);
    Ok(())
}
