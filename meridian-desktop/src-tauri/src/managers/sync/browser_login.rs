//! Sign-in through the system browser: the app listens on a loopback port,
//! the browser comes back to it with a one-time code, and the code is
//! exchanged for a device token (PKCE: only the app knows the verifier).

use std::time::Duration;

use sha2::{Digest, Sha256};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::{TcpListener, TcpStream};
use tokio::sync::mpsc;
use uuid::Uuid;

use super::account::join_url;

/// How long the user has to finish the sign-in in the browser.
pub const LOGIN_TIMEOUT: Duration = Duration::from_secs(5 * 60);
/// Per connection: the browser must send its request head within this time.
const READ_TIMEOUT: Duration = Duration::from_secs(10);
const MAX_HEAD: usize = 8 * 1024;

pub const TIMEOUT_MESSAGE: &str = "Время на вход истекло. Попробуйте ещё раз.";

/// Secrets of one sign-in attempt.
#[derive(Debug, Clone)]
pub struct Pkce {
    /// 64 hex chars; never leaves the app except in the token request.
    pub verifier: String,
    /// Lowercase hex SHA-256 of the verifier; goes to the browser.
    pub challenge: String,
    /// 32 hex chars; ties the browser's answer to this attempt.
    pub state: String,
}

impl Pkce {
    pub fn generate() -> Self {
        let verifier = format!("{}{}", Uuid::new_v4().simple(), Uuid::new_v4().simple());
        let challenge = challenge_of(&verifier);
        let state = Uuid::new_v4().simple().to_string();
        Self {
            verifier,
            challenge,
            state,
        }
    }
}

/// Lowercase hex SHA-256 of `verifier`.
pub fn challenge_of(verifier: &str) -> String {
    Sha256::digest(verifier.as_bytes())
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect()
}

/// The page the system browser opens.
pub fn login_url(server_url: &str, port: u16, pkce: &Pkce) -> String {
    format!(
        "{}?port={port}&state={}&challenge={}",
        join_url(server_url, "desktop-login"),
        pkce.state,
        pkce.challenge
    )
}

/// Loopback only: nobody but this computer can reach the port.
pub async fn bind_loopback() -> Result<(TcpListener, u16), String> {
    let listener = TcpListener::bind("127.0.0.1:0")
        .await
        .map_err(|e| format!("Не удалось начать вход: {e}"))?;
    let port = listener
        .local_addr()
        .map_err(|e| format!("Не удалось начать вход: {e}"))?
        .port();
    Ok((listener, port))
}

/// What the browser brought back.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum CallbackResult {
    Code(String),
    /// `error=access_denied`: the user declined on the site.
    Denied,
    /// Any other `error`.
    Failed,
}

/// A request head, understood.
#[derive(Debug, PartialEq, Eq)]
enum Request {
    /// Not `GET /callback` (favicon and the like).
    NotFound,
    /// Not a valid request line.
    Malformed,
    Callback(Vec<(String, String)>),
}

fn hex_value(b: u8) -> Option<u8> {
    match b {
        b'0'..=b'9' => Some(b - b'0'),
        b'a'..=b'f' => Some(b - b'a' + 10),
        b'A'..=b'F' => Some(b - b'A' + 10),
        _ => None,
    }
}

/// `%XX` of one query component; a broken `%` stays as it is.
pub fn percent_decode(text: &str) -> String {
    let bytes = text.as_bytes();
    let mut out = Vec::with_capacity(bytes.len());
    let mut i = 0;
    while i < bytes.len() {
        match bytes[i] {
            b'%' => {
                let high = bytes.get(i + 1).copied().and_then(hex_value);
                let low = bytes.get(i + 2).copied().and_then(hex_value);
                if let (Some(high), Some(low)) = (high, low) {
                    out.push(high * 16 + low);
                    i += 2;
                } else {
                    out.push(b'%');
                }
            }
            other => out.push(other),
        }
        i += 1;
    }
    String::from_utf8_lossy(&out).into_owned()
}

