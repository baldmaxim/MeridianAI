//! "Continue in the app" for a meeting the app has no copy of: the server hands
//! it over, a local shell is made, and the audio goes under a name the server
//! does not hold.

use chrono::{SecondsFormat, Utc};

use super::engine::audio_filename;
use super::reopen_tests::server_with_storage;
use super::tests::{err, fixture, ok, start_mock};
use super::{ApiClient, ApiError};
use crate::managers::meeting::{write_test_audio, AdoptedMeeting, MeetingStatus};

fn adopted(client_uuid: &str, next_audio_revision: u32) -> AdoptedMeeting {
    AdoptedMeeting {
        client_uuid: client_uuid.to_string(),
        server_meeting_id: 77,
        title: Some("С сайта".to_string()),
        capture_mode: "online".to_string(),
        customer_id: Some(5),
        object_id: Some(6),
        customer_name: Some("Заказчик".to_string()),
        object_name: Some("Объект".to_string()),
        max_speakers: Some(3),
        negotiation_type: Some("price".to_string()),
        key_terms: Some("срок 3 месяца".to_string()),
        opponent_weaknesses: Some("затягивает оплату".to_string()),
        next_audio_revision,
    }
}

#[tokio::test]
async fn adopt_sends_a_new_id_and_reads_the_answer() {
    let server = start_mock(|r| match r.path.as_str() {
        "/api/desktop/meetings/77/adopt" => ok(
            r#"{"client_uuid":"old-id","server_meeting_id":77,"title":null,
                "started_at":"2026-10-21T09:00:00","customer_id":null,"object_id":null,
                "customer_name":null,"object_name":null,"capture_mode":"online",
                "max_speakers":null,"next_audio_revision":3}"#,
        ),
        "/api/desktop/meetings/78/adopt" => err(
            409,
            "Встреча ещё обрабатывается на сервере, попробуйте через минуту",
        ),
        _ => err(404, "нет такого адреса"),
    })
    .await;
    let client = ApiClient::new(&server.url, Some("token"));

    let answer = client
        .adopt_meeting(77, "new-id", "in_person")
        .await
        .unwrap();
    // The server keeps the link it already has: its id wins.
    assert_eq!(answer.client_uuid, "old-id");
    assert_eq!(answer.next_audio_revision, 3);
    assert_eq!(answer.title, None);
    assert_eq!(
        server.all()[0].json(),
        serde_json::json!({"client_uuid": "new-id", "capture_mode": "in_person"})
    );

    assert!(matches!(
        client.adopt_meeting(78, "x", "in_person").await,
        Err(ApiError::Rejected { status: 409, .. })
    ));
    assert!(matches!(
        client.adopt_meeting(1, "x", "in_person").await,
        Err(ApiError::Rejected { status: 404, .. })
    ));
}

#[test]
fn a_new_shell_is_stopped_synced_and_starts_at_the_server_revision() {
    let fx = fixture("http://127.0.0.1:1");
    fx.db
        .register_adopted(&adopted("a1", 3), "2026-11-23T10:00:00.000Z")
        .unwrap();

    let shell = fx.meeting("a1");
    assert_eq!(shell.status, MeetingStatus::Stopped);
    assert_eq!(shell.sync_state, "synced");
    assert_eq!(shell.server_meeting_id, Some(77));
    assert_eq!(shell.title, "С сайта");
    assert_eq!(shell.started_at, "2026-11-23T10:00:00.000Z");
    assert_eq!(shell.customer_name.as_deref(), Some("Заказчик"));
    assert_eq!(shell.max_speakers, Some(3));
    // The context of the server is the local one, and nothing is "to be sent".
    assert_eq!(shell.negotiation_type.as_deref(), Some("price"));
    assert_eq!(shell.key_terms.as_deref(), Some("срок 3 месяца"));
    assert_eq!(
        shell.opponent_weaknesses.as_deref(),
        Some("затягивает оплату")
    );
    assert!(!fx.db.context_dirty("a1").unwrap());
    assert_eq!(fx.db.audio_revision("a1").unwrap(), 3);

    // Continuing it keeps the revision: nothing of ours was sent before.
    fx.db.mark_recording_reopened("a1").unwrap();
    assert_eq!(fx.db.audio_revision("a1").unwrap(), 3);
    assert_eq!(audio_filename("mic", 3), "mic_r3.wav");

    // Nothing on the server: the first name is free.
    fx.db
        .register_adopted(&adopted("a2", 1), "2026-11-23T10:00:00.000Z")
        .unwrap();
    assert_eq!(fx.db.audio_revision("a2").unwrap(), 1);
    assert_eq!(audio_filename("mic", 1), "mic.wav");
}

