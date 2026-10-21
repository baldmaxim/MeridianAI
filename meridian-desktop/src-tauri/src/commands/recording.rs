use tauri::AppHandle;

/// Start recording from the microphone.
#[tauri::command]
#[specta::specta]
pub fn start_recording(app: AppHandle) -> Result<(), String> {
    crate::recording::start(&app)
}

/// Stop the active recording and return the recognized text.
#[tauri::command]
#[specta::specta]
pub async fn stop_recording(app: AppHandle) -> Result<String, String> {
    crate::recording::stop(&app).await
}