/// `a=1&b=%D0%B0` as decoded pairs.
pub fn parse_query(query: &str) -> Vec<(String, String)> {
    query
        .split('&')
        .filter(|pair| !pair.is_empty())
        .map(|pair| {
            let (key, value) = pair.split_once('=').unwrap_or((pair, ""));
            (percent_decode(key), percent_decode(value))
        })
        .collect()
}

/// The request line of a head: `GET /callback?... HTTP/1.1`.
fn parse_request(head: &str) -> Request {
    let line = head.lines().next().unwrap_or_default();
    let mut parts = line.split_whitespace();
    let (Some(method), Some(target), Some(version), None) =
        (parts.next(), parts.next(), parts.next(), parts.next())
    else {
        return Request::Malformed;
    };
    if !version.starts_with("HTTP/") {
        return Request::Malformed;
    }
    let (path, query) = target.split_once('?').unwrap_or((target, ""));
    if method != "GET" || path != "/callback" {
        return Request::NotFound;
    }
    Request::Callback(parse_query(query))
}

fn query_value<'a>(pairs: &'a [(String, String)], key: &str) -> Option<&'a str> {
    pairs
        .iter()
        .find(|(k, _)| k == key)
        .map(|(_, v)| v.as_str())
}

/// Reads the request head (up to the empty line). The whole head is read even
/// though only the first line matters: closing a socket with unread input
/// resets the connection and the browser may lose the answer.
async fn read_head(stream: &mut TcpStream) -> Option<String> {
    let mut data: Vec<u8> = Vec::new();
    let mut chunk = [0u8; 1024];
    while !data.windows(4).any(|w| w == b"\r\n\r\n") {
        if data.len() >= MAX_HEAD {
            return None;
        }
        let n = stream.read(&mut chunk).await.ok()?;
        if n == 0 {
            return None;
        }
        data.extend_from_slice(&chunk[..n]);
    }
    Some(String::from_utf8_lossy(&data).into_owned())
}

fn page(title: &str, text: &str) -> String {
    format!(
        "<!doctype html><html lang=\"ru\"><head><meta charset=\"utf-8\">\
         <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\
         <title>{title}</title></head>\
         <body style=\"font-family:system-ui,sans-serif;text-align:center;margin:20vh 1rem 0\">\
         <h1 style=\"font-size:1.3rem\">{text}</h1></body></html>"
    )
}

async fn respond(stream: &mut TcpStream, status: &str, body: &str) {
    let response = format!(
        "HTTP/1.1 {status}\r\nContent-Type: text/html; charset=utf-8\r\n\
         Content-Length: {}\r\nCache-Control: no-store\r\nReferrer-Policy: no-referrer\r\n\
         Connection: close\r\n\r\n{body}",
        body.len()
    );
    let _ = stream.write_all(response.as_bytes()).await;
    let _ = stream.shutdown().await;
}

/// One connection. `Some` only for a valid callback of this attempt.
async fn handle_connection(mut stream: TcpStream, state: &str) -> Option<CallbackResult> {
    let head = tokio::time::timeout(READ_TIMEOUT, read_head(&mut stream))
        .await
        .ok()
        .flatten()?;
    let pairs = match parse_request(&head) {
        Request::Callback(pairs) => pairs,
        Request::NotFound => {
            respond(
                &mut stream,
                "404 Not Found",
                &page("Meridian", "Не найдено"),
            )
            .await;
            return None;
        }
        Request::Malformed => {
            respond(
                &mut stream,
                "400 Bad Request",
                &page("Meridian", "Неверный запрос"),
            )
            .await;
            return None;
        }
    };
    if query_value(&pairs, "state") != Some(state) {
        respond(
            &mut stream,
            "400 Bad Request",
            &page(
                "Meridian",
                "Неверный запрос входа. Начните вход заново в приложении.",
            ),
        )
        .await;
        return None;
    }
    let (result, text) = if let Some(error) = query_value(&pairs, "error") {
        if error == "access_denied" {
            (CallbackResult::Denied, "Вход отменён.")
        } else {
            (CallbackResult::Failed, "Вход не выполнен.")
        }
    } else if let Some(code) = query_value(&pairs, "code").filter(|c| !c.is_empty()) {
        (
            CallbackResult::Code(code.to_string()),
            "Вход выполнен. Вернитесь в приложение Meridian — вкладку можно закрыть.",
        )
    } else {
        respond(
            &mut stream,
            "400 Bad Request",
            &page("Meridian", "Неверный запрос входа."),
        )
        .await;
        return None;
    };
    respond(&mut stream, "200 OK", &page("Meridian", text)).await;
    Some(result)
}

