//! The upload of meeting sources against the throwaway server.

use std::path::PathBuf;

use super::tests::{err, fixture, happy, ok, start_mock, Fixture, Reply, Req};
use crate::managers::meeting::MeetingStatus;

fn handler(request: &Req) -> Reply {
    match (request.method.as_str(), request.path.as_str()) {
        ("POST", "/api/desktop/documents/upload-session") => {
            ok(r#"{"document_id":900,"upload_url":"{BASE}/storage/doc-900?X-Amz-Signature=sig"}"#)
        }
        ("PUT", "/storage/doc-900?X-Amz-Signature=sig") => ok("{}"),
        ("POST", "/api/desktop/documents/900/confirm") => ok(r#"{"ok":true}"#),
        _ => happy(request),
    }
}

fn copy_file(fx: &Fixture, name: &str) -> (tempfile::TempDir, PathBuf) {
    let _ = fx;
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join(name);
    std::fs::write(&path, b"%PDF-1.4 test").unwrap();
    (dir, path)
}

fn state_of(
    fx: &Fixture,
    meeting: Option<&str>,
    server: Option<i64>,
) -> Vec<(String, Option<String>)> {
    fx.db
        .list_queued_documents(meeting, server)
        .unwrap()
        .into_iter()
        .map(|d| (d.state, d.error))
        .collect()
}

#[tokio::test]
async fn files_of_a_local_meeting_go_before_the_finalization() {
    let server = start_mock(handler).await;
    let fx = fixture(&server.url);
    fx.add_meeting("m1", MeetingStatus::Stopped, 1);
    let (_dir, path) = copy_file(&fx, "Договор.pdf");
    fx.db
        .insert_document(
            Some("m1"),
            None,
            &path.to_string_lossy(),
            "Договор.pdf",
            13,
            "application/pdf",
            "t",
        )
        .unwrap();

    fx.core.run_pass(false).await;

    let lines = server.lines();
    let at = |line: &str| lines.iter().position(|l| l == line).unwrap();
    assert!(
        at("POST /api/desktop/documents/upload-session")
            < at("PUT /storage/doc-900?X-Amz-Signature=sig")
    );
    assert!(
        at("PUT /storage/doc-900?X-Amz-Signature=sig")
            < at("POST /api/desktop/documents/900/confirm")
    );
    assert!(
        at("POST /api/desktop/documents/900/confirm")
            < at("POST /api/desktop/meetings/42/finalize")
    );

    let requests = server.all();
    let session = requests
        .iter()
        .find(|r| r.path.ends_with("upload-session"))
        .unwrap();
    let body = session.json();
    assert_eq!(body["filename"], "Договор.pdf");
    assert_eq!(body["size"], 13);
    assert_eq!(body["mime_type"], "application/pdf");
    assert_eq!(body["meeting_id"], 42);
    let confirm = requests
        .iter()
        .find(|r| r.path.ends_with("/confirm"))
        .unwrap();
    assert_eq!(confirm.json()["meeting_id"], 42);
    let put = requests
        .iter()
        .find(|r| r.method == "PUT" && r.path.starts_with("/storage"))
        .unwrap();
    assert_eq!(
        put.headers.get("content-type").map(String::as_str),
        Some("application/pdf")
    );
    assert!(!put.headers.contains_key("authorization"));
    assert_eq!(put.body, b"%PDF-1.4 test");

    assert!(
        state_of(&fx, Some("m1"), Some(42)).is_empty(),
        "uploaded rows leave the list"
    );
    assert!(!path.exists(), "the copy is deleted after the upload");
}

#[tokio::test]
async fn files_of_a_meeting_of_the_site_go_without_any_local_meeting() {
    let server = start_mock(handler).await;
    let fx = fixture(&server.url);
    let (_dir, path) = copy_file(&fx, "a.pdf");
    fx.db
        .insert_document(
            None,
            Some(42),
            &path.to_string_lossy(),
            "a.pdf",
            13,
            "application/pdf",
            "t",
        )
        .unwrap();

    fx.core.run_pass(false).await;

    assert_eq!(
        server.lines(),
        [
            "POST /api/desktop/documents/upload-session",
            "PUT /storage/doc-900?X-Amz-Signature=sig",
            "POST /api/desktop/documents/900/confirm",
        ]
    );
}

#[tokio::test]
async fn a_server_without_storage_leaves_the_files_waiting_and_stops_the_pass() {
    let server = start_mock(|r: &Req| {
        if r.path.ends_with("upload-session") {
            err(503, "S3-хранилище не настроено")
        } else {
            happy(r)
        }
    })
    .await;
    let fx = fixture(&server.url);
    let (_dir, path) = copy_file(&fx, "a.pdf");
    for name in ["a.pdf", "b.pdf"] {
        fx.db
            .insert_document(
                None,
                Some(42),
                &path.to_string_lossy(),
                name,
                13,
                "application/pdf",
                "t",
            )
            .unwrap();
    }

    fx.core.run_pass(false).await;

    // The second file is not even tried.
    assert_eq!(server.count(), 1);
    let states = state_of(&fx, None, Some(42));
    assert_eq!(states.len(), 2);
    assert!(states.iter().all(|(state, _)| state == "pending"));
    assert!(states[0].1.as_deref().unwrap().contains("503"));
    assert!(path.exists());
}

#[tokio::test]
async fn a_refusal_is_final_and_does_not_hold_back_the_next_file() {
    let server = start_mock(|r: &Req| {
        if r.path.ends_with("upload-session") && r.json()["filename"] == "bad.pdf" {
            err(422, "файл не принят")
        } else {
            handler(r)
        }
    })
    .await;
    let fx = fixture(&server.url);
    let (_dir, path) = copy_file(&fx, "a.pdf");
    for name in ["bad.pdf", "good.pdf"] {
        fx.db
            .insert_document(
                None,
                Some(42),
                &path.to_string_lossy(),
                name,
                13,
                "application/pdf",
                "t",
            )
            .unwrap();
    }

    fx.core.run_pass(false).await;

    let states = state_of(&fx, None, Some(42));
    assert_eq!(states.len(), 1, "{states:?}");
    assert_eq!(states[0].0, "error");
    assert!(states[0].1.as_deref().unwrap().contains("файл не принят"));
    // An errored row is not retried by later passes.
    server.requests.lock().unwrap().clear();
    fx.core.run_pass(false).await;
    assert_eq!(server.count(), 0);
}

#[tokio::test]
async fn an_upload_cut_by_a_crash_continues_with_the_confirm() {
    let server = start_mock(handler).await;
    let fx = fixture(&server.url);
    let (_dir, path) = copy_file(&fx, "a.pdf");
    let id = fx
        .db
        .insert_document(
            None,
            Some(42),
            &path.to_string_lossy(),
            "a.pdf",
            13,
            "application/pdf",
            "t",
        )
        .unwrap();
    fx.db.claim_document(id).unwrap();
    fx.db.set_document_server_id(id, Some(900)).unwrap();

    fx.core.run_pass(false).await;

    assert_eq!(server.lines(), ["POST /api/desktop/documents/900/confirm"]);
    assert!(state_of(&fx, None, Some(42)).is_empty());
}

#[tokio::test]
async fn a_missing_copy_is_a_final_error() {
    let server = start_mock(handler).await;
    let fx = fixture(&server.url);
    fx.db
        .insert_document(
            None,
            Some(42),
            "/nonexistent/a.pdf",
            "a.pdf",
            13,
            "application/pdf",
            "t",
        )
        .unwrap();

    fx.core.run_pass(false).await;

    assert_eq!(server.count(), 0);
    let states = state_of(&fx, None, Some(42));
    assert_eq!(states[0].0, "error");
}
