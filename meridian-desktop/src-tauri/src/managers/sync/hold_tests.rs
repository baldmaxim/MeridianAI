//! An interrupted meeting is held back: its text goes, its finalization waits.

use chrono::{Duration, SecondsFormat, Utc};

use super::tests::{fixture, happy, start_mock, Fixture};
use crate::managers::meeting::{write_test_audio, MeetingStatus};

/// An interrupted meeting whose last audio was `ago` ago.
fn interrupted(fx: &Fixture, ago: Duration) {
    fx.add_meeting("m1", MeetingStatus::Interrupted, 2);
    let ended = (Utc::now() - ago).to_rfc3339_opts(SecondsFormat::Millis, true);
    fx.db
        .finish_meeting("m1", MeetingStatus::Interrupted, &ended, 60.0)
        .unwrap();
    write_test_audio(fx.root_path(), "m1", "mic", &[5; 1600]);
}

fn has(lines: &[String], part: &str) -> bool {
    lines.iter().any(|l| l.contains(part))
}

#[tokio::test]
async fn a_fresh_interrupted_meeting_sends_text_but_is_not_finalized() {
    let server = start_mock(happy).await;
    let fx = fixture(&server.url);
    interrupted(&fx, Duration::minutes(5));

    fx.core.run_pass(true).await;

    let lines = server.lines();
    assert!(
        has(&lines, "PUT /api/desktop/meetings/42/segments"),
        "{lines:?}"
    );
    assert!(!has(&lines, "finalize"), "{lines:?}");
    assert!(!has(&lines, "audio-upload"), "{lines:?}");
    let held = fx.meeting("m1");
    // Still waiting, and "Continue" is still possible.
    assert_eq!(held.status, MeetingStatus::Interrupted);
    assert_eq!(held.sync_state, "pending");
    assert_eq!(held.audio_state, "pending");
    assert_eq!(fx.db.unsynced_segments("m1", 10).unwrap().len(), 0);

    // The next pass leaves it alone: no repeated requests every 30 seconds.
    let before = server.count();
    fx.core.run_pass(true).await;
    assert_eq!(server.count(), before);
}

#[tokio::test]
async fn finishing_an_interrupted_meeting_lets_the_sync_finalize_it() {
    let server = start_mock(happy).await;
    let fx = fixture(&server.url);
    interrupted(&fx, Duration::minutes(5));
    fx.core.run_pass(true).await;
    assert!(!has(&server.lines(), "finalize"));

    assert!(fx.db.finish_interrupted("m1").unwrap());
    fx.core.release("m1");
    fx.core.run_pass(true).await;

    assert!(has(
        &server.lines(),
        "POST /api/desktop/meetings/42/finalize"
    ));
    assert_eq!(fx.meeting("m1").sync_state, "synced");
}

#[tokio::test]
async fn after_twelve_hours_the_meeting_is_finished_by_itself() {
    let server = start_mock(happy).await;
    let fx = fixture(&server.url);
    interrupted(&fx, Duration::hours(12) + Duration::minutes(1));

    fx.core.run_pass(true).await;

    assert!(has(
        &server.lines(),
        "POST /api/desktop/meetings/42/finalize"
    ));
    let done = fx.meeting("m1");
    assert_eq!(done.status, MeetingStatus::Stopped);
    assert_eq!(done.sync_state, "synced");
}

#[tokio::test]
async fn an_interrupted_meeting_without_any_text_is_not_sent_as_empty() {
    let server = start_mock(happy).await;
    let fx = fixture(&server.url);
    fx.add_meeting("m1", MeetingStatus::Interrupted, 0);
    let ended = Utc::now().to_rfc3339_opts(SecondsFormat::Millis, true);
    fx.db
        .finish_meeting("m1", MeetingStatus::Interrupted, &ended, 0.0)
        .unwrap();
    fx.core.run_pass(false).await;
    // Not marked empty: the user may still continue it.
    assert_eq!(fx.meeting("m1").sync_state, "pending");
    assert!(!has(&server.lines(), "finalize"));
}

#[tokio::test]
async fn a_continued_meeting_is_finalized_only_after_its_next_stop() {
    use crate::managers::meeting::resume_blocker_for_tests as blocker;

    let server = start_mock(happy).await;
    let fx = fixture(&server.url);
    interrupted(&fx, Duration::minutes(5));
    fx.core.run_pass(true).await;
    // Its text is on the server, yet "Continue" is open.
    assert_eq!(blocker(&fx.meeting("m1")), None);

    // Continue: the meeting records again; the sync leaves it alone.
    fx.db.mark_recording("m1").unwrap();
    fx.core.release("m1");
    fx.core.run_pass(true).await;
    assert!(!has(&server.lines(), "finalize"));
    assert_eq!(fx.meeting("m1").status, MeetingStatus::Recording);

    // The next stop: now it goes through to the end.
    let ended = Utc::now().to_rfc3339_opts(SecondsFormat::Millis, true);
    fx.db
        .finish_meeting("m1", MeetingStatus::Stopped, &ended, 120.0)
        .unwrap();
    fx.core.release("m1");
    fx.core.run_pass(true).await;
    assert!(has(
        &server.lines(),
        "POST /api/desktop/meetings/42/finalize"
    ));
    // A finalized meeting is continued only after the server took it back.
    assert!(blocker(&fx.meeting("m1")).is_some());
}

#[tokio::test]
async fn finishing_during_a_held_pass_does_not_make_the_meeting_wait() {
    let server = start_mock(happy).await;
    let fx = fixture(&server.url);
    interrupted(&fx, Duration::minutes(5));
    // "Finish" came in while the pass was still under way: the status changed
    // before the pass recorded that the meeting is held.
    assert!(fx.db.finish_interrupted("m1").unwrap());
    fx.core.hold_back("m1");
    fx.core.run_pass(true).await;
    assert!(has(
        &server.lines(),
        "POST /api/desktop/meetings/42/finalize"
    ));
}
