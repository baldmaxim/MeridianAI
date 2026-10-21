//! The sides of the voices go to the server: with the main pass, and later,
//! alone, for a meeting that is synced already.

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;

use super::tests::{err, fixture, happy, ok, start_mock, Req};
use crate::managers::meeting::voice::VoiceCentroid;
use crate::managers::meeting::MeetingStatus;

/// "Голос 1", percent-encoded as it goes in the path.
const ROLE_1: &str =
    "PUT /api/desktop/meetings/42/speaker-roles/%D0%93%D0%BE%D0%BB%D0%BE%D1%81%201";

fn roles(requests: &[Req]) -> Vec<Req> {
    requests
        .iter()
        .filter(|r| r.path.contains("/speaker-roles/"))
        .cloned()
        .collect()
}

fn voice(label: &str) -> VoiceCentroid {
    VoiceCentroid {
        label: label.to_string(),
        vector: vec![1.0, 0.0],
        count: 1,
    }
}

fn with_roles(request: &Req) -> super::tests::Reply {
    if request.method == "PUT" && request.path.contains("/speaker-roles/") {
        return ok(r#"{"ok":true}"#);
    }
    happy(request)
}

#[tokio::test]
async fn sides_go_after_the_segments_with_the_voice_of_each_segment() {
    let server = start_mock(with_roles).await;
    let fx = fixture(&server.url);
    fx.add_meeting("m1", MeetingStatus::Stopped, 0);
    let mut spoken = fx.db.list_segments("m1").unwrap();
    assert!(spoken.is_empty());
    for (n, label) in [(0, Some("Голос 1")), (1, None)] {
        spoken.push(crate::managers::meeting::Segment {
            id: format!("s{n}"),
            meeting_id: "m1".into(),
            channel: "system".into(),
            start_time: n as f64,
            end_time: n as f64 + 1.0,
            text: format!("фраза {n}"),
            created_at: "2026-03-01T10:00:00.000Z".into(),
            synced: false,
            voice: label.map(str::to_string),
        });
    }
    for segment in &spoken {
        fx.db.insert_segment(segment).unwrap();
    }
    fx.db
        .insert_voice("m1", &voice("Голос 1"), Some("opponent"), "system", 1)
        .unwrap();
    fx.db
        .insert_voice("m1", &voice("Голос 2"), None, "mic", 2)
        .unwrap();

    fx.core.run_pass(false).await;

    let lines = server.lines();
    let at = |line: &str| lines.iter().position(|l| l == line).unwrap();
    assert!(
        at("PUT /api/desktop/meetings/42/segments") < at(ROLE_1),
        "{lines:?}"
    );
    assert!(
        at(ROLE_1) < at("POST /api/desktop/meetings/42/finalize"),
        "{lines:?}"
    );
    let requests = server.all();
    let sent = roles(&requests);
    assert_eq!(
        sent.len(),
        1,
        "a voice without a side is not sent: {lines:?}"
    );
    assert_eq!(
        sent[0].json(),
        serde_json::json!({"side": "opponent", "display_name": null})
    );
    assert_eq!(
        sent[0].headers.get("content-type").map(String::as_str),
        Some("application/json")
    );

    let segments = requests
        .iter()
        .find(|r| r.path.ends_with("/segments"))
        .unwrap()
        .json();
    assert_eq!(segments["segments"][0]["speaker_label"], "Голос 1");
    assert!(segments["segments"][1].get("speaker_label").is_none());
    assert!(fx.db.unsynced_voices("m1").unwrap().is_empty());
    assert_eq!(fx.meeting("m1").sync_state, "synced");
}

#[tokio::test]
async fn a_changed_side_of_a_synced_meeting_is_put_alone_and_retried_on_failure() {
    let fail = Arc::new(AtomicBool::new(true));
    let switch = Arc::clone(&fail);
    let server = start_mock(move |r| {
        if r.method == "PUT" && r.path.contains("/speaker-roles/") {
            return if switch.load(Ordering::SeqCst) {
                err(500, "сбой")
            } else {
                ok(r#"{"ok":true}"#)
            };
        }
        happy(r)
    })
    .await;
    let fx = fixture(&server.url);
    fx.add_meeting("m1", MeetingStatus::Stopped, 1);
    fx.db
        .insert_voice("m1", &voice("Голос 1"), None, "mixed", 1)
        .unwrap();
    fx.core.run_pass(false).await;
    assert_eq!(fx.meeting("m1").sync_state, "synced");
    let before = server.count();

    // The user says it is us: only this goes, the meeting is not finalized again.
    fx.db.set_voice_side("m1", "Голос 1", Some("self")).unwrap();
    fx.core.run_pass(false).await;
    let requests = server.all();
    assert_eq!(roles(&requests[before..]).len(), 1);
    assert_eq!(requests.len(), before + 1, "{:?}", server.lines());
    assert_eq!(
        fx.db.unsynced_voices("m1").unwrap().len(),
        1,
        "failed: stays unsynced"
    );
    assert_eq!(fx.meeting("m1").sync_state, "synced");

    // Waiting time: no hot loop.
    fx.core.run_pass(false).await;
    assert_eq!(server.count(), before + 1);

    fail.store(false, Ordering::SeqCst);
    fx.core.reset_backoff();
    fx.core.run_pass(false).await;
    assert_eq!(roles(&server.all()[before..]).len(), 2);
    assert!(fx.db.unsynced_voices("m1").unwrap().is_empty());
    let last = roles(&server.all()).pop().unwrap();
    assert_eq!(last.json()["side"], "self");

    // Cleared again: null goes.
    fx.db.set_voice_side("m1", "Голос 1", None).unwrap();
    fx.core.run_pass(false).await;
    let last = roles(&server.all()).pop().unwrap();
    assert!(last.json()["side"].is_null());
}
