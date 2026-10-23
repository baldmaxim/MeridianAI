//! HTTP client of the Meridian server's `/api/desktop` API. Every call is a
//! plain request; retries and ordering belong to the engine.

mod documents;
mod library;

pub use documents::{DocumentUploadBody, ServerDocument};

use std::fmt;
use std::io::Read;
use std::path::Path;
use std::time::Duration;

use reqwest::header::{AUTHORIZATION, CONTENT_LENGTH, CONTENT_TYPE};
use reqwest::{Body, Client, RequestBuilder, Response, StatusCode};
use serde::de::DeserializeOwned;
use serde::{Deserialize, Serialize};

use super::account::{app_version, join_url};

const CONNECT_TIMEOUT: Duration = Duration::from_secs(10);
const REQUEST_TIMEOUT: Duration = Duration::from_secs(60);
/// Uploads have no overall limit (hours of audio on a slow line), only this
/// silence limit.
const UPLOAD_READ_TIMEOUT: Duration = Duration::from_secs(120);
const UPLOAD_CHUNK: usize = 256 * 1024;

/// Why a request did not go through. Messages are for the user, in Russian,
/// and never carry the token or a signed URL.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ApiError {
    /// No connection, a timeout, a server error (5xx) or "too many requests":
    /// worth another try later. `status` is set when the server answered.
    Retry {
        status: Option<u16>,
        message: String,
    },
    /// 401: the device token is not accepted any more.
    Unauthorized,
    /// The server refused the request (400, 403, 404, 409, 422, ...): retrying
    /// the same request will not help.
    Rejected { status: u16, message: String },
    /// A local problem (the audio file, the disk).
    Local(String),
}

impl fmt::Display for ApiError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Retry { message, .. } | Self::Rejected { message, .. } | Self::Local(message) => {
                f.write_str(message)
            }
            Self::Unauthorized => f.write_str("Сессия на сервере завершена: войдите заново"),
        }
    }
}

impl ApiError {
    /// The reason a sign-in failed, as shown on the login screen.
    pub fn login_message(&self) -> String {
        match self {
            Self::Unauthorized => "Неверный логин или пароль".to_string(),
            Self::Rejected { status: 403, .. } => "Пользователь отключён".to_string(),
            Self::Retry {
                status: Some(429), ..
            } => "Слишком много попыток входа: подождите минуту".to_string(),
            other => other.to_string(),
        }
    }
}

#[derive(Serialize)]
pub struct LoginBody<'a> {
    pub email: &'a str,
    pub password: &'a str,
    pub device_name: &'a str,
    pub platform: &'a str,
    pub app_version: &'a str,
}

#[derive(Deserialize)]
pub struct LoginUser {
    pub id: i64,
    pub email: String,
    pub display_name: Option<String>,
}

#[derive(Deserialize)]
pub struct LoginResponse {
    pub device_token: String,
    pub device_id: i64,
    pub user: LoginUser,
}

#[derive(Serialize)]
pub struct MeetingBody<'a> {
    pub client_uuid: &'a str,
    pub title: &'a str,
    pub started_at: &'a str,
    pub ended_at: Option<&'a str>,
    pub capture_mode: &'a str,
    pub customer_id: Option<i64>,
    pub object_id: Option<i64>,
    /// The meeting context; `None`: the server leaves it as it is.
    pub negotiation_type: Option<&'a str>,
    pub key_terms: Option<&'a str>,
    pub opponent_weaknesses: Option<&'a str>,
}

#[derive(Deserialize)]
pub struct MeetingResponse {
    pub meeting_id: i64,
}

#[derive(Serialize)]
pub struct SegmentBody {
    pub client_segment_id: String,
    pub text: String,
    pub start_time: f64,
    pub end_time: f64,
    pub wall_clock: Option<String>,
    pub channel: String,
    /// "Голос N" when the phrase's voice is known.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub speaker_label: Option<String>,
}

/// The side of a voice: `self`, `opponent`, or `None` to clear it.
#[derive(Serialize)]
pub struct SpeakerRoleBody<'a> {
    pub side: Option<&'a str>,
    pub display_name: Option<&'a str>,
}

#[derive(Serialize)]
pub struct NoteBody {
    pub at_seconds: f64,
    pub text: String,
}

#[derive(Serialize)]
pub struct PatchBody<'a> {
    pub title: &'a str,
    pub ended_at: Option<&'a str>,
    pub notes: Vec<NoteBody>,
}

/// Only the context: the server reads an empty string as "clear the field".
#[derive(Serialize)]
pub struct ContextPatchBody<'a> {
    pub negotiation_type: &'a str,
    pub key_terms: &'a str,
    pub opponent_weaknesses: &'a str,
}

#[derive(Serialize)]
pub struct AudioUploadBody<'a> {
    pub filename: &'a str,
    pub size: u64,
    pub channel: &'a str,
}

#[derive(Deserialize)]
pub struct AudioUploadResponse {
    pub file_id: i64,
    /// `None`: the file is on the server already.
    pub upload_url: Option<String>,
}

pub struct ApiClient {
    http: Client,
    upload: Client,
    server_url: String,
    token: Option<String>,
}