#[test]
fn a_local_copy_with_that_id_is_kept_and_only_its_revision_is_raised() {
    let fx = fixture("http://127.0.0.1:1");
    fx.add_meeting("m1", MeetingStatus::Stopped, 2);
    fx.db.add_audio_done_channel("m1", "mic").unwrap();
    fx.db
        .register_adopted(&adopted("m1", 4), "2026-11-23T10:00:00.000Z")
        .unwrap();

    let kept = fx.meeting("m1");
    assert_ne!(kept.title, "С сайта");
    // Its own context stays as it was, the server's is not laid over it.
    assert!(kept.negotiation_type.is_none() && kept.key_terms.is_none());
    assert_eq!(kept.server_meeting_id, Some(77));
    assert_eq!(fx.db.list_meetings().unwrap().len(), 1);

    // The reopening adds one for the channel already sent: it lands on 4.
    fx.db.mark_recording_reopened("m1").unwrap();
    assert_eq!(fx.db.audio_revision("m1").unwrap(), 4);

    // A higher local revision is never lowered.
    fx.db
        .register_adopted(&adopted("m1", 2), "2026-11-23T10:00:00.000Z")
        .unwrap();
    assert_eq!(fx.db.audio_revision("m1").unwrap(), 4);
}

#[tokio::test]
async fn an_adopted_meeting_is_sent_under_the_new_revision_without_touching_the_rest() {
    let server = start_mock(server_with_storage).await;
    let fx = fixture(&server.url);
    let mut meeting = adopted("a1", 3);
    meeting.server_meeting_id = 42;
    fx.db
        .register_adopted(&meeting, "2026-11-23T10:00:00.000Z")
        .unwrap();

    // The server has reopened it already; recording starts and ends.
    fx.db.mark_recording_reopened("a1").unwrap();
    write_test_audio(fx.root_path(), "a1", "mic", &[7; 16_000]);
    let ended = Utc::now().to_rfc3339_opts(SecondsFormat::Millis, true);
    fx.db
        .finish_meeting("a1", MeetingStatus::Stopped, &ended, 5.0)
        .unwrap();
    fx.core.release("a1");
    fx.core.run_pass(true).await;

    let requests = server.all();
    let uploads: Vec<String> = requests
        .iter()
        .filter(|r| r.path.ends_with("/audio-upload"))
        .map(|r| r.json()["filename"].as_str().unwrap().to_string())
        .collect();
    assert_eq!(uploads, ["mic_r3.wav"]);
    // The server knows the meeting: no second one is created from the shell.
    assert!(!requests
        .iter()
        .any(|r| r.method == "POST" && r.path == "/api/desktop/meetings"));
    // The context of the site is not cleared by an empty one of the shell.
    assert!(requests
        .iter()
        .filter(|r| r.method == "PATCH")
        .all(|r| r.json().get("negotiation_type").is_none()));
    assert_eq!(fx.meeting("a1").sync_state, "synced");
}

#[tokio::test]
async fn editing_one_context_field_sends_the_others_from_the_server() {
    let server = start_mock(server_with_storage).await;
    let fx = fixture(&server.url);
    let mut meeting = adopted("a1", 1);
    meeting.server_meeting_id = 42;
    fx.db
        .register_adopted(&meeting, "2026-11-23T10:00:00.000Z")
        .unwrap();

    // The user changes the key terms only; the screen hands back the rest as it
    // got it from the local meeting.
    let local = fx.meeting("a1");
    fx.db
        .set_meeting_context(
            "a1",
            local.negotiation_type.as_deref(),
            Some("срок 2 месяца"),
            local.opponent_weaknesses.as_deref(),
        )
        .unwrap();
    fx.core.run_pass(false).await;

    let patches: Vec<serde_json::Value> = server
        .all()
        .iter()
        .filter(|r| r.method == "PATCH")
        .map(|r| r.json())
        .collect();
    assert_eq!(
        patches,
        [serde_json::json!({
            "negotiation_type": "price",
            "key_terms": "срок 2 месяца",
            "opponent_weaknesses": "затягивает оплату",
        })]
    );
}

#[tokio::test]
async fn a_meeting_without_a_title_stays_so_and_sends_none() {
    let server = start_mock(server_with_storage).await;
    let fx = fixture(&server.url);
    let mut meeting = adopted("a1", 1);
    meeting.server_meeting_id = 42;
    meeting.title = Some("  ".to_string());
    fx.db
        .register_adopted(&meeting, "2026-11-23T10:00:00.000Z")
        .unwrap();
    assert_eq!(fx.meeting("a1").title, "");

    fx.db.mark_recording_reopened("a1").unwrap();
    write_test_audio(fx.root_path(), "a1", "mic", &[7; 16_000]);
    let ended = Utc::now().to_rfc3339_opts(SecondsFormat::Millis, true);
    fx.db
        .finish_meeting("a1", MeetingStatus::Stopped, &ended, 5.0)
        .unwrap();
    fx.core.release("a1");
    fx.core.run_pass(true).await;

    let requests = server.all();
    let details: Vec<_> = requests.iter().filter(|r| r.method == "PATCH").collect();
    assert_eq!(details.len(), 1, "{:?}", server.lines());
    assert!(details[0].json().get("title").is_none());
    assert!(details[0].json().get("notes").is_some());
}
