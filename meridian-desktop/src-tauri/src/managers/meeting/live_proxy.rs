//! The socket of the live link goes through the proxy the rest of the app
//! uses. `reqwest` takes it from the environment (`HTTPS_PROXY`, `ALL_PROXY`,
//! `NO_PROXY`) and from the system settings; `tokio-tungstenite` takes none,
//! so the environment's one is done here: an `http://` proxy and `CONNECT`.
//! (A proxy that only the system settings name — the Windows or macOS network
//! settings — and a SOCKS proxy are not followed: the connection is direct.)
//! The proxy's address may carry a password: it is never logged.

use std::io;

use reqwest::Url;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::TcpStream;
use tokio_tungstenite::tungstenite::handshake::client::Response;
use tokio_tungstenite::tungstenite::Error;
use tokio_tungstenite::{MaybeTlsStream, WebSocketStream};

/// The proxy's answer to `CONNECT` is read up to this size.
const MAX_REPLY: usize = 16 * 1024;

/// An `http://` proxy.
#[derive(Debug, PartialEq, Eq)]
struct Proxy {
    host: String,
    port: u16,
    /// `user:password`, for `Proxy-Authorization: Basic`.
    credentials: Option<String>,
}

/// The proxy for `target` from the environment, if there is one and `target`
/// is not excluded by `NO_PROXY`. `env` reads a variable.
fn proxy_for(target: &Url, env: impl Fn(&str) -> Option<String>) -> Option<Proxy> {
    let get = |names: &[&str]| {
        names
            .iter()
            .find_map(|name| env(name).filter(|v| !v.trim().is_empty()))
    };
    let host = target.host_str()?;
    if let Some(list) = get(&["NO_PROXY", "no_proxy"]) {
        if excluded(host, &list) {
            return None;
        }
    }
    let raw = if target.scheme() == "wss" {
        get(&["HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy"])
    } else {
        get(&["HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"])
    }?;
    let raw = raw.trim();
    let url = Url::parse(raw)
        .ok()
        .filter(|u| u.host_str().is_some())
        .or_else(|| Url::parse(&format!("http://{raw}")).ok())?;
    if url.scheme() != "http" {
        return None;
    }
    let credentials = (!url.username().is_empty()).then(|| {
        format!(
            "{}:{}",
            percent_decode(url.username()),
            percent_decode(url.password().unwrap_or_default())
        )
    });
    Some(Proxy {
        host: url.host_str()?.to_string(),
        port: url.port_or_known_default().unwrap_or(80),
        credentials,
    })
}

/// `NO_PROXY`: `*`, or names the host equals or ends with (`.example.com`,
/// `example.com`).
fn excluded(host: &str, list: &str) -> bool {
    let host = host.to_ascii_lowercase();
    list.split(',').map(str::trim).any(|entry| {
        let entry = entry.trim_start_matches('.').to_ascii_lowercase();
        entry == "*"
            || (!entry.is_empty() && (host == entry || host.ends_with(&format!(".{entry}"))))
    })
}

fn percent_decode(text: &str) -> String {
    let bytes = text.as_bytes();
    let mut out = Vec::with_capacity(bytes.len());
    let mut i = 0;
    while i < bytes.len() {
        let hex = bytes
            .get(i + 1..i + 3)
            .and_then(|h| std::str::from_utf8(h).ok())
            .and_then(|h| u8::from_str_radix(h, 16).ok());
        match (bytes[i], hex) {
            (b'%', Some(byte)) => {
                out.push(byte);
                i += 3;
            }
            (byte, _) => {
                out.push(byte);
                i += 1;
            }
        }
    }
    String::from_utf8_lossy(&out).into_owned()
}

fn base64(data: &[u8]) -> String {
    const ALPHABET: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    let mut out = String::with_capacity(data.len().div_ceil(3) * 4);
    for chunk in data.chunks(3) {
        let n = chunk
            .iter()
            .enumerate()
            .fold(0u32, |acc, (i, b)| acc | u32::from(*b) << (16 - 8 * i));
        for i in 0..4 {
            if i <= chunk.len() {
                out.push(char::from(ALPHABET[(n >> (18 - 6 * i) & 63) as usize]));
            } else {
                out.push('=');
            }
        }
    }
    out
}

/// A tunnel to `host:port` through the proxy.
async fn tunnel(proxy: &Proxy, host: &str, port: u16) -> io::Result<TcpStream> {
    let mut stream = TcpStream::connect((proxy.host.as_str(), proxy.port)).await?;
    let mut request = format!("CONNECT {host}:{port} HTTP/1.1\r\nHost: {host}:{port}\r\n");
    if let Some(credentials) = &proxy.credentials {
        request.push_str(&format!(
            "Proxy-Authorization: Basic {}\r\n",
            base64(credentials.as_bytes())
        ));
    }
    request.push_str("\r\n");
    stream.write_all(request.as_bytes()).await?;

    // Read byte by byte up to the end of the headers: nothing of the tunnel's
    // own traffic may be swallowed.
    let mut reply = Vec::new();
    let mut byte = [0u8; 1];
    while !reply.ends_with(b"\r\n\r\n") {
        if reply.len() >= MAX_REPLY || stream.read(&mut byte).await? == 0 {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "bad proxy reply",
            ));
        }
        reply.push(byte[0]);
    }
    let status = String::from_utf8_lossy(&reply)
        .lines()
        .next()
        .and_then(|line| line.split_whitespace().nth(1).map(str::to_string))
        .unwrap_or_default();
    if status.starts_with('2') {
        Ok(stream)
    } else {
        Err(io::Error::new(
            io::ErrorKind::ConnectionRefused,
            format!("proxy refused the tunnel: {status}"),
        ))
    }
}

