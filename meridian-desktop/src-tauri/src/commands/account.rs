//! Meridian account: sign in through the browser (the server answers with a
//! device token), sign out, who is signed in. The token stays on this side.

use std::sync::{Arc, Mutex};

use log::{info, warn};
use tauri::{AppHandle, Manager};
use tauri_plugin_opener::OpenerExt;
use tauri_specta::Event;
use tokio::sync::oneshot;

use crate::managers::meeting::MeetingManager;
use crate::managers::sync::account::{
    normalize_server_url, AccountInfo, AccountStore, AccountUser, StoredAccount,
};
use crate::managers::sync::browser_login::{
    bind_loopback, login_url, wait_for_callback, CallbackResult, Pkce, LOGIN_TIMEOUT,
};
use crate::managers::sync::{AccountChanged, ApiClient, LoginResponse, SyncManager};
use crate::settings::{get_settings, write_settings};

fn accounts(app: &AppHandle) -> Arc<AccountStore> {
    Arc::clone(&app.state::<Arc<AccountStore>>())
}

/// Forgets the site's meetings and projects kept for offline use.
pub fn clear_library_cache(app: &AppHandle) {
    let db = app.state::<Arc<MeetingManager>>().db();
    if let Err(e) = db.clear_server_cache() {
        warn!("Cannot clear the library cache: {e:#}");
    }
}

/// Sender that cancels the sign-in in progress; a new sign-in cancels the old one.
static PENDING_LOGIN: Mutex<Option<oneshot::Sender<()>>> = Mutex::new(None);

fn cancel_pending_login() {
    let sender = PENDING_LOGIN
        .lock()
        .unwrap_or_else(|e| e.into_inner())
        .take();
    if let Some(sender) = sender {
        let _ = sender.send(());
    }
}

/// Stores the account the server just confirmed and tells the rest of the app.
fn complete_login(
    app: &AppHandle,
    server_url: String,
    response: LoginResponse,
) -> Result<AccountInfo, String> {
    let account = StoredAccount {
        server_url: server_url.clone(),
        device_token: response.device_token,
        device_id: response.device_id,
        user: AccountUser {
            id: response.user.id,
            email: response.user.email,
            display_name: response.user.display_name,
        },
    };
    let info = account.info();
    // The cache belongs to the previous account, whoever it was.
    clear_library_cache(app);
    accounts(app).save(account)?;
    info!("Signed in to {server_url} as device {}", info.device_id);

    let mut settings = get_settings(app);
    settings.server_url = server_url;
    write_settings(app, settings);

    let _ = AccountChanged {
        account: Some(info.clone()),
        reason: None,
    }
    .emit(app);
    app.state::<Arc<SyncManager>>().sync_now();
    Ok(info)
}

/// Signs in through the system browser: opens the site's sign-in page, waits
/// for the browser to come back to a loopback port with a one-time code and
/// exchanges the code for a device token.
#[tauri::command]
#[specta::specta]
pub async fn account_browser_login(
    app: AppHandle,
    server_url: String,
) -> Result<AccountInfo, String> {
    let server_url = normalize_server_url(&server_url)?;
    let pkce = Pkce::generate();
    let (listener, port) = bind_loopback().await?;

    let (cancel_tx, cancel_rx) = oneshot::channel();
    {
        let mut pending = PENDING_LOGIN.lock().unwrap_or_else(|e| e.into_inner());
        if let Some(previous) = pending.replace(cancel_tx) {
            let _ = previous.send(());
        }
    }

    let url = login_url(&server_url, port, &pkce);
    app.opener()
        .open_url(url, None::<&str>)
        .map_err(|e| format!("Не удалось открыть браузер: {e}"))?;

    let callback = tokio::select! {
        result = wait_for_callback(&listener, &pkce.state, LOGIN_TIMEOUT) => result?,
        _ = cancel_rx => return Err("Вход отменён".to_string()),
    };
    drop(listener);
    let code = match callback {
        CallbackResult::Code(code) => code,
        CallbackResult::Denied => return Err("Вход отменён".to_string()),
        CallbackResult::Failed => return Err("Вход не выполнен. Попробуйте ещё раз.".to_string()),
    };

    let response = ApiClient::new(&server_url, None)
        .exchange_browser_code(&code, &pkce.verifier)
        .await
        .map_err(|e| e.login_message())?;
    complete_login(&app, server_url, response)
}

/// Aborts the sign-in that waits for the browser (nothing happens if none does).
#[tauri::command]
#[specta::specta]
pub fn account_browser_login_cancel() {
    cancel_pending_login();
}

/// Asks the server to forget the device, then forgets the account here. Without
/// a connection the local sign-out still happens.
#[tauri::command]
#[specta::specta]
pub async fn account_logout(app: AppHandle) -> Result<(), String> {
    let store = accounts(&app);
    if let Some(account) = store.get() {
        let client = ApiClient::new(&account.server_url, Some(&account.device_token));
        if let Err(e) = client.logout().await {
            warn!("The server was not told about the sign-out: {e}");
        }
    }
    store.clear();
    clear_library_cache(&app);
    let _ = AccountChanged {
        account: None,
        reason: None,
    }
    .emit(&app);
    Ok(())
}

#[tauri::command]
#[specta::specta]
pub fn get_account(app: AppHandle) -> Option<AccountInfo> {
    accounts(&app).info()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::managers::sync::ApiError;

    #[test]
    fn login_failures_are_explained_in_russian() {
        let invalid = "Код входа недействителен или истёк. Попробуйте ещё раз.";
        assert_eq!(ApiError::Unauthorized.login_message(), invalid);
        let bad_code = ApiError::Rejected {
            status: 400,
            message: "x".into(),
        };
        assert_eq!(bad_code.login_message(), invalid);
        let disabled = ApiError::Rejected {
            status: 403,
            message: "x".into(),
        };
        assert_eq!(disabled.login_message(), "Пользователь отключён");
        let limited = ApiError::Retry {
            status: Some(429),
            message: "x".into(),
        };
        assert!(limited.login_message().contains("Слишком много попыток"));
        let offline = ApiError::Retry {
            status: None,
            message: "Нет связи с сервером".into(),
        };
        assert_eq!(offline.login_message(), "Нет связи с сервером");
    }

    #[tokio::test]
    async fn a_new_sign_in_cancels_the_pending_one() {
        let (first_tx, first_rx) = oneshot::channel();
        PENDING_LOGIN
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .replace(first_tx);
        cancel_pending_login();
        assert!(first_rx.await.is_ok());
    }
}
