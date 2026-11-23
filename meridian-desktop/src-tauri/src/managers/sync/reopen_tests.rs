//! A synced meeting that is continued: the server takes it back, the audio goes
//! again under a new name, and the finalization is repeated.

use chrono::{SecondsFormat, Utc};

use super::engine::audio_filename;
use super::tests::{err, fixture, happy, ok, start_mock, Reply};
use super::{ApiClient, ApiError};
use crate::managers::meeting::{
    resume_blocker_for_tests as plain, resume_blocker_reopened_for_tests as reopened,
    write_test_audio, MeetingStatus,
};

#[test]
fn audio_name_changes_with_the_revision_only_after_the_first() {
    assert_eq!(audio_filename("mic", 1), "mic.wav");
    assert_eq!(audio_filename("mic", 0), "mic.wav");
    assert_eq!(audio_filename("system", 2), "system_r2.wav");
    assert_eq!(audio_filename("mixed", 7), "mixed_r7.wav");
}

#[test]
fn a_synced_meeting_is_continued_only_after_the_server_took_it_back() {
    let fx = fixture("http://127.0.0.1:1");
    fx.add_meeting("m1", MeetingStatus::Stopped, 1);
    // Not sent yet: no reopening needed.
    assert_eq!(plain(&fx.meeting("m1")), None);
    assert_eq!(reopened(&fx.meeting("m1")), None);

    fx.db.set_server_meeting_id("m1", 42).unwrap();
    fx.db
        .set_sync_state("m1", "synced", None, Some("2026-03-01T12:00:00.000Z"))
        .unwrap();
    assert!(plain(&fx.meeting("m1")).is_some());
    assert_eq!(reopened(&fx.meeting("m1")), None);

    // Never without the server's number: there is nothing to reopen.
    let mut nameless = fx.meeting("m1");
    nameless.server_meeting_id = None;
    assert!(plain(&nameless).is_some());
    assert!(reopened(&nameless).is_some());

    // A meeting that records right now cannot be continued at all.
    let mut recording = fx.meeting("m1");
    recording.status = MeetingStatus::Recording;
    assert!(plain(&recording).is_some());
    assert!(reopened(&recording).is_some());
}

#[tokio::test]
async fn reopen_asks_the_server_and_passes_on_its_refusal() {
    let busy = start_mock(|r| match r.path.as_str() {
        "/api/desktop/meetings/42/reopen" => err(
            409,
            "Встреча ещё обрабатывается на сервере, попробуйте через минуту",
        ),
        "/api/desktop/meetings/43/reopen" => ok(r#"{"ok":true}"#),
        _ => err(404, "нет такого адреса"),
    })
    .await;
    let client = ApiClient::new(&busy.url, Some("token"));

    client.reopen_meeting(43).await.unwrap();
    assert!(busy
        .lines()
        .contains(&"POST /api/desktop/meetings/43/reopen".to_string()));

    // The server's own words, without the code and a prefix.
    let Err(ApiError::Rejected { status, message }) = client.reopen_meeting(42).await else {
        panic!("a busy meeting must be refused");
    };
    assert_eq!(status, 409);
    assert_eq!(
        message,
        "Встреча ещё обрабатывается на сервере, попробуйте через минуту"
    );
    // Other refusals keep the usual form.
    assert!(matches!(
        client.reopen_meeting(1).await,
        Err(ApiError::Rejected { status: 404, .. })
    ));
}

#[tokio::test]
async fn offer_submission_goes_alone_with_an_explicit_null() {
    let server = start_mock(|r| match (r.method.as_str(), r.path.as_str()) {
        ("PATCH", "/api/desktop/meetings/42") => {
            ok(r#"{"meeting_id":42,"title":"t","ended_at":null}"#)
        }
        _ => err(404, "нет такого адреса"),
    })
    .await;
    let client = ApiClient::new(&server.url, Some("token"));
    client
        .set_offer_submission(42, Some("2026-10-01"))
        .await
        .unwrap();
    client.set_offer_submission(42, None).await.unwrap();
    let bodies: Vec<_> = server.all().iter().map(|r| r.json()).collect();
    assert_eq!(
        bodies[0],
        serde_json::json!({"offer_submission": "2026-10-01"})
    );
    assert_eq!(bodies[1], serde_json::json!({"offer_submission": null}));
}

/// A server with working audio storage that remembers the names it was given.
fn server_with_storage(request: &super::tests::Req) -> Reply {
    match (request.method.as_str(), request.path.as_str()) {
        ("POST", "/api/desktop/meetings/42/audio-upload") => {
            ok(r#"{"file_id":9,"upload_url":"{BASE}/storage/a?sig=abc","status":"pending"}"#)
        }
        ("PUT", "/storage/a?sig=abc") => Reply(200, String::new()),
        ("POST", "/api/desktop/meetings/42/audio-confirm/9") => {
            ok(r#"{"file_id":9,"status":"active","size":1}"#)
        }
        _ => happy(request),
    }
}

#[tokio::test]
async fn a_continued_meeting_sends_all_its_audio_again_under_a_new_name() {
    let server = start_mock(server_with_storage).await;
    let fx = fixture(&server.url);
    fx.add_meeting("m1", MeetingStatus::Stopped, 2);
    write_test_audio(fx.root_path(), "m1", "mic", &[7; 16_000]);

    fx.core.run_pass(true).await;
    assert_eq!(fx.meeting("m1").sync_state, "synced");
    assert_eq!(fx.db.audio_done_channels("m1").unwrap(), ["mic"]);

    // Continue: the server took it back, recording starts and the queue gets it.
    fx.db.mark_recording_reopened("m1").unwrap();
    fx.core.run_pass(true).await;
    // Recording: nothing is sent until the next stop.
    let uploads = |server: &super::tests::Mock| -> Vec<String> {
        server
            .all()
            .iter()
            .filter(|r| r.path.ends_with("/audio-upload"))
            .map(|r| r.json()["filename"].as_str().unwrap().to_string())
            .collect()
    };
    assert_eq!(uploads(&server), ["mic.wav"]);

    write_test_audio(fx.root_path(), "m1", "mic", &[9; 16_000]);
    let ended = Utc::now().to_rfc3339_opts(SecondsFormat::Millis, true);
    fx.db
        .finish_meeting("m1", MeetingStatus::Stopped, &ended, 120.0)
        .unwrap();
    fx.core.release("m1");
    fx.core.run_pass(true).await;

    assert_eq!(uploads(&server), ["mic.wav", "mic_r2.wav"]);
    let finalizes = server
        .lines()
        .iter()
        .filter(|l| l.ends_with("/finalize"))
        .count();
    assert_eq!(finalizes, 2);
    let done = fx.meeting("m1");
    assert_eq!(done.sync_state, "synced");
    assert_eq!(done.audio_state, "done");
    assert_eq!(fx.db.audio_revision("m1").unwrap(), 2);
}
