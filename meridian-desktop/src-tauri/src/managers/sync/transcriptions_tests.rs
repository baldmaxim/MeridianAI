//! The «Расшифровка файлов» queue against the throwaway server.

use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};

use super::tests::{err, fixture as fixture_without_pull, ok, start_mock, Fixture, Reply, Req};
use crate::managers::meeting::{TR_ERROR, TR_QUEUED};

const TR_DONE: &str = "done";
const TR_PROCESSING: &str = "processing";

/// Like the common one, but the list of the server's files is due, as at the start.
fn fixture(server_url: &str) -> Fixture {
    let fx = fixture_without_pull(server_url);
    fx.core.inner().last_pull = None;
    fx
}

const SESSION: &str = "POST /api/desktop/transcriptions/upload-session";
const PUT: &str = "PUT /storage/tr-5?X-Amz-Signature=sig";
const CONFIRM: &str = "POST /api/desktop/transcriptions/5/confirm";
const GET: &str = "GET /api/desktop/transcriptions/77";
const LIST: &str = "GET /api/desktop/transcriptions";

fn session() -> Reply {
    ok(r#"{"file_id":5,"upload_url":"{BASE}/storage/tr-5?X-Amz-Signature=sig"}"#)
}

fn job(status: &str) -> Reply {
    ok(&format!(
        r#"{{"id":77,"status":"{status}","original_filename":"a.mp3","error_message":null}}"#
    ))
}

fn queue_file(fx: &Fixture) -> (tempfile::TempDir, PathBuf, String) {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("a.mp3");
    std::fs::write(&path, b"audio-bytes").unwrap();
    let id = "t1".to_string();
    fx.db
        .insert_transcription(&id, "a.mp3", &path.to_string_lossy(), 11, TR_QUEUED, None)
        .unwrap();
    (dir, path, id)
}

fn status_of(fx: &Fixture, id: &str) -> String {
    fx.db.get_transcription_item(id).unwrap().unwrap().status
}

#[tokio::test]
async fn a_file_goes_up_is_confirmed_and_then_polled_until_done() {
    let done = Arc::new(AtomicBool::new(false));
    let flag = Arc::clone(&done);
    let server = start_mock(move |r: &Req| match format!("{} {}", r.method, r.path).as_str() {
        SESSION => session(),
        PUT => ok("{}"),
        CONFIRM => job("uploaded"),
        GET if flag.load(Ordering::SeqCst) => ok(
            r#"{"id":77,"status":"done","transcription_text":"Привет. Ответ.",
                "segments":[{"speaker":"speaker_0","start":0.0,"end":1.2,"text":"Привет.","text_ru":null,"corrections":[]},
                            {"speaker":"speaker_1","start":1.5,"end":2.5,"text":"Ответ."}]}"#,
        ),
        GET => job("transcribing"),
        _ => err(404, "нет такого адреса"),
    })
    .await;
    let fx = fixture(&server.url);
    let (_dir, path, id) = queue_file(&fx);

    fx.core.run_pass(false).await;

    // The job is asked for in the same pass.
    assert_eq!(server.lines(), [SESSION, PUT, CONFIRM, LIST, GET]);
    let requests = server.all();
    let body = requests[0].json();
    assert_eq!(body["filename"], "a.mp3");
    assert_eq!(body["size"], 11);
    let put = &requests[1];
    assert_eq!(put.body, b"audio-bytes");
    assert!(!put.headers.contains_key("authorization"));
    assert_eq!(status_of(&fx, &id), TR_PROCESSING);
    assert!(!path.exists(), "the copy is deleted after the confirm");

    // The next pass asks for the job only: the list was read a moment ago.
    fx.core.run_pass(false).await;
    assert_eq!(server.lines()[5..], [GET]);
    assert_eq!(
        fx.db
            .get_transcription_item(&id)
            .unwrap()
            .unwrap()
            .server_status
            .as_deref(),
        Some("transcribing")
    );

    done.store(true, Ordering::SeqCst);
    fx.core.run_pass(false).await;
    let detail = fx.db.get_transcription_detail(&id).unwrap().unwrap();
    assert_eq!(detail.item.status, TR_DONE);
    assert_eq!(detail.text, "Привет. Ответ.");
    assert_eq!(detail.segments.len(), 2);
    assert_eq!(detail.segments[1].speaker, "speaker_1");
    assert!((detail.segments[1].start - 1.5).abs() < f64::EPSILON);

    // Done: nothing more is asked while the list is not due.
    let before = server.lines().len();
    fx.core.run_pass(false).await;
    assert_eq!(server.lines().len(), before);
}