impl fmt::Debug for ApiClient {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("ApiClient")
            .field("server_url", &self.server_url)
            .field("token", &self.token.as_ref().map(|_| "***"))
            .finish()
    }
}

fn build_client(read_timeout: bool) -> Client {
    let mut builder = Client::builder()
        .connect_timeout(CONNECT_TIMEOUT)
        .user_agent(format!("MeridianDesktop/{}", app_version()));
    builder = if read_timeout {
        builder.read_timeout(UPLOAD_READ_TIMEOUT)
    } else {
        builder.timeout(REQUEST_TIMEOUT)
    };
    // The test server is on localhost; a proxy from the environment would
    // swallow those requests.
    #[cfg(test)]
    let builder = builder.no_proxy();
    builder.build().unwrap_or_default()
}

fn network_error(e: reqwest::Error) -> ApiError {
    // `without_url`: a signed upload URL must not end up in messages or logs.
    let e = e.without_url();
    let message = if e.is_timeout() {
        "Сервер не ответил вовремя".to_string()
    } else if e.is_connect() {
        "Нет связи с сервером".to_string()
    } else {
        format!("Ошибка сети: {e}")
    };
    ApiError::Retry {
        status: None,
        message,
    }
}

/// The server's `detail` (a string, or the first message of a validation list).
fn error_detail(body: &str) -> String {
    let value: Option<serde_json::Value> = serde_json::from_str(body).ok();
    let detail = value.as_ref().and_then(|v| v.get("detail"));
    let text = match detail {
        Some(serde_json::Value::String(s)) => s.clone(),
        Some(serde_json::Value::Array(items)) => items
            .first()
            .and_then(|item| item.get("msg"))
            .and_then(|m| m.as_str())
            .unwrap_or("неверные данные")
            .to_string(),
        _ => String::new(),
    };
    text.chars().take(300).collect()
}

async fn error_from(response: Response) -> ApiError {
    let status = response.status();
    let body = response.text().await.unwrap_or_default();
    let detail = error_detail(&body);
    let with_detail = |prefix: &str| {
        if detail.is_empty() {
            format!("{prefix} (код {})", status.as_u16())
        } else {
            format!("{prefix} (код {}): {detail}", status.as_u16())
        }
    };
    if status == StatusCode::UNAUTHORIZED {
        ApiError::Unauthorized
    } else if status.is_server_error() {
        ApiError::Retry {
            status: Some(status.as_u16()),
            message: with_detail("Сервер временно недоступен"),
        }
    } else if status == StatusCode::TOO_MANY_REQUESTS {
        ApiError::Retry {
            status: Some(429),
            message: with_detail("Слишком много запросов, повторим позже"),
        }
    } else {
        ApiError::Rejected {
            status: status.as_u16(),
            message: with_detail("Сервер отклонил запрос"),
        }
    }
}

async fn send(request: RequestBuilder) -> Result<Response, ApiError> {
    let response = request.send().await.map_err(network_error)?;
    if response.status().is_success() {
        Ok(response)
    } else {
        Err(error_from(response).await)
    }
}

async fn send_json<T: DeserializeOwned>(request: RequestBuilder) -> Result<T, ApiError> {
    send(request)
        .await?
        .json::<T>()
        .await
        .map_err(|e| ApiError::Retry {
            status: None,
            message: format!("Непонятный ответ сервера: {}", e.without_url()),
        })
}

impl ApiClient {
    pub fn new(server_url: &str, token: Option<&str>) -> Self {
        Self {
            http: build_client(false),
            upload: build_client(true),
            server_url: server_url.trim_end_matches('/').to_string(),
            token: token.map(str::to_string),
        }
    }

    fn url(&self, path: &str) -> String {
        join_url(
            &self.server_url,
            &format!("api/desktop/{}", path.trim_start_matches('/')),
        )
    }

    fn authorized(&self, request: RequestBuilder) -> RequestBuilder {
        match &self.token {
            Some(token) => request.header(AUTHORIZATION, format!("Bearer {token}")),
            None => request,
        }
    }

    pub async fn login(&self, body: &LoginBody<'_>) -> Result<LoginResponse, ApiError> {
        send_json(self.http.post(self.url("login")).json(body)).await
    }

    pub async fn logout(&self) -> Result<(), ApiError> {
        send(self.authorized(self.http.post(self.url("logout")))).await?;
        Ok(())
    }

    pub async fn upsert_meeting(
        &self,
        body: &MeetingBody<'_>,
    ) -> Result<MeetingResponse, ApiError> {
        send_json(self.authorized(self.http.post(self.url("meetings")).json(body))).await
    }

    pub async fn put_segments(
        &self,
        meeting_id: i64,
        segments: &[SegmentBody],
    ) -> Result<(), ApiError> {
        let body = serde_json::json!({ "segments": segments });
        let url = self.url(&format!("meetings/{meeting_id}/segments"));
        send(self.authorized(self.http.put(url).json(&body))).await?;
        Ok(())
    }

