//! The signed-in Meridian account: server address, device token and the user.
//! Kept in `account.json` in the app data folder (0600 on unix). The token
//! never leaves this module in a readable form: `Debug` masks it, and the
//! frontend only gets `AccountInfo`.

use std::fmt;
use std::path::{Path, PathBuf};
use std::sync::{Mutex, MutexGuard};

use log::warn;
use serde::{Deserialize, Serialize};
use specta::Type;

pub const DEFAULT_SERVER_URL: &str = "https://meridianai.ru";
const ACCOUNT_FILE: &str = "account.json";

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize, Type)]
pub struct AccountUser {
    pub id: i64,
    pub email: String,
    pub display_name: Option<String>,
}

/// What the frontend may see of the account.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Type)]
pub struct AccountInfo {
    pub server_url: String,
    pub user: AccountUser,
    pub device_id: i64,
    pub logged_in: bool,
}

#[derive(Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct StoredAccount {
    pub server_url: String,
    pub device_token: String,
    pub device_id: i64,
    pub user: AccountUser,
}

impl fmt::Debug for StoredAccount {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("StoredAccount")
            .field("server_url", &self.server_url)
            .field("device_token", &"***")
            .field("device_id", &self.device_id)
            .field("user", &self.user)
            .finish()
    }
}

impl StoredAccount {
    pub fn info(&self) -> AccountInfo {
        AccountInfo {
            server_url: self.server_url.clone(),
            user: self.user.clone(),
            device_id: self.device_id,
            logged_in: true,
        }
    }
}

/// `https://host` as typed by the user, made canonical: no trailing slash,
/// no query or credentials. Plain `http` is only for a local server.
pub fn normalize_server_url(raw: &str) -> Result<String, String> {
    let raw = raw.trim();
    if raw.is_empty() {
        return Err("Укажите адрес сервера".to_string());
    }
    let mut url = reqwest::Url::parse(raw)
        .map_err(|_| "Адрес сервера указан неверно: ожидается https://...".to_string())?;
    let host = url.host_str().unwrap_or_default().to_string();
    let local = host == "localhost" || host == "127.0.0.1";
    match url.scheme() {
        "https" => {}
        "http" if local => {}
        _ => return Err("Адрес сервера должен начинаться с https://".to_string()),
    }
    if host.is_empty() || !url.username().is_empty() || url.password().is_some() {
        return Err("Адрес сервера указан неверно: ожидается https://host".to_string());
    }
    url.set_query(None);
    url.set_fragment(None);
    Ok(url.as_str().trim_end_matches('/').to_string())
}

/// `{server}{path}` with exactly one slash between them.
pub fn join_url(base: &str, path: &str) -> String {
    format!(
        "{}/{}",
        base.trim_end_matches('/'),
        path.trim_start_matches('/')
    )
}

/// The meeting's page on the site.
pub fn meeting_web_url(server_url: &str, server_meeting_id: i64) -> String {
    join_url(server_url, &format!("meetings/{server_meeting_id}"))
}

/// Name of this computer for the server's list of devices.
pub fn device_name() -> String {
    #[cfg(unix)]
    {
        let mut buf = [0u8; 256];
        // SAFETY: the buffer is valid for its length; gethostname NUL-terminates it on success.
        let ok = unsafe { libc::gethostname(buf.as_mut_ptr().cast(), buf.len() - 1) } == 0;
        if ok {
            let end = buf.iter().position(|b| *b == 0).unwrap_or(buf.len());
            let name = String::from_utf8_lossy(&buf[..end]).trim().to_string();
            if !name.is_empty() {
                return name;
            }
        }
    }
    for var in ["COMPUTERNAME", "HOSTNAME"] {
        if let Ok(name) = std::env::var(var) {
            if !name.trim().is_empty() {
                return name.trim().to_string();
            }
        }
    }
    "Компьютер".to_string()
}

pub fn platform() -> &'static str {
    if cfg!(windows) {
        "windows"
    } else if cfg!(target_os = "macos") {
        "macos"
    } else {
        "linux"
    }
}

pub fn app_version() -> &'static str {
    env!("CARGO_PKG_VERSION")
}

pub struct AccountStore {
    path: PathBuf,
    cache: Mutex<Option<StoredAccount>>,
}

impl AccountStore {
    /// Reads `account.json` from `dir`; a missing or damaged file means no account.
    pub fn open(dir: &Path) -> Self {
        let path = dir.join(ACCOUNT_FILE);
        let account = match std::fs::read(&path) {
            Ok(bytes) => serde_json::from_slice::<StoredAccount>(&bytes)
                .map_err(|_| warn!("{} is damaged; signing out", path.display()))
                .ok(),
            Err(_) => None,
        };
        Self {
            path,
            cache: Mutex::new(account),
        }
    }