#[tokio::test]
async fn an_empty_queue_asks_for_the_list_only_when_due() {
    let server = start_mock(
        |r: &Req| match format!("{} {}", r.method, r.path).as_str() {
            LIST => ok("[]"),
            _ => err(404, "нет"),
        },
    )
    .await;
    let fx = fixture(&server.url);

    // At the start the list is due.
    fx.core.run_pass(false).await;
    assert_eq!(server.lines(), [LIST]);

    // Read a moment ago: nothing is asked.
    fx.core.run_pass(false).await;
    assert_eq!(server.lines(), [LIST]);

    // `sync_now` asks at once.
    fx.core.reset_backoff();
    fx.core.run_pass(false).await;
    assert_eq!(server.lines(), [LIST, LIST]);

    // Five minutes later it is due again.
    fx.core.inner().last_pull = Instant::now().checked_sub(Duration::from_secs(6 * 60));
    fx.core.run_pass(false).await;
    assert_eq!(server.lines().len(), 3);
    fx.core.run_pass(false).await;
    assert_eq!(server.lines().len(), 3);
}

#[tokio::test]
async fn a_list_that_failed_to_load_stays_due() {
    // A port nobody listens on.
    let fx = fixture("http://127.0.0.1:9");
    fx.core.run_pass(false).await;
    assert!(fx.core.pull_due());

    // An old server without the list answers 404: not asked again at once.
    let server = start_mock(|_: &Req| err(404, "нет")).await;
    let fx = fixture(&server.url);
    fx.core.run_pass(false).await;
    assert_eq!(server.lines(), [LIST]);
    assert!(!fx.core.pull_due());
}

#[tokio::test]
async fn a_server_without_storage_leaves_the_file_queued() {
    let server = start_mock(|r: &Req| {
        if r.path.ends_with("upload-session") {
            err(503, "S3-хранилище не настроено")
        } else {
            err(404, "нет")
        }
    })
    .await;
    let fx = fixture(&server.url);
    let (_dir, path, id) = queue_file(&fx);

    fx.core.run_pass(false).await;

    assert_eq!(status_of(&fx, &id), TR_QUEUED);
    assert!(path.exists());
    let item = fx.db.get_transcription_item(&id).unwrap().unwrap();
    assert!(item.error.is_some());
}

#[tokio::test]
async fn a_refused_file_gets_the_servers_message() {
    let server = start_mock(|r: &Req| {
        if r.path.ends_with("upload-session") {
            err(400, "Формат не поддерживается")
        } else {
            err(404, "нет")
        }
    })
    .await;
    let fx = fixture(&server.url);
    let (_dir, _path, id) = queue_file(&fx);

    fx.core.run_pass(false).await;

    let item = fx.db.get_transcription_item(&id).unwrap().unwrap();
    assert_eq!(item.status, TR_ERROR);
    assert!(item.error.unwrap().contains("Формат не поддерживается"));
}

#[tokio::test]
async fn a_crash_after_the_upload_resumes_with_the_confirm() {
    let server = start_mock(
        |r: &Req| match format!("{} {}", r.method, r.path).as_str() {
            CONFIRM => job("uploaded"),
            GET => job("transcribing"),
            _ => err(404, "нет"),
        },
    )
    .await;
    let fx = fixture(&server.url);
    let (_dir, _path, id) = queue_file(&fx);
    fx.db.claim_transcription(&id).unwrap();
    fx.db.set_transcription_file(&id, Some(5), true).unwrap();

    fx.core.run_pass(false).await;

    assert_eq!(server.lines(), [CONFIRM, LIST, GET]);
    assert_eq!(status_of(&fx, &id), TR_PROCESSING);
}

