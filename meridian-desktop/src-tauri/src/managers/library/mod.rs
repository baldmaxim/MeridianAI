//! The library: all meetings of the signed-in user from the site, the projects
//! (customers and objects), one meeting for viewing and "ask about a meeting".
//! The answers are cached in `meetings.db` for offline use (see `cache.rs`),
//! and the full-text search over local and server meetings lives in `search.rs`.
//!
//! The functions take the client as `Option`: `None` is "not signed in".

mod cache;
mod search;
#[cfg(test)]
mod search_tests;
#[cfg(test)]
mod test_support;
#[cfg(test)]
mod tests;
pub mod types;

use std::sync::Arc;

use log::warn;

pub use types::{AskAnswer, LibrarySnapshot, MeetingViewResult, SearchHit};

use crate::managers::meeting::MeetingDb;
use crate::managers::sync::{ApiClient, ApiError};

/// How many of the newest meetings the library keeps.
const LIBRARY_LIMIT: u32 = 500;

const MSG_NO_ACCOUNT: &str = "Войдите в аккаунт Meridian";
const MSG_NO_VIEW_OFFLINE: &str = "Нет сети, встреча ещё не открывалась на этом компьютере";
const MSG_ASK_OFFLINE: &str = "Спросить можно только при подключении к сети";

fn db_error(e: impl std::fmt::Display) -> ApiError {
    ApiError::Local(format!("Ошибка базы встреч: {e:#}"))
}

/// The library from the cache, as it is now.
fn cached_snapshot(db: &MeetingDb, offline: bool) -> Result<LibrarySnapshot, ApiError> {
    let (items, library_at) = db.get_library().map_err(db_error)?;
    let (projects, projects_at) = db.get_projects().map_err(db_error)?;
    Ok(LibrarySnapshot {
        items,
        projects,
        fetched_at: library_at.max(projects_at),
        offline,
        signed_in: true,
    })
}

/// `refresh`: ask the server (library and projects) and keep the answer; when
/// it can not be reached the cache is returned with `offline` set. Only a
/// refused token is an error: the caller has to sign out.
pub async fn library_get(
    db: &Arc<MeetingDb>,
    client: Option<&ApiClient>,
    refresh: bool,
) -> Result<LibrarySnapshot, ApiError> {
    let Some(client) = client else {
        return Ok(LibrarySnapshot {
            items: Vec::new(),
            projects: Vec::new(),
            fetched_at: None,
            offline: false,
            signed_in: false,
        });
    };
    if !refresh {
        return cached_snapshot(db, false);
    }
    let (items, projects) =
        futures_util::future::join(client.get_library(LIBRARY_LIMIT), client.get_projects()).await;
    let mut offline = false;
    match items {
        Ok(items) => db.put_library(&items).map_err(db_error)?,
        Err(ApiError::Unauthorized) => return Err(ApiError::Unauthorized),
        Err(e) => {
            warn!("The library was not refreshed: {e}");
            offline = true;
        }
    }
    match projects {
        Ok(projects) => db.put_projects(&projects).map_err(db_error)?,
        Err(ApiError::Unauthorized) => return Err(ApiError::Unauthorized),
        Err(e) => {
            warn!("The projects were not refreshed: {e}");
            offline = true;
        }
    }
    cached_snapshot(db, offline)
}

/// The meeting from the server (and into the cache); when the server can not be
/// reached, from the cache.
pub async fn meeting_view_get(
    db: &Arc<MeetingDb>,
    client: Option<&ApiClient>,
    server_meeting_id: i64,
) -> Result<MeetingViewResult, ApiError> {
    let client = client.ok_or_else(|| ApiError::Local(MSG_NO_ACCOUNT.to_string()))?;
    match client.get_meeting_view(server_meeting_id).await {
        Ok(view) => {
            db.put_view(&view).map_err(db_error)?;
            Ok(MeetingViewResult {
                view,
                from_cache: false,
            })
        }
        // No connection or a server failure: show what was opened before.
        Err(ApiError::Retry { .. }) => {
            match db.get_view(server_meeting_id).map_err(db_error)? {
                Some(view) => Ok(MeetingViewResult {
                    view,
                    from_cache: true,
                }),
                None => Err(ApiError::Local(MSG_NO_VIEW_OFFLINE.to_string())),
            }
        }
        Err(e) => Err(e),
    }
}

pub async fn meeting_ask(
    client: Option<&ApiClient>,
    server_meeting_id: i64,
    question: &str,
) -> Result<AskAnswer, ApiError> {
    let client = client.ok_or_else(|| ApiError::Local(MSG_NO_ACCOUNT.to_string()))?;
    let question = question.trim();
    if question.is_empty() {
        return Err(ApiError::Local("Введите вопрос".to_string()));
    }
    match client.ask(server_meeting_id, question).await {
        Err(ApiError::Retry { status: None, .. }) => {
            Err(ApiError::Local(MSG_ASK_OFFLINE.to_string()))
        }
        other => other,
    }
}
