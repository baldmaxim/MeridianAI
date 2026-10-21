//! The meeting context goes to the server: with the upsert, and later as a
//! PATCH of the context alone.

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;

use super::tests::{err, fixture, happy, ok, start_mock, Req, Reply};
use crate::managers::meeting::MeetingStatus;

const PATCH_42: &str = "PATCH /api/desktop/meetings/42";

fn context_patches(requests: &[Req]) -> Vec<serde_json::Value> {
    requests
        .iter()
        .filter(|r| r.method == "PATCH" && r.json().get("key_terms").is_some())
        .map(Req::json)
        .collect()
}

#[tokio::test]
async fn upsert_carries_the_context_and_no_extra_patch_follows() {
    let server = start_mock(happy).await;
    let fx = fixture(&server.url);
    fx.add_meeting("m1", MeetingStatus::Stopped, 2);
    fx.db
        .set_meeting_context("m1", Some("price"), Some("срок 3 месяца"), None)
        .unwrap();

    fx.core.run_pass(false).await;

    let requests = server.all();
    let upsert = requests[0].json();
    assert_eq!(requests[0].path, "/api/desktop/meetings");
    assert_eq!(upsert["negotiation_type"], "price");
    assert_eq!(upsert["key_terms"], "срок 3 месяца");
    assert!(upsert["opponent_weaknesses"].is_null());
    // Only the regular details PATCH (title, notes) is there: no context PATCH.
    assert!(context_patches(&requests).is_empty());
    assert!(!fx.db.context_dirty("m1").unwrap());
    assert_eq!(fx.meeting("m1").sync_state, "synced");
}

#[tokio::test]
async fn changed_context_of_a_synced_meeting_is_patched_without_finalizing() {
    let server = start_mock(happy).await;
    let fx = fixture(&server.url);
    fx.add_meeting("m1", MeetingStatus::Stopped, 1);
    fx.core.run_pass(false).await;
    assert_eq!(fx.meeting("m1").sync_state, "synced");
    let before = server.count();

    // One field is filled, one is cleared, one was never set.
    fx.db
        .set_meeting_context("m1", None, Some("новые условия"), None)
        .unwrap();
    assert!(fx.db.context_dirty("m1").unwrap());
    fx.core.run_pass(false).await;

    let requests = server.all();
    let new_requests = &requests[before..];
    assert_eq!(new_requests.len(), 1, "{:?}", server.lines());
    assert_eq!(
        format!("{} {}", new_requests[0].method, new_requests[0].path),
        PATCH_42
    );
    let body = new_requests[0].json();
    assert_eq!(body["negotiation_type"], "");
    assert_eq!(body["key_terms"], "новые условия");
    assert_eq!(body["opponent_weaknesses"], "");
    assert!(body.get("title").is_none() && body.get("notes").is_none());
    assert!(!fx.db.context_dirty("m1").unwrap());
    assert_eq!(fx.meeting("m1").sync_state, "synced");

    // Nothing left to send: the next pass is silent.
    fx.core.run_pass(false).await;
    assert_eq!(server.count(), before + 1);
}

#[tokio::test]
async fn failed_context_patch_keeps_the_flag_and_the_synced_state() {
    let fail = Arc::new(AtomicBool::new(true));
    let switch = Arc::clone(&fail);
    let server = start_mock(move |r| {
        if r.method == "PATCH" && r.json().get("key_terms").is_some_and(|v| v == "срок") {
            return if switch.load(Ordering::SeqCst) {
                err(500, "сбой")
            } else {
                ok(r#"{"meeting_id":42,"title":"t","ended_at":null}"#)
            };
        }
        happy(r)
    })
    .await;
    let fx = fixture(&server.url);
    fx.add_meeting("m1", MeetingStatus::Stopped, 1);
    fx.core.run_pass(false).await;
    fx.db
        .set_meeting_context("m1", None, Some("срок"), None)
        .unwrap();

    fx.core.run_pass(false).await;
    assert_eq!(context_patches(&server.all()).len(), 1);
    assert!(fx.db.context_dirty("m1").unwrap());
    let meeting = fx.meeting("m1");
    assert_eq!(meeting.sync_state, "synced");
    assert!(meeting.sync_error.is_none());
    assert_eq!(
        server
            .lines()
            .iter()
            .filter(|l| l.ends_with("/finalize"))
            .count(),
        1,
        "the context must not trigger finalization again"
    );

    // Waiting time: the next pass does not hit the server again...
    fx.core.run_pass(false).await;
    assert_eq!(context_patches(&server.all()).len(), 1);

    // ...until it is over (or the user asks for a sync) and the server is back.
    fail.store(false, Ordering::SeqCst);
    fx.core.reset_backoff();
    fx.core.run_pass(false).await;
    assert_eq!(context_patches(&server.all()).len(), 2);
    assert!(!fx.db.context_dirty("m1").unwrap());
}

#[tokio::test]
async fn refused_context_patch_does_not_spoil_the_meeting() {
    let server = start_mock(|r| {
        if r.method == "PATCH" && r.json().get("key_terms").is_some() {
            return Reply(404, r#"{"detail":"Встреча не найдена"}"#.to_string());
        }
        happy(r)
    })
    .await;
    let fx = fixture(&server.url);
    fx.add_meeting("m1", MeetingStatus::Stopped, 1);
    fx.core.run_pass(false).await;
    fx.db
        .set_meeting_context("m1", Some("price"), None, None)
        .unwrap();

    fx.core.run_pass(false).await;
    fx.core.run_pass(false).await;

    assert_eq!(context_patches(&server.all()).len(), 1, "no hot loop");
    assert!(fx.db.context_dirty("m1").unwrap());
    let meeting = fx.meeting("m1");
    assert_eq!(meeting.sync_state, "synced");
    assert!(meeting.sync_error.is_none());
}