#[tokio::test]
async fn a_failed_job_shows_the_servers_error() {
    let server = start_mock(
        |r: &Req| match format!("{} {}", r.method, r.path).as_str() {
            GET => ok(r#"{"id":77,"status":"error","error_message":"Речь не найдена"}"#),
            _ => err(404, "нет"),
        },
    )
    .await;
    let fx = fixture(&server.url);
    let (_dir, _path, id) = queue_file(&fx);
    fx.db.claim_transcription(&id).unwrap();
    fx.db
        .mark_transcription_confirmed(&id, 77, "uploaded")
        .unwrap();

    fx.core.run_pass(false).await;

    let item = fx.db.get_transcription_item(&id).unwrap().unwrap();
    assert_eq!(item.status, TR_ERROR);
    assert_eq!(item.error.as_deref(), Some("Речь не найдена"));
}

#[tokio::test]
async fn without_a_connection_the_rows_stay_as_they_are() {
    // A port nobody listens on.
    let fx = fixture("http://127.0.0.1:9");
    let (_dir, path, id) = queue_file(&fx);

    fx.core.run_pass(false).await;

    assert_eq!(status_of(&fx, &id), TR_QUEUED);
    assert!(path.exists());
}

#[tokio::test]
async fn files_of_the_site_and_other_pcs_are_pulled_into_the_list() {
    let server = start_mock(
        |r: &Req| match format!("{} {}", r.method, r.path).as_str() {
            LIST => ok(
                r#"[{"id":90,"status":"transcribing","original_filename":"c.mp3","original_size":300,
                     "created_at":"2026-11-03T10:00:00.123456","updated_at":"2026-11-03T10:00:00"},
                    {"id":77,"status":"done","original_filename":"a.mp3","original_size":11,
                     "created_at":"2026-11-02T10:00:00","updated_at":"2026-11-02T10:00:00"},
                    {"id":80,"status":"done","original_filename":"b.mp3","original_size":200,
                     "created_at":"2026-11-01T10:00:00","updated_at":"2026-11-01T10:00:00"},
                    {"id":81,"status":"error","original_filename":"d.mp3","original_size":5,
                     "error_message":null,"created_at":"2026-10-31T10:00:00","updated_at":"2026-10-31T10:00:00"}]"#,
            ),
            "GET /api/desktop/transcriptions/80" => ok(
                r#"{"id":80,"status":"done","transcription_text":"С сайта",
                    "segments":[{"speaker":"speaker_0","start":0.0,"end":1.0,"text":"С сайта"}]}"#,
            ),
            "GET /api/desktop/transcriptions/90" => job("transcribing"),
            GET => job("transcribing"),
            _ => err(404, "нет"),
        },
    )
    .await;
    let fx = fixture(&server.url);
    // The row of the job 77 is the PC's own; an active row opens the pass.
    let (_dir, _path, id) = queue_file(&fx);
    fx.db.claim_transcription(&id).unwrap();
    fx.db
        .mark_transcription_confirmed(&id, 77, "uploaded")
        .unwrap();
    // A job removed here before: it must not come back.
    fx.db
        .insert_server_transcription(
            81,
            "d.mp3",
            5,
            TR_ERROR,
            "error",
            None,
            "2026-10-31T10:00:00",
        )
        .unwrap();
    let hidden = fx
        .db
        .list_transcriptions()
        .unwrap()
        .into_iter()
        .find(|i| i.filename == "d.mp3")
        .unwrap();
    fx.db.remove_transcription(&hidden.id).unwrap();

    fx.core.run_pass(false).await;

    let items = fx.db.list_transcriptions().unwrap();
    // Newest first: the own file (made now), then the server's by their times.
    assert_eq!(
        items
            .iter()
            .map(|i| i.filename.as_str())
            .collect::<Vec<_>>(),
        ["a.mp3", "c.mp3", "b.mp3"]
    );
    let b = items.iter().find(|i| i.filename == "b.mp3").unwrap();
    assert_eq!((b.status.as_str(), b.size), (TR_DONE, 200));
    let detail = fx.db.get_transcription_detail(&b.id).unwrap().unwrap();
    assert_eq!(detail.text, "С сайта");
    let c = items.iter().find(|i| i.filename == "c.mp3").unwrap();
    assert_eq!(c.status, TR_PROCESSING);
    assert_eq!(c.server_status.as_deref(), Some("transcribing"));
    assert_eq!(c.created_at, "2026-11-03T10:00:00.123Z");
    assert!(
        !items.iter().any(|i| i.filename == "d.mp3"),
        "a removed job stays hidden"
    );
    assert!(!server
        .lines()
        .contains(&"GET /api/desktop/transcriptions/81".to_string()));
}

/// A finished row as an older version left it: no protocol asked for.
fn old_done_row(fx: &Fixture, id: &str, job_id: i64) {
    fx.db
        .insert_transcription(id, "a.mp3", "", 11, TR_QUEUED, None)
        .unwrap();
    fx.db.claim_transcription(id).unwrap();
    fx.db
        .mark_transcription_confirmed(id, job_id, "uploaded")
        .unwrap();
    fx.db
        .finish_transcription(
            id,
            "done",
            &crate::managers::meeting::StoredTranscript::default(),
        )
        .unwrap();
}

