//! The «Расшифровка файлов» queue against the throwaway server.

use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;

use super::tests::{err, fixture, ok, start_mock, Fixture, Reply, Req};
use crate::managers::meeting::{TR_ERROR, TR_QUEUED};

const TR_DONE: &str = "done";
const TR_PROCESSING: &str = "processing";

const SESSION: &str = "POST /api/desktop/transcriptions/upload-session";
const PUT: &str = "PUT /storage/tr-5?X-Amz-Signature=sig";
const CONFIRM: &str = "POST /api/desktop/transcriptions/5/confirm";
const GET: &str = "GET /api/desktop/transcriptions/77";

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
    assert_eq!(server.lines(), [SESSION, PUT, CONFIRM, GET]);
    let requests = server.all();
    let body = requests[0].json();
    assert_eq!(body["filename"], "a.mp3");
    assert_eq!(body["size"], 11);
    let put = &requests[1];
    assert_eq!(put.body, b"audio-bytes");
    assert!(!put.headers.contains_key("authorization"));
    assert_eq!(status_of(&fx, &id), TR_PROCESSING);
    assert!(!path.exists(), "the copy is deleted after the confirm");

    // The next pass only asks for the job.
    fx.core.run_pass(false).await;
    assert_eq!(server.lines()[4..], [GET]);
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

    // Done: nothing more is asked.
    let before = server.lines().len();
    fx.core.run_pass(false).await;
    assert_eq!(server.lines().len(), before);
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

    assert_eq!(server.lines(), [CONFIRM, GET]);
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
