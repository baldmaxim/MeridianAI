//! The sync against a throwaway HTTP server on localhost (no real Meridian
//! server, no real storage).

use std::collections::HashMap;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};

use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::TcpListener;

use super::account::{AccountStore, AccountUser, StoredAccount};
use super::{Notice, SyncCore};
use crate::managers::meeting::{
    write_test_audio, CaptureMode, MeetingDb, MeetingInfo, MeetingStatus, Note, Segment,
};
use crate::secrets::testing::{store_with, MemoryBackend};

const TOKEN: &str = "tok-secret-123";
const STARTED: &str = "2026-03-01T10:00:00.000Z";

/* ------------------------------ mock server ------------------------------ */

#[derive(Clone, Debug)]
pub(crate) struct Req {
    pub(crate) method: String,
    pub(crate) path: String,
    pub(crate) headers: HashMap<String, String>,
    pub(crate) body: Vec<u8>,
}

impl Req {
    fn line(&self) -> String {
        format!("{} {}", self.method, self.path)
    }

    pub(crate) fn json(&self) -> serde_json::Value {
        serde_json::from_slice(&self.body).unwrap_or(serde_json::Value::Null)
    }
}

pub(crate) struct Reply(pub(crate) u16, pub(crate) String);

pub(crate) fn ok(body: &str) -> Reply {
    Reply(200, body.to_string())
}