#[tokio::test]
async fn the_protocol_of_a_done_job_reaches_the_detail() {
    let server = start_mock(
        |r: &Req| match format!("{} {}", r.method, r.path).as_str() {
            GET => ok(r##"{"id":77,"status":"done","transcription_text":"Привет",
                    "protocol_markdown":"# Протокол\n- [00:12] решили"}"##),
            _ => err(404, "нет"),
        },
    )
    .await;
    let fx = fixture(&server.url);
    let (_dir, _path, id) = queue_file(&fx);
    fx.db.claim_transcription(&id).unwrap();
    fx.db
        .mark_transcription_confirmed(&id, 77, "uploaded")
        .unwrap();

    fx.core.run_pass(false).await;

    let detail = fx.db.get_transcription_detail(&id).unwrap().unwrap();
    assert_eq!(detail.item.status, TR_DONE);
    assert_eq!(
        detail.protocol_markdown.as_deref(),
        Some("# Протокол\n- [00:12] решили")
    );
    // The protocol came with the job: nothing is asked again.
    assert!(fx.db.transcriptions_without_protocol().unwrap().is_empty());
}

#[tokio::test]
async fn a_done_row_without_a_protocol_is_asked_once() {
    let server = start_mock(
        |r: &Req| match format!("{} {}", r.method, r.path).as_str() {
            LIST => ok("[]"),
            GET => ok(r##"{"id":77,"status":"done","protocol_markdown":"# П"}"##),
            _ => err(404, "нет"),
        },
    )
    .await;
    let fx = fixture(&server.url);
    old_done_row(&fx, "old", 77);
    assert_eq!(fx.db.transcriptions_without_protocol().unwrap().len(), 1);

    fx.core.run_pass(false).await;
    assert_eq!(server.lines(), [LIST, GET]);
    let detail = fx.db.get_transcription_detail("old").unwrap().unwrap();
    assert_eq!(detail.protocol_markdown.as_deref(), Some("# П"));
    // The transcript and the status stay as they were.
    assert_eq!(detail.item.status, TR_DONE);

    // Once: the next pass with the list due again asks for the list only.
    fx.core.inner().last_pull = None;
    fx.core.run_pass(false).await;
    assert_eq!(server.lines(), [LIST, GET, LIST]);
}

#[tokio::test]
async fn a_null_protocol_is_kept_as_empty_and_not_asked_again() {
    let server = start_mock(
        |r: &Req| match format!("{} {}", r.method, r.path).as_str() {
            LIST => ok("[]"),
            GET => ok(r#"{"id":77,"status":"done","protocol_markdown":null}"#),
            _ => err(404, "нет"),
        },
    )
    .await;
    let fx = fixture(&server.url);
    old_done_row(&fx, "old", 77);

    fx.core.run_pass(false).await;
    assert_eq!(server.lines(), [LIST, GET]);
    let detail = fx.db.get_transcription_detail("old").unwrap().unwrap();
    assert_eq!(detail.protocol_markdown, None);
    assert!(fx.db.transcriptions_without_protocol().unwrap().is_empty());

    fx.core.inner().last_pull = None;
    fx.core.run_pass(false).await;
    assert_eq!(server.lines(), [LIST, GET, LIST]);
}

#[tokio::test]
async fn a_refused_backfill_is_not_repeated() {
    let server = start_mock(
        |r: &Req| match format!("{} {}", r.method, r.path).as_str() {
            LIST => ok("[]"),
            _ => err(404, "нет"),
        },
    )
    .await;
    let fx = fixture(&server.url);
    old_done_row(&fx, "old", 77);

    fx.core.run_pass(false).await;
    assert!(fx.db.transcriptions_without_protocol().unwrap().is_empty());
    assert_eq!(server.lines(), [LIST, GET]);
}

#[tokio::test]
async fn hidden_rows_are_not_backfilled() {
    let server = start_mock(|_: &Req| err(404, "нет")).await;
    let fx = fixture(&server.url);
    old_done_row(&fx, "old", 77);
    fx.db.remove_transcription("old").unwrap();
    assert!(fx.db.transcriptions_without_protocol().unwrap().is_empty());

    fx.core.run_pass(false).await;
    assert!(!server.lines().contains(&GET.to_string()));
}

#[tokio::test]
async fn without_a_connection_the_backfill_stays_for_later() {
    // A port nobody listens on.
    let fx = fixture("http://127.0.0.1:9");
    old_done_row(&fx, "old", 77);

    fx.core.run_pass(false).await;

    assert_eq!(fx.db.transcriptions_without_protocol().unwrap().len(), 1);
    let detail = fx.db.get_transcription_detail("old").unwrap().unwrap();
    assert_eq!(detail.protocol_markdown, None);
}
