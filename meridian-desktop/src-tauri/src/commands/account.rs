//! Meridian account: sign in with a password (the server answers with a
//! device token), sign out, who is signed in. The token stays on this side.

use std::sync::Arc;

use log::{info, warn};
use serde::Deserialize;
use specta::Type;
use tauri::{AppHandle, Manager};
use tauri_specta::Event;

use crate::managers::meeting::MeetingManager;
use crate::managers::sync::account::{
    app_version, device_name, normalize_server_url, platform, AccountInfo, AccountStore,
    AccountUser, StoredAccount,
};
use crate::managers::sync::{AccountChanged, ApiClient, LoginBody, SyncManager};
use crate::settings::{get_settings, write_settings};

#[derive(Clone, Deserialize, Type)]
pub struct AccountLoginRequest {
    pub server_url: String,
    pub email: String,
    pub password: String,
}

impl std::fmt::Debug for AccountLoginRequest {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("AccountLoginRequest")
            .field("server_url", &self.server_url)
            .field("email", &self.email)
            .field("password", &"***")
            .finish()
    }
}

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

#[tauri::command]
#[specta::specta]
pub async fn account_login(
    app: AppHandle,
    request: AccountLoginRequest,
) -> Result<AccountInfo, String> {
    let server_url = normalize_server_url(&request.server_url)?;
    let email = request.email.trim();
    if email.is_empty() || request.password.is_empty() {
        return Err("Введите почту и пароль".to_string());
    }
    let response = ApiClient::new(&server_url, None)
        .login(&LoginBody {
            email,
            password: &request.password,
            device_name: &device_name(),
            platform: platform(),
            app_version: app_version(),
        })
        .await
        .map_err(|e| e.login_message())?;

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
    clear_library_cache(&app);
    accounts(&app).save(account)?;
    info!("Signed in to {server_url} as device {}", info.device_id);

    let mut settings = get_settings(&app);
    settings.server_url = server_url;
    write_settings(&app, settings);

    let _ = AccountChanged {
        account: Some(info.clone()),
        reason: None,
    }
    .emit(&app);
    app.state::<Arc<SyncManager>>().sync_now();
    Ok(info)
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
    fn password_is_masked_in_debug() {
        let request = AccountLoginRequest {
            server_url: "https://meridianai.ru".into(),
            email: "a@b.ru".into(),
            password: "hunter2-secret".into(),
        };
        let text = format!("{request:?}");
        assert!(!text.contains("hunter2-secret"), "{text}");
    }

    #[test]
    fn login_failures_are_explained_in_russian() {
        assert_eq!(
            ApiError::Unauthorized.login_message(),
            "Неверный логин или пароль"
        );
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
}
