//! The library of meetings from the site, the meeting view, "ask about a
//! meeting" and the search over all meetings. The work is in `managers::library`.

use std::sync::Arc;

use log::info;
use tauri::{AppHandle, Manager};
use tauri_specta::Event;

use crate::commands::account::clear_library_cache;
use crate::managers::library::types::OfferSubmission;
use crate::managers::library::{
    self, AskAnswer, AskMode, LibrarySnapshot, MeetingViewResult, SearchHit,
};
use crate::managers::meeting::{MeetingDb, MeetingManager};
use crate::managers::sync::{AccountChanged, AccountStore, ApiClient, ApiError};

fn db(app: &AppHandle) -> Arc<MeetingDb> {
    app.state::<Arc<MeetingManager>>().db()
}

/// The client of the signed-in account; `None` when nobody is signed in.
pub(super) fn client(app: &AppHandle) -> Option<ApiClient> {
    let account = app.state::<Arc<AccountStore>>().get()?;
    Some(ApiClient::new(
        &account.server_url,
        Some(&account.device_token),
    ))
}

/// The server does not accept this device any more: sign out, like the sync does.
fn sign_out(app: &AppHandle) -> String {
    info!("The server does not accept this device any more; signing out");
    app.state::<Arc<AccountStore>>().clear();
    clear_library_cache(app);
    let reason = ApiError::Unauthorized.to_string();
    let _ = AccountChanged {
        account: None,
        reason: Some(reason.clone()),
    }
    .emit(app);
    reason
}

pub(super) fn failure(app: &AppHandle, error: ApiError) -> String {
    match error {
        ApiError::Unauthorized => sign_out(app),
        other => other.to_string(),
    }
}

/// `refresh`: ask the server first; without a connection the cache is returned
/// with `offline`. Not signed in: empty lists and `signed_in: false`.
#[tauri::command]
#[specta::specta]
pub async fn library_get(app: AppHandle, refresh: bool) -> Result<LibrarySnapshot, String> {
    let client = client(&app);
    match library::library_get(&db(&app), client.as_ref(), refresh).await {
        Ok(snapshot) => Ok(snapshot),
        Err(ApiError::Unauthorized) => {
            sign_out(&app);
            library::library_get(&db(&app), None, false)
                .await
                .map_err(|e| e.to_string())
        }
        Err(e) => Err(e.to_string()),
    }
}

/// A meeting of the site; from the cache when the server can not be reached.
#[tauri::command]
#[specta::specta]
pub async fn meeting_view_get(
    app: AppHandle,
    server_meeting_id: i64,
) -> Result<MeetingViewResult, String> {
    let client = client(&app);
    library::meeting_view_get(&db(&app), client.as_ref(), server_meeting_id)
        .await
        .map_err(|e| failure(&app, e))
}

#[tauri::command]
#[specta::specta]
pub async fn meeting_ask(
    app: AppHandle,
    server_meeting_id: i64,
    question: String,
    mode: AskMode,
) -> Result<AskAnswer, String> {
    let client = client(&app);
    library::meeting_ask(client.as_ref(), server_meeting_id, &question, mode)
        .await
        .map_err(|e| failure(&app, e))
}

const MSG_NO_ACCOUNT: &str = "Войдите в аккаунт Meridian";

/// The submissions of commercial offers of an object, to choose from in a meeting.
#[tauri::command]
#[specta::specta]
pub async fn object_offer_submissions(
    app: AppHandle,
    object_id: i64,
) -> Result<Vec<OfferSubmission>, String> {
    let client = client(&app).ok_or_else(|| MSG_NO_ACCOUNT.to_string())?;
    client
        .get_offer_submissions(object_id)
        .await
        .map_err(|e| failure(&app, e))
}

/// Which submission of offers the meeting talks about; `None`: all documents of
/// the object. The meeting is the site's (it has to be on the server).
#[tauri::command]
#[specta::specta]
pub async fn meeting_set_offer_submission(
    app: AppHandle,
    server_meeting_id: i64,
    offer_submission: Option<String>,
) -> Result<(), String> {
    let client = client(&app).ok_or_else(|| MSG_NO_ACCOUNT.to_string())?;
    client
        .set_offer_submission(server_meeting_id, offer_submission.as_deref())
        .await
        .map_err(|e| failure(&app, e))
}

/// The link to the recording of a site meeting. `None`: no audio (404, an old
/// server, no account or no connection). The link is a secret: it is neither
/// stored nor logged.
#[tauri::command]
#[specta::specta]
pub async fn meeting_audio_url(app: AppHandle, meeting_id: i64) -> Result<Option<String>, String> {
    let Some(client) = client(&app) else {
        return Ok(None);
    };
    match client.get_meeting_audio_url(meeting_id).await {
        Ok(url) => Ok(url),
        Err(ApiError::Retry { .. }) => Ok(None),
        Err(ApiError::Unauthorized) => Err(failure(&app, ApiError::Unauthorized)),
        Err(_) => Ok(None),
    }
}

/// Full-text search over local and server meetings; fewer than 2 characters
/// find nothing.
#[tauri::command]
#[specta::specta]
pub async fn search_meetings(
    app: AppHandle,
    query: String,
    limit: Option<u32>,
) -> Result<Vec<SearchHit>, String> {
    let db = db(&app);
    tauri::async_runtime::spawn_blocking(move || db.search_meetings(&query, limit))
        .await
        .map_err(|e| format!("Фоновая задача завершилась ошибкой: {e}"))?
        .map_err(|e| format!("Ошибка поиска: {e:#}"))
}