    fn cache(&self) -> MutexGuard<'_, Option<StoredAccount>> {
        self.cache.lock().unwrap_or_else(|e| e.into_inner())
    }

    pub fn get(&self) -> Option<StoredAccount> {
        self.cache().clone()
    }

    pub fn info(&self) -> Option<AccountInfo> {
        self.cache().as_ref().map(StoredAccount::info)
    }

    pub fn save(&self, account: StoredAccount) -> Result<(), String> {
        write_private(
            &self.path,
            &serde_json::to_vec_pretty(&account).map_err(|e| e.to_string())?,
        )
        .map_err(|e| format!("Не удалось сохранить аккаунт: {e}"))?;
        *self.cache() = Some(account);
        Ok(())
    }

    /// Forgets the account and removes the file.
    pub fn clear(&self) {
        *self.cache() = None;
        if let Err(e) = std::fs::remove_file(&self.path) {
            if e.kind() != std::io::ErrorKind::NotFound {
                warn!("Cannot remove {}: {e}", self.path.display());
            }
        }
    }
}

/// Writes through a temporary file so a crash leaves the old or the new
/// content, never half of it; on unix the file is private to the user.
fn write_private(path: &Path, bytes: &[u8]) -> std::io::Result<()> {
    use std::io::Write;

    let tmp = path.with_extension("json.tmp");
    let mut options = std::fs::OpenOptions::new();
    options.write(true).create(true).truncate(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let mut file = options.open(&tmp)?;
    file.write_all(bytes)?;
    file.sync_all()?;
    drop(file);
    std::fs::rename(&tmp, path)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn account() -> StoredAccount {
        StoredAccount {
            server_url: "https://meridianai.ru".into(),
            device_token: "secret-device-token".into(),
            device_id: 7,
            user: AccountUser {
                id: 1,
                email: "a@b.ru".into(),
                display_name: None,
            },
        }
    }

    #[test]
    fn server_url_is_validated_and_normalized() {
        assert_eq!(
            normalize_server_url(" https://meridianai.ru/ ").unwrap(),
            "https://meridianai.ru"
        );
        assert_eq!(
            normalize_server_url("https://host.ru/app/?x=1#y").unwrap(),
            "https://host.ru/app"
        );
        assert_eq!(
            normalize_server_url("http://localhost:8001").unwrap(),
            "http://localhost:8001"
        );
        assert_eq!(
            normalize_server_url("http://127.0.0.1:8001/").unwrap(),
            "http://127.0.0.1:8001"
        );
        for bad in [
            "",
            "meridianai.ru",
            "http://meridianai.ru",
            "ftp://meridianai.ru",
            "https://user:pw@meridianai.ru",
            "http://localhost.evil.ru",
        ] {
            assert!(normalize_server_url(bad).is_err(), "{bad}");
        }
    }

    #[test]
    fn urls_are_joined_with_one_slash() {
        assert_eq!(join_url("https://a.ru/", "/api/x"), "https://a.ru/api/x");
        assert_eq!(join_url("https://a.ru", "api/x"), "https://a.ru/api/x");
        assert_eq!(
            meeting_web_url("https://a.ru/", 5),
            "https://a.ru/meetings/5"
        );
    }

    #[test]
    fn token_is_masked_in_debug() {
        let text = format!("{:?}", account());
        assert!(!text.contains("secret-device-token"), "{text}");
        assert!(text.contains("***"));
    }

    #[test]
    fn account_survives_restart_and_clears() {
        let dir = tempfile::tempdir().unwrap();
        let store = AccountStore::open(dir.path());
        assert!(store.get().is_none());
        store.save(account()).unwrap();

        let reopened = AccountStore::open(dir.path());
        assert_eq!(reopened.get(), Some(account()));
        // The frontend view carries no token.
        let json = serde_json::to_string(&reopened.info().unwrap()).unwrap();
        assert!(!json.contains("secret-device-token"));

        reopened.clear();
        assert!(AccountStore::open(dir.path()).get().is_none());
        assert!(!dir.path().join("account.json").exists());
    }

    #[cfg(unix)]
    #[test]
    fn account_file_is_private() {
        use std::os::unix::fs::PermissionsExt;
        let dir = tempfile::tempdir().unwrap();
        AccountStore::open(dir.path()).save(account()).unwrap();
        let mode = std::fs::metadata(dir.path().join("account.json"))
            .unwrap()
            .permissions()
            .mode();
        assert_eq!(mode & 0o777, 0o600);
    }

    #[test]
    fn damaged_file_means_no_account() {
        let dir = tempfile::tempdir().unwrap();
        std::fs::write(dir.path().join("account.json"), b"{not json").unwrap();
        assert!(AccountStore::open(dir.path()).get().is_none());
    }
}
