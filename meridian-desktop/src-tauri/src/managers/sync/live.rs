//! What the live stream of a meeting needs from the sync: the meeting on the
//! server (made at once, the first time there is a connection) and the
//! address of its socket.

use std::fmt;
use std::path::Path;
use std::sync::Arc;

use super::account::{join_url, AccountStore};
use super::client::{ApiClient, ApiError};
use super::engine::{db_error, Engine};
use crate::managers::meeting::MeetingDb;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum LiveError {
    /// Nobody is signed in.
    NoAccount,
    Api(ApiError),
}

/// The meeting on the server and the socket address of its live stream. The
/// address carries the device token, so it is never printed.
pub struct LiveEndpoint {
    pub server_meeting_id: i64,
    ws_url: String,
}

impl LiveEndpoint {
    /// The address to connect to. Keep it out of logs and messages.
    pub fn ws_url(&self) -> &str {
        &self.ws_url
    }
}

impl fmt::Debug for LiveEndpoint {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("LiveEndpoint")
            .field("server_meeting_id", &self.server_meeting_id)
            .field("ws_url", &"***")
            .finish()
    }
}

/// `wss://host/ws/desktop/meetings/{id}?token=...` for the server at `server_url`.
pub(super) fn live_ws_url(
    server_url: &str,
    token: &str,
    server_meeting_id: i64,
) -> Result<String, ApiError> {
    let local = |_| ApiError::Local("Неверный адрес сервера".to_string());
    let mut url = reqwest::Url::parse(&join_url(
        server_url,
        &format!("ws/desktop/meetings/{server_meeting_id}"),
    ))
    .map_err(local)?;
    let scheme = if url.scheme() == "https" { "wss" } else { "ws" };
    url.set_scheme(scheme)
        .map_err(|()| ApiError::Local("Неверный адрес сервера".to_string()))?;
    url.query_pairs_mut().append_pair("token", token);
    Ok(url.into())
}

/// Makes sure the meeting exists on the server (the call is idempotent by the
/// meeting's id, and its result is kept in `meetings.db`) and builds the
/// socket address.
pub async fn prepare_live(
    accounts: &AccountStore,
    db: &Arc<MeetingDb>,
    meeting_id: &str,
) -> Result<LiveEndpoint, LiveError> {
    let account = accounts.get().ok_or(LiveError::NoAccount)?;
    let meeting = db
        .get_meeting(meeting_id)
        .map_err(|e| LiveError::Api(db_error(e)))?
        .ok_or_else(|| LiveError::Api(ApiError::Local("Встреча не найдена".to_string())))?;
    let client = ApiClient::new(&account.server_url, Some(&account.device_token));
    let engine = Engine {
        db,
        root: Path::new(""),
        client: &client,
        upload_audio: false,
    };
    let server_meeting_id = engine
        .create_meeting(&meeting)
        .await
        .map_err(LiveError::Api)?;
    let ws_url = live_ws_url(
        &account.server_url,
        &account.device_token,
        server_meeting_id,
    )
    .map_err(LiveError::Api)?;
    Ok(LiveEndpoint {
        server_meeting_id,
        ws_url,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_address_uses_the_socket_scheme_and_escapes_the_token() {
        let url = live_ws_url("https://meridianai.ru", "a b&c", 42).unwrap();
        assert_eq!(
            url,
            "wss://meridianai.ru/ws/desktop/meetings/42?token=a+b%26c"
        );
        let local = live_ws_url("http://localhost:8001/", "t", 1).unwrap();
        assert_eq!(local, "ws://localhost:8001/ws/desktop/meetings/1?token=t");
    }

    #[test]
    fn the_endpoint_does_not_print_the_token() {
        let endpoint = LiveEndpoint {
            server_meeting_id: 5,
            ws_url: live_ws_url("https://meridianai.ru", "secret-token", 5).unwrap(),
        };
        let printed = format!("{endpoint:?}");
        assert!(!printed.contains("secret-token"));
        assert!(printed.contains("5"));
    }
}