pub(crate) fn err(status: u16, detail: &str) -> Reply {
    Reply(status, format!(r#"{{"detail":"{detail}"}}"#))
}

pub(crate) struct Mock {
    pub(crate) url: String,
    pub(crate) requests: Arc<Mutex<Vec<Req>>>,
}

impl Mock {
    pub(crate) fn lines(&self) -> Vec<String> {
        self.requests
            .lock()
            .unwrap()
            .iter()
            .map(Req::line)
            .collect()
    }

    pub(crate) fn all(&self) -> Vec<Req> {
        self.requests.lock().unwrap().clone()
    }

    pub(crate) fn count(&self) -> usize {
        self.requests.lock().unwrap().len()
    }
}

fn find(haystack: &[u8], needle: &[u8]) -> Option<usize> {
    haystack.windows(needle.len()).position(|w| w == needle)
}

async fn read_request(stream: &mut tokio::net::TcpStream) -> Option<Req> {
    let mut data = Vec::new();
    let mut chunk = [0u8; 16 * 1024];
    let head_end = loop {
        if let Some(pos) = find(&data, b"\r\n\r\n") {
            break pos;
        }
        let n = stream.read(&mut chunk).await.ok()?;
        if n == 0 {
            return None;
        }
        data.extend_from_slice(&chunk[..n]);
    };
    let head = String::from_utf8_lossy(&data[..head_end]).into_owned();
    let mut lines = head.lines();
    let mut first = lines.next()?.split_whitespace();
    let (method, path) = (first.next()?.to_string(), first.next()?.to_string());
    let headers: HashMap<String, String> = lines
        .filter_map(|l| l.split_once(':'))
        .map(|(k, v)| (k.trim().to_lowercase(), v.trim().to_string()))
        .collect();
    let length: usize = headers
        .get("content-length")
        .and_then(|v| v.parse().ok())
        .unwrap_or(0);
    let mut body = data[head_end + 4..].to_vec();
    while body.len() < length {
        let n = stream.read(&mut chunk).await.ok()?;
        if n == 0 {
            break;
        }
        body.extend_from_slice(&chunk[..n]);
    }
    Some(Req {
        method,
        path,
        headers,
        body,
    })
}

/// `{BASE}` in a reply body stands for the server's own address.
pub(crate) async fn start_mock(handler: impl Fn(&Req) -> Reply + Send + Sync + 'static) -> Mock {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let url = format!("http://{}", listener.local_addr().unwrap());
    let requests = Arc::new(Mutex::new(Vec::new()));
    let handler = Arc::new(handler);
    let (log, base) = (Arc::clone(&requests), url.clone());
    tokio::spawn(async move {
        loop {
            let Ok((mut stream, _)) = listener.accept().await else {
                break;
            };
            let (handler, log, base) = (Arc::clone(&handler), Arc::clone(&log), base.clone());
            tokio::spawn(async move {
                let Some(request) = read_request(&mut stream).await else {
                    return;
                };
                let Reply(status, body) = handler(&request);
                log.lock().unwrap().push(request);
                let body = body.replace("{BASE}", &base);
                let response = format!(
                    "HTTP/1.1 {status} X\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
                    body.len()
                );
                let _ = stream.write_all(response.as_bytes()).await;
                let _ = stream.shutdown().await;
            });
        }
    });
    Mock { url, requests }
}

/// A server that accepts everything the way the real one does.
pub(super) fn happy(request: &Req) -> Reply {
    match (request.method.as_str(), request.path.as_str()) {
        ("POST", "/api/desktop/meetings") => ok(r#"{"meeting_id":42,"created":true}"#),
        ("PUT", "/api/desktop/meetings/42/segments") => ok(r#"{"created":1,"updated":0}"#),
        ("PATCH", "/api/desktop/meetings/42") => {
            ok(r#"{"meeting_id":42,"title":"t","ended_at":null}"#)
        }
        ("POST", "/api/desktop/meetings/42/audio-upload") => err(503, "S3-хранилище не настроено"),
        ("POST", "/api/desktop/meetings/42/finalize") => ok(
            r#"{"meeting_id":42,"status":"queued","error":null,"finalized_at":null,"has_protocol":false}"#,
        ),
        _ => err(404, "нет такого адреса"),
    }
}

/* ------------------------------ fixtures ------------------------------ */

pub(super) struct Fixture {
    pub(super) core: SyncCore,
    pub(super) db: Arc<MeetingDb>,
    accounts: Arc<AccountStore>,
    notices: Arc<Mutex<Vec<Notice>>>,
    root: tempfile::TempDir,
    _account_dir: tempfile::TempDir,
}

pub(super) fn fixture(server_url: &str) -> Fixture {
    let db = Arc::new(MeetingDb::open_in_memory().unwrap());
    let account_dir = tempfile::tempdir().unwrap();
    let accounts = Arc::new(AccountStore::open(
        account_dir.path(),
        store_with(&Arc::new(MemoryBackend::default())),
    ));
    accounts
        .save(StoredAccount {
            server_url: server_url.to_string(),
            device_token: TOKEN.to_string(),
            device_id: 3,
            user: AccountUser {
                id: 1,
                email: "a@b.ru".into(),
                display_name: None,
            },
        })
        .unwrap();
    let root = tempfile::tempdir().unwrap();
    let notices = Arc::new(Mutex::new(Vec::new()));
    let sink = Arc::clone(&notices);
    let core = SyncCore::new(
        Arc::clone(&db),
        root.path().to_path_buf(),
        Arc::clone(&accounts),
        Box::new(move |notice| sink.lock().unwrap().push(notice)),
    );
    Fixture {
        core,
        db,
        accounts,
        notices,
        root,
        _account_dir: account_dir,
    }
}

fn meeting(id: &str, status: MeetingStatus) -> MeetingInfo {
    MeetingInfo {
        id: id.to_string(),
        title: "Переговоры".to_string(),
        capture_mode: CaptureMode::Online,
        started_at: STARTED.to_string(),
        ended_at: (status != MeetingStatus::Recording).then(|| "2026-03-01T11:00:00.000Z".into()),
        status,
        duration_seconds: 3600.0,
        server_meeting_id: None,
        sync_state: "pending".to_string(),
        sync_error: None,
        synced_at: None,
        customer_id: None,
        object_id: None,
        customer_name: None,
        object_name: None,
        audio_state: "pending".to_string(),
        negotiation_type: None,
        key_terms: None,
        opponent_weaknesses: None,
        web_url: None,
    }
}

fn segment(meeting: &str, n: usize) -> Segment {
    Segment {
        id: format!("{meeting}-seg{n:04}"),
        meeting_id: meeting.to_string(),
        channel: if n.is_multiple_of(2) { "mic" } else { "system" }.to_string(),
        start_time: n as f64,
        end_time: n as f64 + 0.5,
        text: format!("реплика {n}"),
        created_at: STARTED.to_string(),
        synced: false,
        voice: None,
    }
}

impl Fixture {
    pub(super) fn add_meeting(&self, id: &str, status: MeetingStatus, segments: usize) {
        self.db.insert_meeting(&meeting(id, status)).unwrap();
        for n in 0..segments {
            self.db.insert_segment(&segment(id, n)).unwrap();
        }
    }

    pub(super) fn meeting(&self, id: &str) -> MeetingInfo {
        self.db.get_meeting(id).unwrap().unwrap()
    }

    fn unsynced(&self, id: &str) -> usize {
        self.db.unsynced_segments(id, 10_000).unwrap().len()
    }
}

/* ------------------------------ tests ------------------------------ */

#[tokio::test]
async fn full_pass_without_storage_ends_synced() {
    let server = start_mock(happy).await;
    let fx = fixture(&server.url);
    fx.add_meeting("m1", MeetingStatus::Stopped, 3);
    fx.db
        .upsert_note(&Note {
            id: "n1".into(),
            meeting_id: "m1".into(),
            at_seconds: 12.5,
            text: "Согласовать срок".into(),
            updated_at: STARTED.into(),
        })
        .unwrap();
    write_test_audio(fx.root.path(), "m1", "mic", &[100; 16_000]);

    fx.core.run_pass(true).await;

    assert_eq!(
        server.lines(),
        [
            "POST /api/desktop/meetings",
            "PUT /api/desktop/meetings/42/segments",
            "PATCH /api/desktop/meetings/42",
            "POST /api/desktop/meetings/42/audio-upload",
            "POST /api/desktop/meetings/42/finalize",
        ]
    );
    let requests = server.all();
    let bearer = format!("Bearer {TOKEN}");
    assert!(requests
        .iter()
        .all(|r| r.headers.get("authorization") == Some(&bearer)));

    let create = requests[0].json();
    assert_eq!(create["client_uuid"], "m1");
    assert_eq!(create["started_at"], STARTED);
    assert_eq!(create["capture_mode"], "online");

    let segments = requests[1].json();
    let first = &segments["segments"][0];
    assert_eq!(first["client_segment_id"], "m1-seg0000");
    assert_eq!(first["channel"], "mic");
    assert_eq!(first["wall_clock"], "2026-03-01T10:00:00.000Z");
    assert_eq!(
        segments["segments"][1]["wall_clock"],
        "2026-03-01T10:00:01.000Z"
    );

    let patch = requests[2].json();
    assert_eq!(patch["title"], "Переговоры");
    assert_eq!(patch["ended_at"], "2026-03-01T11:00:00.000Z");
    assert_eq!(patch["notes"][0]["at_seconds"], 12.5);
    assert_eq!(patch["notes"][0]["text"], "Согласовать срок");

    let audio = requests[3].json();
    assert_eq!(audio["filename"], "mic.wav");
    assert_eq!(audio["channel"], "mic");
    assert_eq!(audio["size"], 44 + 32_000);

    let done = fx.meeting("m1");
    assert_eq!(done.sync_state, "synced");
    assert!(done.synced_at.is_some());
    assert_eq!(done.sync_error, None);
    assert_eq!(done.server_meeting_id, Some(42));
    assert_eq!(done.audio_state, "no_storage");
    assert_eq!(fx.unsynced("m1"), 0);
    assert!(
        !fx.root.path().join("m1").join("mic.wav").exists(),
        "the temporary WAV is removed"
    );

    let status = fx.core.status();
    assert!(status.online && !status.running);
    assert_eq!(status.pending_count, 0);
    assert!(status.last_sync_at.is_some() && status.last_error.is_none());

    // A synced meeting is not sent again.
    fx.core.run_pass(true).await;
    assert_eq!(server.count(), 5);
}

#[tokio::test]
async fn audio_is_streamed_to_the_storage_and_confirmed() {
    let server = start_mock(|r| match (r.method.as_str(), r.path.as_str()) {
        ("POST", "/api/desktop/meetings/42/audio-upload") => {
            ok(r#"{"file_id":9,"upload_url":"{BASE}/storage/mic.wav?sig=abc","status":"pending"}"#)
        }
        ("PUT", "/storage/mic.wav?sig=abc") => Reply(200, String::new()),
        ("POST", "/api/desktop/meetings/42/audio-confirm/9") => {
            ok(r#"{"file_id":9,"status":"active","size":32044}"#)
        }
        _ => happy(r),
    })
    .await;
    let fx = fixture(&server.url);
    fx.add_meeting("m1", MeetingStatus::Interrupted, 1);
    write_test_audio(fx.root.path(), "m1", "mic", &[7; 16_000]);

    fx.core.run_pass(true).await;

    let requests = server.all();
    let upload = requests
        .iter()
        .find(|r| r.method == "PUT" && r.path.starts_with("/storage/"))
        .expect("the file was uploaded");
    assert_eq!(upload.body.len(), 44 + 32_000);
    assert_eq!(&upload.body[..4], b"RIFF");
    assert_eq!(upload.headers["content-type"], "audio/wav");
    assert_eq!(upload.headers["content-length"], (44 + 32_000).to_string());
    assert!(!upload.headers.contains_key("transfer-encoding"));
    assert!(
        !upload.headers.contains_key("authorization"),
        "the token must not go to the storage"
    );
    assert!(server
        .lines()
        .contains(&"POST /api/desktop/meetings/42/audio-confirm/9".to_string()));

    let done = fx.meeting("m1");
    assert_eq!(done.sync_state, "synced");
    assert_eq!(done.audio_state, "done");
    assert_eq!(fx.db.audio_done_channels("m1").unwrap(), ["mic"]);
}

#[tokio::test]
async fn audio_is_left_alone_when_switched_off() {
    let server = start_mock(happy).await;
    let fx = fixture(&server.url);
    fx.add_meeting("m1", MeetingStatus::Stopped, 1);
    write_test_audio(fx.root.path(), "m1", "mic", &[7; 1600]);

    fx.core.run_pass(false).await;

    assert!(!server.lines().iter().any(|l| l.contains("audio")));
    let done = fx.meeting("m1");
    assert_eq!(done.sync_state, "synced");
    assert_eq!(done.audio_state, "pending");
}

#[tokio::test]
async fn interrupted_pass_does_not_resend_confirmed_segments() {
    let segment_calls = Arc::new(AtomicUsize::new(0));
    let calls = Arc::clone(&segment_calls);
    let server = start_mock(move |r| {
        if r.method == "PUT" && r.path.ends_with("/segments") {
            // The connection "drops" on the second batch of the first pass.
            if calls.fetch_add(1, Ordering::SeqCst) == 1 {
                return err(502, "Bad gateway");
            }
        }
        happy(r)
    })
    .await;
    let fx = fixture(&server.url);
    fx.add_meeting("m1", MeetingStatus::Stopped, 501);

    fx.core.run_pass(true).await;

    let cut = fx.meeting("m1");
    assert_eq!(cut.sync_state, "pending");
    assert!(
        cut.sync_error.as_deref().unwrap().contains("502"),
        "{:?}",
        cut.sync_error
    );
    assert_eq!(cut.server_meeting_id, Some(42));
    assert_eq!(fx.unsynced("m1"), 1, "the first batch of 500 is confirmed");
    assert!(fx.core.status().online, "the server answered");

    // The wait before the next attempt is respected...
    let before = server.count();
    fx.core.run_pass(true).await;
    assert_eq!(server.count(), before);

    // ...until the user asks for a sync right now.
    fx.core.reset_backoff();
    fx.core.run_pass(true).await;

    let batches: Vec<usize> = server
        .all()
        .iter()
        .filter(|r| r.method == "PUT")
        .map(|r| r.json()["segments"].as_array().unwrap().len())
        .collect();
    assert_eq!(batches, [500, 1, 1], "only the unsent segment goes again");
    let creates = server
        .lines()
        .iter()
        .filter(|l| *l == "POST /api/desktop/meetings")
        .count();
    assert_eq!(creates, 1, "the meeting is not created twice");
    let done = fx.meeting("m1");
    assert_eq!(done.sync_state, "synced");
    assert_eq!(done.sync_error, None);
    assert_eq!(fx.unsynced("m1"), 0);
}

#[tokio::test]
async fn unauthorized_signs_the_account_out() {
    let server = start_mock(|_| err(401, "Токен устройства не принят")).await;
    let fx = fixture(&server.url);
    fx.add_meeting("m1", MeetingStatus::Stopped, 1);
    fx.add_meeting("m2", MeetingStatus::Stopped, 1);

    fx.core.run_pass(true).await;

    assert!(fx.accounts.get().is_none());
    assert_eq!(server.count(), 1, "the pass stops at the first 401");
    let told_about_sign_out = fx.notices.lock().unwrap().iter().any(|n| {
        matches!(
            n,
            Notice::Account(changed) if changed.account.is_none() && changed.reason.is_some()
        )
    });
    assert!(told_about_sign_out);
    // The meeting stays in the queue for after the next sign-in.
    let waiting = fx.meeting("m1");
    assert_eq!(waiting.sync_state, "pending");
    assert!(waiting.sync_error.is_some());

    // Signed out: no more requests.
    fx.core.reset_backoff();
    fx.core.run_pass(true).await;
    assert_eq!(server.count(), 1);
}

#[tokio::test]
async fn conflict_is_an_error_that_is_not_retried_by_itself() {
    let server = start_mock(|r| {
        if r.method == "PUT" && r.path.ends_with("/segments") {
            return err(409, "Встреча уже финализирована");
        }
        happy(r)
    })
    .await;
    let fx = fixture(&server.url);
    fx.add_meeting("m1", MeetingStatus::Stopped, 2);

    fx.core.run_pass(true).await;

    let failed = fx.meeting("m1");
    assert_eq!(failed.sync_state, "error");
    let text = failed.sync_error.unwrap();
    assert!(
        text.contains("409") && text.contains("финализирована"),
        "{text}"
    );
    assert_eq!(fx.core.status().pending_count, 0);

    let before = server.count();
    fx.core.reset_backoff();
    fx.core.run_pass(true).await;
    assert_eq!(server.count(), before, "no automatic retry");

    // The "retry" button puts it back in the queue.
    fx.core.retry_meeting("m1").unwrap();
    let again = fx.meeting("m1");
    assert_eq!(
        (again.sync_state.as_str(), again.sync_error),
        ("pending", None)
    );
    fx.core.run_pass(true).await;
    assert!(server.count() > before);
    assert_eq!(fx.meeting("m1").sync_state, "error");

    assert!(fx.core.retry_meeting("nope").is_err());
}

#[tokio::test]
async fn no_connection_keeps_the_meeting_pending_with_a_reason() {
    // A port nobody listens on.
    let url = {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        format!("http://{}", listener.local_addr().unwrap())
    };
    let fx = fixture(&url);
    fx.add_meeting("m1", MeetingStatus::Stopped, 1);

    fx.core.run_pass(true).await;

    let waiting = fx.meeting("m1");
    assert_eq!(waiting.sync_state, "pending");
    assert_eq!(waiting.sync_error.as_deref(), Some("Нет связи с сервером"));
    let status = fx.core.status();
    assert!(!status.online);
    assert_eq!(status.pending_count, 1);
    assert_eq!(status.last_error.as_deref(), Some("Нет связи с сервером"));
}

#[tokio::test]
async fn recording_meetings_and_signed_out_state_send_nothing() {
    let server = start_mock(happy).await;
    let fx = fixture(&server.url);
    fx.add_meeting("live", MeetingStatus::Recording, 2);
    fx.core.run_pass(true).await;
    assert_eq!(server.count(), 0);

    fx.add_meeting("m1", MeetingStatus::Stopped, 1);
    fx.accounts.clear();
    fx.core.run_pass(true).await;
    assert_eq!(server.count(), 0);
}

#[test]
fn retry_delay_doubles_up_to_fifteen_minutes() {
    use std::time::Duration;
    let secs: Vec<u64> = (1..=8).map(|n| super::retry_delay(n).as_secs()).collect();
    assert_eq!(secs, [30, 60, 120, 240, 480, 900, 900, 900]);
    assert_eq!(super::retry_delay(0), Duration::from_secs(30));
    assert_eq!(super::retry_delay(u32::MAX), Duration::from_secs(900));
}