/// `connect_async`, through the environment's proxy when there is one.
pub(super) async fn connect(
    url: &str,
) -> Result<(WebSocketStream<MaybeTlsStream<TcpStream>>, Response), Error> {
    let proxy = Url::parse(url)
        .ok()
        .and_then(|target| proxy_for(&target, |name| std::env::var(name).ok()));
    let (Some(proxy), Ok(target)) = (proxy, Url::parse(url)) else {
        return tokio_tungstenite::connect_async(url).await;
    };
    let host = target.host_str().unwrap_or_default();
    let port = target.port_or_known_default().unwrap_or(443);
    let stream = tunnel(&proxy, host, port).await.map_err(Error::Io)?;
    tokio_tungstenite::client_async_tls(url, stream).await
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashMap;

    fn env(pairs: &[(&str, &str)]) -> impl Fn(&str) -> Option<String> {
        let map: HashMap<String, String> = pairs
            .iter()
            .map(|(k, v)| ((*k).to_string(), (*v).to_string()))
            .collect();
        move |name| map.get(name).cloned()
    }

    fn url(text: &str) -> Url {
        Url::parse(text).unwrap()
    }

    #[test]
    fn the_proxy_comes_from_the_environment_by_scheme() {
        let vars = env(&[("HTTPS_PROXY", "http://proxy.local:3128")]);
        let proxy = proxy_for(&url("wss://meridianai.ru/ws"), &vars).unwrap();
        assert_eq!((proxy.host.as_str(), proxy.port), ("proxy.local", 3128));
        assert_eq!(proxy.credentials, None);
        // `ws://` looks for the HTTP one, which is not set.
        assert_eq!(proxy_for(&url("ws://meridianai.ru/ws"), &vars), None);
        // Nothing set: direct.
        assert_eq!(proxy_for(&url("wss://a.b/ws"), env(&[])), None);
    }

    #[test]
    fn an_address_without_a_scheme_and_with_a_password_is_understood() {
        let vars = env(&[("https_proxy", "user:p%40ss@10.0.0.5:8080")]);
        let proxy = proxy_for(&url("wss://a.b/ws"), &vars).unwrap();
        assert_eq!((proxy.host.as_str(), proxy.port), ("10.0.0.5", 8080));
        assert_eq!(proxy.credentials.as_deref(), Some("user:p@ss"));
        // SOCKS is not followed.
        let socks = env(&[("ALL_PROXY", "socks5://127.0.0.1:1080")]);
        assert_eq!(proxy_for(&url("wss://a.b/ws"), &socks), None);
    }

    #[test]
    fn no_proxy_excludes_hosts_and_their_subdomains() {
        let vars = env(&[
            ("HTTPS_PROXY", "http://p:1"),
            ("NO_PROXY", "localhost, .meridianai.ru"),
        ]);
        assert_eq!(proxy_for(&url("wss://api.meridianai.ru/ws"), &vars), None);
        assert_eq!(proxy_for(&url("wss://meridianai.ru/ws"), &vars), None);
        assert!(proxy_for(&url("wss://other.ru/ws"), &vars).is_some());
        let all = env(&[("HTTPS_PROXY", "http://p:1"), ("no_proxy", "*")]);
        assert_eq!(proxy_for(&url("wss://other.ru/ws"), &all), None);
    }

    #[test]
    fn base64_matches_the_standard() {
        assert_eq!(base64(b""), "");
        assert_eq!(base64(b"f"), "Zg==");
        assert_eq!(base64(b"fo"), "Zm8=");
        assert_eq!(base64(b"foo"), "Zm9v");
        assert_eq!(base64(b"user:pass"), "dXNlcjpwYXNz");
    }

    #[tokio::test]
    async fn the_tunnel_asks_the_proxy_with_credentials_and_keeps_the_rest_of_the_stream() {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let port = listener.local_addr().unwrap().port();
        let server = tokio::spawn(async move {
            let (mut socket, _) = listener.accept().await.unwrap();
            let mut head = Vec::new();
            let mut byte = [0u8; 1];
            while !head.ends_with(b"\r\n\r\n") {
                socket.read_exact(&mut byte).await.unwrap();
                head.push(byte[0]);
            }
            // The reply and the tunnel's first bytes arrive together.
            socket
                .write_all(b"HTTP/1.1 200 Connection established\r\n\r\nHELLO")
                .await
                .unwrap();
            String::from_utf8(head).unwrap()
        });
        let proxy = Proxy {
            host: "127.0.0.1".into(),
            port,
            credentials: Some("user:pass".into()),
        };
        let mut stream = tunnel(&proxy, "meridianai.ru", 443).await.unwrap();
        let mut rest = [0u8; 5];
        stream.read_exact(&mut rest).await.unwrap();
        assert_eq!(&rest, b"HELLO");
        let head = server.await.unwrap();
        assert!(head.starts_with("CONNECT meridianai.ru:443 HTTP/1.1\r\n"));
        assert!(head.contains("Proxy-Authorization: Basic dXNlcjpwYXNz\r\n"));
    }

    #[tokio::test]
    async fn a_refusing_proxy_is_an_error() {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let port = listener.local_addr().unwrap().port();
        tokio::spawn(async move {
            let (mut socket, _) = listener.accept().await.unwrap();
            let mut buf = [0u8; 512];
            let _ = socket.read(&mut buf).await;
            let _ = socket
                .write_all(b"HTTP/1.1 407 Proxy Authentication Required\r\n\r\n")
                .await;
        });
        let proxy = Proxy {
            host: "127.0.0.1".into(),
            port,
            credentials: None,
        };
        let error = tunnel(&proxy, "meridianai.ru", 443).await.unwrap_err();
        assert!(error.to_string().contains("407"));
    }
}
