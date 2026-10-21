use std::sync::mpsc;

use chrono::Utc;
use tempfile::tempdir;

use super::capture::ChanMsg;
use super::db::sample_meeting;
use super::recognizer::{run_recognizer, PhraseQueue};
use super::workers::cut_phrases;
use super::{now_iso, recover_interrupted, short_id, storage, MeetingDb, MeetingStatus};
use crate::audio_toolkit::vad::SpeechScorer;

#[test]
fn recording_meetings_become_interrupted_with_duration_and_time() {
    let root = tempdir().unwrap();
    let db = MeetingDb::open_in_memory().unwrap();
    db.insert_meeting(&sample_meeting("live", "2026-01-01T10:00:00.000Z"))
        .unwrap();
    let mut done = sample_meeting("done", "2026-01-01T08:00:00.000Z");
    done.status = MeetingStatus::Stopped;
    done.ended_at = Some("2026-01-01T09:00:00.000Z".into());
    db.insert_meeting(&done).unwrap();
    db.insert_meeting(&sample_meeting("silent", "2026-01-01T11:00:00.000Z"))
        .unwrap();

    // 3 s of mic, 2 s of system sound.
    let audio = storage::audio_dir(root.path(), "live");
    let mut mic = storage::PcmWriter::new(&audio, "mic", 16_000).unwrap();
    mic.write(&vec![1; 48_000]).unwrap();
    mic.finish().unwrap();
    let mut system = storage::PcmWriter::new(&audio, "system", 16_000).unwrap();
    system.write(&vec![1; 32_000]).unwrap();
    system.finish().unwrap();

    assert_eq!(recover_interrupted(&db, root.path()).unwrap(), 2);

    let live = db.get_meeting("live").unwrap().unwrap();
    assert_eq!(live.status, MeetingStatus::Interrupted);
    assert_eq!(live.duration_seconds, 3.0);
    let ended = chrono::DateTime::parse_from_rfc3339(live.ended_at.as_deref().unwrap()).unwrap();
    assert!((Utc::now() - ended.with_timezone(&Utc)).num_seconds().abs() < 60);

    // No audio at all: ended at the start, zero length.
    let silent = db.get_meeting("silent").unwrap().unwrap();
    assert_eq!(silent.status, MeetingStatus::Interrupted);
    assert_eq!(silent.duration_seconds, 0.0);
    assert_eq!(silent.ended_at.as_deref(), Some("2026-01-01T11:00:00.000Z"));

    // Finished meetings are left alone; a second run finds nothing.
    assert_eq!(db.get_meeting("done").unwrap().unwrap(), done);
    assert_eq!(recover_interrupted(&db, root.path()).unwrap(), 0);
}

#[test]
fn ids_are_short_and_unique() {
    let a = short_id();
    assert_eq!(a.len(), 16);
    assert_ne!(a, short_id());
}

#[test]
fn cutter_turns_channel_messages_into_queued_phrases() {
    use crate::audio_toolkit::vad::{VadFrame, VoiceActivityDetector};

    struct Loud;
    impl VoiceActivityDetector for Loud {
        fn push_frame<'a>(&'a mut self, frame: &'a [f32]) -> anyhow::Result<VadFrame<'a>> {
            Ok(VadFrame::Speech(frame))
        }
        fn frame_samples(&self) -> usize {
            512
        }
    }
    impl SpeechScorer for Loud {
        fn score(&mut self, frames: &[f32]) -> anyhow::Result<Vec<f32>> {
            Ok(frames
                .chunks(512)
                .map(|f| {
                    if f.iter().any(|s| s.abs() > 0.1) {
                        1.0
                    } else {
                        0.0
                    }
                })
                .collect())
        }
    }

    let (tx, rx) = mpsc::channel();
    let queue = PhraseQueue::default();
    tx.send(ChanMsg::Start { offset_secs: 10.0 }).unwrap();
    tx.send(ChanMsg::Samples(vec![0.0; 16_000])).unwrap();
    tx.send(ChanMsg::Samples(
        (0..32_000).map(|i| 0.5 * (i as f32 * 0.2).sin()).collect(),
    ))
    .unwrap();
    tx.send(ChanMsg::Samples(vec![0.0; 16_000])).unwrap();
    drop(tx);
    cut_phrases(rx, Box::new(Loud), &queue, "mixed");

    assert_eq!(queue.len(), 1);
    queue.close();
    let mut seen = Vec::new();
    run_recognizer(
        &queue,
        "m",
        |samples| {
            seen.push(samples.len());
            Ok("текст".to_string())
        },
        |segment, _| {
            assert_eq!(segment.channel, "mixed");
            assert!(
                segment.start_time > 10.4 && segment.start_time < 10.7,
                "{}",
                segment.start_time
            );
            Ok(())
        },
        |_| {},
        short_id,
        now_iso,
    );
    assert_eq!(seen.len(), 1);
}
