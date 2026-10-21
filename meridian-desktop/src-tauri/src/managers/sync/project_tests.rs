//! The meeting's project goes to the server with the meeting.

use std::sync::Arc;

use super::client::ApiClient;
use super::engine::{Engine, Outcome};
use super::tests::{err, ok, start_mock};
use crate::managers::meeting::{CaptureMode, MeetingDb, MeetingInfo, MeetingStatus, Segment};

fn meeting(customer: Option<i64>, object: Option<i64>) -> MeetingInfo {
    MeetingInfo {
        id: "m1".to_string(),
        title: "Приёмка".to_string(),
        capture_mode: CaptureMode::InPerson,
        started_at: "2026-03-01T10:00:00.000Z".to_string(),
        ended_at: Some("2026-03-01T11:00:00.000Z".to_string()),
        status: MeetingStatus::Stopped,
        duration_seconds: 3600.0,
        server_meeting_id: None,
        sync_state: "pending".to_string(),
        sync_error: None,
        synced_at: None,
        customer_id: customer,
        object_id: object,
        customer_name: customer.map(|_| "Заказчик".to_string()),
        object_name: object.map(|_| "Объект".to_string()),
        audio_state: "none".to_string(),
        negotiation_type: None,
        key_terms: None,
        opponent_weaknesses: None,
        web_url: None,
    }
}

async fn upsert_body(customer: Option<i64>, object: Option<i64>) -> serde_json::Value {
    let mock = start_mock(|r| match (r.method.as_str(), r.path.as_str()) {
        ("POST", "/api/desktop/meetings") => ok(r#"{"meeting_id":42,"created":true}"#),
        ("PUT", "/api/desktop/meetings/42/segments") => ok(r#"{"created":1,"updated":0}"#),
        ("PATCH", "/api/desktop/meetings/42") => {
            ok(r#"{"meeting_id":42,"title":"t","ended_at":null}"#)
        }
        ("POST", "/api/desktop/meetings/42/finalize") => ok(
            r#"{"meeting_id":42,"status":"queued","error":null,"finalized_at":null,"has_protocol":false}"#,
        ),
        _ => err(404, "нет"),
    })
    .await;
    let db = Arc::new(MeetingDb::open_in_memory().unwrap());
    db.insert_meeting(&meeting(customer, object)).unwrap();
    db.insert_segment(&Segment {
        id: "s1".into(),
        meeting_id: "m1".into(),
        channel: "mixed".into(),
        start_time: 0.0,
        end_time: 1.0,
        text: "текст".into(),
        created_at: "2026-03-01T10:00:00.000Z".into(),
        synced: false,
        voice: None,
    })
    .unwrap();
    let client = ApiClient::new(&mock.url, Some("tok"));
    let root = tempfile::tempdir().unwrap();
    let engine = Engine {
        db: &db,
        root: root.path(),
        client: &client,
        upload_audio: false,
    };
    assert_eq!(engine.sync_meeting("m1").await, Outcome::Synced);
    mock.all()[0].json()
}

#[tokio::test]
async fn project_ids_go_into_the_upsert() {
    let body = upsert_body(Some(3), Some(5)).await;
    assert_eq!(body["customer_id"], 3);
    assert_eq!(body["object_id"], 5);
}

#[tokio::test]
async fn no_project_goes_as_null() {
    let body = upsert_body(None, None).await;
    assert!(body["customer_id"].is_null());
    assert!(body["object_id"].is_null());
}
