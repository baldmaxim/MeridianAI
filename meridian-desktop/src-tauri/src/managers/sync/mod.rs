//! Sync of finished meetings with the Meridian server. A background thread
//! looks for stopped or interrupted meetings that are not on the server yet
//! every 30 seconds, and at once on `sync_now` or after a meeting stops.
//! See `engine.rs` for the steps and `account.rs` for the stored account.

pub mod account;
mod client;
mod engine;
#[cfg(test)]
mod tests;

use std::collections::HashMap;
use std::sync::mpsc::{self, RecvTimeoutError, Sender};
use std::sync::{Arc, Mutex, MutexGuard};
use std::time::{Duration, Instant};

use chrono::{SecondsFormat, Utc};
use log::{info, warn};
use serde::Serialize;
use specta::Type;
use tauri::AppHandle;
use tauri_specta::Event;

pub use account::{AccountInfo, AccountStore};
pub use client::{ApiClient, ApiError, LoginBody};
use engine::{Engine, Outcome};

use crate::managers::meeting::{MeetingDb, MeetingManager};
use crate::settings::get_settings;

/// Between two looks at the queue.
const POLL_INTERVAL: Duration = Duration::from_secs(30);
/// First wait after a failed attempt; doubles up to `MAX_RETRY_DELAY`.
const BASE_RETRY_DELAY: Duration = Duration::from_secs(30);
const MAX_RETRY_DELAY: Duration = Duration::from_secs(15 * 60);

/// What the sync is doing now, for the status bar of the UI.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Type)]
pub struct SyncStatus {
    /// The last request to the server got an answer.
    pub online: bool,
    /// A pass over the queue is under way.
    pub running: bool,
    /// Meetings waiting for the server.
    pub pending_count: u32,
    pub last_error: Option<String>,
    pub last_sync_at: Option<String>,
    /// The meeting being sent right now.
    pub syncing_meeting_id: Option<String>,
}

/// A meeting's sync state or the status changed (`meeting_id` says which
/// meeting, when it is one; reload it with `get_meeting`/`list_meetings`).
#[derive(Clone, Debug, Serialize, Type, Event)]
pub struct SyncState {
    pub meeting_id: Option<String>,
    pub status: SyncStatus,
}

/// Signed in, signed out, or thrown out by the server (`reason` then says why).
#[derive(Clone, Debug, Serialize, Type, Event)]
pub struct AccountChanged {
    pub account: Option<AccountInfo>,
    pub reason: Option<String>,
}

#[derive(Clone, Debug)]
pub enum Notice {
    State(SyncState),
    Account(AccountChanged),
}

#[derive(Default)]
struct Inner {
    online: bool,
    running: bool,
    last_error: Option<String>,
    last_sync_at: Option<String>,
    current: Option<String>,
    /// Per meeting: failed attempts in a row and when the next one is due.
    backoff: HashMap<String, (u32, Instant)>,
}

/// The queue logic, without Tauri: events go out through `notify`.
pub struct SyncCore {
    db: Arc<MeetingDb>,
    root: std::path::PathBuf,
    accounts: Arc<AccountStore>,
    inner: Mutex<Inner>,
    notify: Box<dyn Fn(Notice) + Send + Sync>,
}

/// How long to wait after the `attempts`-th failure in a row.
pub fn retry_delay(attempts: u32) -> Duration {
    let exp = attempts.saturating_sub(1).min(16);
    BASE_RETRY_DELAY
        .saturating_mul(1u32 << exp)
        .min(MAX_RETRY_DELAY)
}

impl SyncCore {
    pub fn new(
        db: Arc<MeetingDb>,
        root: std::path::PathBuf,
        accounts: Arc<AccountStore>,
        notify: Box<dyn Fn(Notice) + Send + Sync>,
    ) -> Self {
        Self {
            db,
            root,
            accounts,
            inner: Mutex::new(Inner::default()),
            notify,
        }
    }