/// Waits for the browser's callback with this `state`; other requests are
/// answered and ignored. A connection is served in its own task so that an idle
/// pre-connection of the browser does not hold the real request back.
pub async fn wait_for_callback(
    listener: &TcpListener,
    state: &str,
    timeout: Duration,
) -> Result<CallbackResult, String> {
    let (tx, mut rx) = mpsc::channel::<CallbackResult>(8);
    let wait = async {
        loop {
            tokio::select! {
                accepted = listener.accept() => {
                    let Ok((stream, _)) = accepted else { continue };
                    let (tx, state) = (tx.clone(), state.to_string());
                    tokio::spawn(async move {
                        if let Some(result) = handle_connection(stream, &state).await {
                            let _ = tx.send(result).await;
                        }
                    });
                }
                Some(result) = rx.recv() => return result,
            }
        }
    };
    tokio::time::timeout(timeout, wait)
        .await
        .map_err(|_| TIMEOUT_MESSAGE.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::managers::sync::tests::{err, ok, start_mock};
    use crate::managers::sync::ApiClient;

    #[test]
    fn challenge_is_sha256_hex_of_the_verifier() {
        // SHA-256("abc")
        assert_eq!(
            challenge_of("abc"),
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        );
        let pkce = Pkce::generate();
        assert_eq!(pkce.verifier.len(), 64);
        assert_eq!(pkce.state.len(), 32);
        assert_eq!(pkce.challenge, challenge_of(&pkce.verifier));
        assert!(pkce
            .verifier
            .chars()
            .all(|c| c.is_ascii_digit() || ('a'..='f').contains(&c)));
        assert_ne!(pkce.verifier, Pkce::generate().verifier);
    }

    #[test]
    fn login_url_has_port_state_and_challenge() {
        let pkce = Pkce {
            verifier: "v".into(),
            challenge: "c1".into(),
            state: "s1".into(),
        };
        assert_eq!(
            login_url("https://meridianai.ru/", 5000, &pkce),
            "https://meridianai.ru/desktop-login?port=5000&state=s1&challenge=c1"
        );
    }

    #[test]
    fn query_values_are_percent_decoded() {
        let pairs = parse_query("code=a%2Fb%3D%3D&state=x%20y+z&empty=&flag&bad=%zz%4");
        assert_eq!(query_value(&pairs, "code"), Some("a/b=="));
        assert_eq!(query_value(&pairs, "state"), Some("x y+z"));
        assert_eq!(query_value(&pairs, "empty"), Some(""));
        assert_eq!(query_value(&pairs, "flag"), Some(""));
        assert_eq!(query_value(&pairs, "bad"), Some("%zz%4"));
        assert_eq!(percent_decode("%D0%B0%D0%B1"), "аб");
    }

    #[test]
    fn only_get_callback_is_accepted() {
        let head = "GET /callback?code=abc&state=s HTTP/1.1\r\nHost: x\r\n\r\n";
        let Request::Callback(pairs) = parse_request(head) else {
            panic!("callback expected");
        };
        assert_eq!(query_value(&pairs, "code"), Some("abc"));
        assert_eq!(
            parse_request("GET /favicon.ico HTTP/1.1\r\n\r\n"),
            Request::NotFound
        );
        assert_eq!(
            parse_request("GET /callbackx?code=1 HTTP/1.1\r\n\r\n"),
            Request::NotFound
        );
        assert_eq!(
            parse_request("POST /callback?code=1 HTTP/1.1\r\n\r\n"),
            Request::NotFound
        );
        assert_eq!(parse_request("garbage\r\n\r\n"), Request::Malformed);
    }

    async fn get(port: u16, target: &str) -> String {
        let mut stream = TcpStream::connect(("127.0.0.1", port)).await.unwrap();
        let request = format!("GET {target} HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n");
        stream.write_all(request.as_bytes()).await.unwrap();
        let mut answer = Vec::new();
        stream.read_to_end(&mut answer).await.unwrap();
        String::from_utf8(answer).unwrap()
    }

    #[tokio::test]
    async fn the_server_takes_the_code_only_with_the_right_state() {
        let (listener, port) = bind_loopback().await.unwrap();
        let waiter = tokio::spawn(async move {
            wait_for_callback(&listener, "good", Duration::from_secs(20)).await
        });

        let favicon = get(port, "/favicon.ico").await;
        assert!(favicon.starts_with("HTTP/1.1 404"), "{favicon}");
        let wrong = get(port, "/callback?code=stolen&state=bad").await;
        assert!(wrong.starts_with("HTTP/1.1 400"), "{wrong}");
        let missing = get(port, "/callback?code=stolen").await;
        assert!(missing.starts_with("HTTP/1.1 400"), "{missing}");
        assert!(!waiter.is_finished());

        let good = get(port, "/callback?code=my%2Fcode&state=good").await;
        assert!(good.starts_with("HTTP/1.1 200"), "{good}");
        assert!(good.contains("text/html; charset=utf-8"));
        assert!(good.contains("Connection: close"));
        assert!(good.contains("Вход выполнен"));
        assert_eq!(
            waiter.await.unwrap(),
            Ok(CallbackResult::Code("my/code".into()))
        );
    }

    #[tokio::test]
    async fn the_user_may_decline() {
        let (listener, port) = bind_loopback().await.unwrap();
        let waiter = tokio::spawn(async move {
            wait_for_callback(&listener, "s", Duration::from_secs(20)).await
        });
        let answer = get(port, "/callback?error=access_denied&state=s").await;
        assert!(answer.contains("Вход отменён."), "{answer}");
        assert_eq!(waiter.await.unwrap(), Ok(CallbackResult::Denied));
    }

    #[tokio::test]
    async fn an_idle_connection_does_not_block_the_real_one() {
        let (listener, port) = bind_loopback().await.unwrap();
        let waiter = tokio::spawn(async move {
            wait_for_callback(&listener, "s", Duration::from_secs(20)).await
        });
        let _idle = TcpStream::connect(("127.0.0.1", port)).await.unwrap();
        get(port, "/callback?code=c&state=s").await;
        assert_eq!(waiter.await.unwrap(), Ok(CallbackResult::Code("c".into())));
    }

    #[tokio::test]
    async fn waiting_times_out() {
        let (listener, _) = bind_loopback().await.unwrap();
        let result = wait_for_callback(&listener, "s", Duration::from_millis(50)).await;
        assert_eq!(result, Err(TIMEOUT_MESSAGE.to_string()));
    }

    #[tokio::test]
    async fn the_code_is_exchanged_for_a_device_token() {
        let mock = start_mock(|req| {
            if req.method == "POST" && req.path == "/api/desktop/token" {
                ok(r#"{"device_token":"t","device_id":7,"user":{"id":1,"email":"a@b.ru","display_name":null}}"#)
            } else {
                err(404, "no")
            }
        })
        .await;
        let response = ApiClient::new(&mock.url, None)
            .exchange_browser_code("the-code", "the-verifier")
            .await
            .unwrap();
        assert_eq!(response.device_id, 7);
        assert_eq!(response.user.email, "a@b.ru");
        let body = mock.all()[0].json();
        assert_eq!(body["code"], "the-code");
        assert_eq!(body["verifier"], "the-verifier");
        assert!(body["device_name"].is_string());
        assert!(body["platform"].is_string());
        assert!(body["app_version"].is_string());
    }

    #[tokio::test]
    async fn exchange_failures_are_explained() {
        let mock = start_mock(|_| err(400, "bad code")).await;
        let e = ApiClient::new(&mock.url, None)
            .exchange_browser_code("c", "v")
            .await
            .err()
            .unwrap();
        assert_eq!(
            e.login_message(),
            "Код входа недействителен или истёк. Попробуйте ещё раз."
        );
    }
}