    pub async fn patch_meeting(
        &self,
        meeting_id: i64,
        body: &PatchBody<'_>,
    ) -> Result<(), ApiError> {
        let url = self.url(&format!("meetings/{meeting_id}"));
        send(self.authorized(self.http.patch(url).json(body))).await?;
        Ok(())
    }

    pub async fn patch_context(
        &self,
        meeting_id: i64,
        body: &ContextPatchBody<'_>,
    ) -> Result<(), ApiError> {
        let url = self.url(&format!("meetings/{meeting_id}"));
        send(self.authorized(self.http.patch(url).json(body))).await?;
        Ok(())
    }

    /// Sets the side of one voice of the meeting. The label goes into the
    /// path, percent-encoded.
    pub async fn put_speaker_role(
        &self,
        meeting_id: i64,
        label: &str,
        side: Option<&str>,
    ) -> Result<(), ApiError> {
        let mut url =
            reqwest::Url::parse(&self.url(&format!("meetings/{meeting_id}/speaker-roles")))
                .map_err(|e| ApiError::Local(format!("Неверный адрес сервера: {e}")))?;
        url.path_segments_mut()
            .map_err(|_| ApiError::Local("Неверный адрес сервера".to_string()))?
            .push(label);
        let body = SpeakerRoleBody {
            side,
            display_name: None,
        };
        send(self.authorized(self.http.put(url).json(&body))).await?;
        Ok(())
    }

    pub async fn audio_upload(
        &self,
        meeting_id: i64,
        body: &AudioUploadBody<'_>,
    ) -> Result<AudioUploadResponse, ApiError> {
        let url = self.url(&format!("meetings/{meeting_id}/audio-upload"));
        send_json(self.authorized(self.http.post(url).json(body))).await
    }

    /// Sends the file to the presigned URL, reading it piece by piece. The
    /// storage is not the Meridian API: whatever it answers (even 401/403) is
    /// a reason to try again with a fresh URL, not to sign out.
    pub async fn put_file(
        &self,
        upload_url: &str,
        path: &Path,
        size: u64,
        content_type: &str,
    ) -> Result<(), ApiError> {
        let file = std::fs::File::open(path)
            .map_err(|e| ApiError::Local(format!("Не удалось открыть файл: {e}")))?;
        let request = self
            .upload
            .put(upload_url)
            .header(CONTENT_TYPE, content_type)
            .header(CONTENT_LENGTH, size)
            .body(file_body(file));
        let response = request.send().await.map_err(network_error)?;
        let status = response.status();
        if status.is_success() {
            return Ok(());
        }
        Err(ApiError::Retry {
            status: Some(status.as_u16()),
            message: format!("Хранилище не приняло файл (код {})", status.as_u16()),
        })
    }

    pub async fn audio_confirm(&self, meeting_id: i64, file_id: i64) -> Result<(), ApiError> {
        let url = self.url(&format!("meetings/{meeting_id}/audio-confirm/{file_id}"));
        match send(self.authorized(self.http.post(url))).await {
            // The object is not in the storage (yet): upload again.
            Err(ApiError::Rejected { status: 400, .. }) => Err(ApiError::Retry {
                status: Some(400),
                message: "Звук не найден в хранилище, загрузим заново".to_string(),
            }),
            other => other.map(|_| ()),
        }
    }

    pub async fn finalize(&self, meeting_id: i64) -> Result<(), ApiError> {
        let url = self.url(&format!("meetings/{meeting_id}/finalize"));
        send(self.authorized(self.http.post(url))).await?;
        Ok(())
    }
}

/// A request body that reads the file in pieces on the blocking pool.
fn file_body(file: std::fs::File) -> Body {
    let stream = futures_util::stream::unfold(Some(file), |state| async move {
        let mut file = state?;
        let read = tokio::task::spawn_blocking(move || {
            let mut buf = vec![0u8; UPLOAD_CHUNK];
            let read = file.read(&mut buf);
            read.map(|n| {
                buf.truncate(n);
                (file, buf)
            })
        })
        .await;
        match read {
            Ok(Ok((_, buf))) if buf.is_empty() => None,
            Ok(Ok((file, buf))) => Some((Ok::<_, std::io::Error>(buf), Some(file))),
            Ok(Err(e)) => Some((Err(e), None)),
            Err(e) => Some((Err(std::io::Error::other(e.to_string())), None)),
        }
    });
    Body::wrap_stream(stream)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn debug_hides_the_token() {
        let client = ApiClient::new("https://meridianai.ru", Some("secret-device-token"));
        let text = format!("{client:?}");
        assert!(!text.contains("secret-device-token"), "{text}");
    }

    #[test]
    fn detail_is_taken_from_string_and_validation_list() {
        assert_eq!(
            error_detail(r#"{"detail":"Встреча не найдена"}"#),
            "Встреча не найдена"
        );
        assert_eq!(
            error_detail(r#"{"detail":[{"msg":"field required","loc":["body"]}]}"#),
            "field required"
        );
        assert_eq!(error_detail("<html>"), "");
    }

    #[test]
    fn urls_have_no_double_slashes() {
        let client = ApiClient::new("https://a.ru/", None);
        assert_eq!(client.url("/meetings"), "https://a.ru/api/desktop/meetings");
    }
}