    fn inner(&self) -> MutexGuard<'_, Inner> {
        self.inner.lock().unwrap_or_else(|e| e.into_inner())
    }

    pub fn status(&self) -> SyncStatus {
        let pending_count = self.db.count_meetings_for_sync().unwrap_or(0);
        let inner = self.inner();
        SyncStatus {
            online: inner.online,
            running: inner.running,
            pending_count,
            last_error: inner.last_error.clone(),
            last_sync_at: inner.last_sync_at.clone(),
            syncing_meeting_id: inner.current.clone(),
        }
    }

    fn announce(&self, meeting_id: Option<&str>) {
        (self.notify)(Notice::State(SyncState {
            meeting_id: meeting_id.map(str::to_string),
            status: self.status(),
        }));
    }

    /// Forget the waiting times: try everything now (`sync_now`).
    pub fn reset_backoff(&self) {
        self.inner().backoff.clear();
    }

    /// Puts a failed meeting back in the queue.
    pub fn retry_meeting(&self, id: &str) -> Result<(), String> {
        let found = self
            .db
            .reset_sync(id)
            .map_err(|e| format!("Ошибка базы встреч: {e:#}"))?;
        if !found {
            return Err("Встреча не найдена или уже синхронизирована".to_string());
        }
        self.inner().backoff.remove(id);
        self.announce(Some(id));
        Ok(())
    }

    fn due(&self, id: &str) -> bool {
        match self.inner().backoff.get(id) {
            Some((_, next_at)) => Instant::now() >= *next_at,
            None => true,
        }
    }

    /// One look at the queue: sends what is due.
    pub async fn run_pass(&self, upload_audio: bool) {
        let Some(account) = self.accounts.get() else {
            return;
        };
        let meetings = match self.db.meetings_for_sync() {
            Ok(meetings) => meetings,
            Err(e) => {
                warn!("Cannot read the sync queue: {e:#}");
                return;
            }
        };
        if !meetings.iter().any(|m| self.due(&m.id)) {
            return;
        }
        let client = ApiClient::new(&account.server_url, Some(&account.device_token));
        self.inner().running = true;
        self.announce(None);

        for meeting in meetings {
            if !self.due(&meeting.id) {
                continue;
            }
            self.inner().current = Some(meeting.id.clone());
            self.announce(Some(&meeting.id));
            let engine = Engine {
                db: &self.db,
                root: &self.root,
                client: &client,
                upload_audio,
            };
            let outcome = engine.sync_meeting(&meeting.id).await;
            let signed_out = outcome == Outcome::Unauthorized;
            self.apply(&meeting.id, outcome);
            if signed_out {
                break;
            }
        }
        {
            let mut inner = self.inner();
            inner.running = false;
            inner.current = None;
        }
        self.announce(None);
    }

    fn apply(&self, id: &str, outcome: Outcome) {
        match outcome {
            Outcome::Synced => {
                let mut inner = self.inner();
                inner.backoff.remove(id);
                inner.online = true;
                inner.last_error = None;
                inner.last_sync_at = Some(Utc::now().to_rfc3339_opts(SecondsFormat::Millis, true));
            }
            Outcome::Retry { message, reachable } => {
                warn!("Sync of {id} will be retried: {message}");
                let mut inner = self.inner();
                let attempts = inner.backoff.get(id).map_or(0, |(n, _)| *n) + 1;
                inner.backoff.insert(
                    id.to_string(),
                    (attempts, Instant::now() + retry_delay(attempts)),
                );
                inner.online = reachable;
                inner.last_error = Some(message);
            }
            Outcome::Failed(message) => {
                warn!("Sync of {id} failed: {message}");
                let mut inner = self.inner();
                inner.backoff.remove(id);
                inner.online = true;
                inner.last_error = Some(message);
            }
            Outcome::Unauthorized => {
                info!("The server does not accept this device any more; signing out");
                self.accounts.clear();
                {
                    let mut inner = self.inner();
                    inner.online = true;
                    inner.last_error = Some(ApiError::Unauthorized.to_string());
                }
                (self.notify)(Notice::Account(AccountChanged {
                    account: None,
                    reason: Some(ApiError::Unauthorized.to_string()),
                }));
            }
            Outcome::Postponed => {}
        }
        self.announce(Some(id));
    }
}

enum Wake {
    /// `true`: ignore the waiting times.
    Now(bool),
}

pub struct SyncManager {
    core: Arc<SyncCore>,
    wake: Sender<Wake>,
}

impl SyncManager {
    /// Starts the background thread; the first pass runs at once.
    pub fn new(app: &AppHandle, meetings: &MeetingManager, accounts: Arc<AccountStore>) -> Self {
        let emitter = app.clone();
        let core = Arc::new(SyncCore::new(
            meetings.db(),
            meetings.root().to_path_buf(),
            accounts,
            Box::new(move |notice| {
                let _ = match notice {
                    Notice::State(state) => state.emit(&emitter),
                    Notice::Account(changed) => changed.emit(&emitter),
                };
            }),
        ));
        let (wake, rx) = mpsc::channel();
        let _ = wake.send(Wake::Now(false));

        let worker = Arc::clone(&core);
        let app = app.clone();
        let spawned = std::thread::Builder::new()
            .name("meeting-sync".into())
            .spawn(move || loop {
                match rx.recv_timeout(POLL_INTERVAL) {
                    Ok(Wake::Now(true)) => worker.reset_backoff(),
                    Ok(Wake::Now(false)) | Err(RecvTimeoutError::Timeout) => {}
                    Err(RecvTimeoutError::Disconnected) => break,
                }
                let upload_audio = get_settings(&app).upload_audio;
                tauri::async_runtime::block_on(worker.run_pass(upload_audio));
            });
        if let Err(e) = spawned {
            warn!("Cannot start the sync thread: {e}");
        }
        Self { core, wake }
    }

    pub fn core(&self) -> &Arc<SyncCore> {
        &self.core
    }

    /// Look at the queue now (after a meeting stops or the user signs in).
    pub fn wake(&self) {
        let _ = self.wake.send(Wake::Now(false));
    }

    /// Look at the queue now, ignoring the waiting times.
    pub fn sync_now(&self) {
        let _ = self.wake.send(Wake::Now(true));
    }

    pub fn retry_meeting(&self, id: &str) -> Result<(), String> {
        self.core.retry_meeting(id)?;
        self.wake();
        Ok(())
    }
}
