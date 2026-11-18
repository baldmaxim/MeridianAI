//! Re-clustering of a meeting's voices at the stop, the database side: reads
//! the phrases with their embeddings, runs `voice::recluster`, and rewrites
//! the segments' voices and the meeting's voices in one transaction.

use std::collections::{HashMap, HashSet};

use anyhow::Result;
use rusqlite::params;

use super::db::MeetingDb;
use super::sink::default_side;
use super::voice::{recluster, ReclusterInput};

const LABEL_PREFIX: &str = "Голос ";

/// What a re-clustering did (counts only).
#[derive(Debug, PartialEq, Eq)]
pub(super) struct ReclusterReport {
    pub(super) phrases: usize,
    pub(super) voices_before: usize,
    pub(super) voices_after: usize,
}

/// 192 `f32`, little-endian; anything else is no embedding.
fn decode_embedding(blob: Option<Vec<u8>>) -> Option<Vec<f32>> {
    let blob = blob.filter(|b| !b.is_empty() && b.len() % 4 == 0)?;
    Some(
        blob.as_chunks::<4>()
            .0
            .iter()
            .map(|c| f32::from_le_bytes(*c))
            .collect(),
    )
}

fn unit_mean(embeddings: &[&Vec<f32>]) -> Vec<f32> {
    let Some(first) = embeddings.first() else {
        return Vec::new();
    };
    let dim = first.len();
    let mut sum = vec![0.0f32; dim];
    for e in embeddings.iter().filter(|e| e.len() == dim) {
        let norm = e.iter().map(|x| x * x).sum::<f32>().sqrt();
        if norm > f32::EPSILON {
            sum.iter_mut()
                .zip(e.iter())
                .for_each(|(s, x)| *s += x / norm);
        }
    }
    let norm = sum.iter().map(|x| x * x).sum::<f32>().sqrt();
    if norm > f32::EPSILON {
        sum.iter_mut().for_each(|x| *x /= norm);
    }
    sum
}

/// A segment as the rewrite needs it.
struct Row {
    id: String,
    channel: String,
    start: f64,
    end: f64,
    voice: Option<String>,
    embedding: Option<Vec<f32>>,
}

impl MeetingDb {
    /// The meeting's phrases with their embeddings, in time order.
    fn recluster_inputs(&self, meeting_id: &str) -> Result<Vec<ReclusterInput>> {
        let conn = self.conn();
        let mut stmt = conn.prepare(
            "SELECT id, start_time, end_time, embedding FROM segments
             WHERE meeting_id = ?1 ORDER BY start_time, channel, id",
        )?;
        let rows = stmt.query_map([meeting_id], |row| {
            Ok(ReclusterInput {
                id: row.get(0)?,
                start: row.get(1)?,
                end: row.get(2)?,
                embedding: decode_embedding(row.get(3)?),
            })
        })?;
        Ok(rows.collect::<rusqlite::Result<_>>()?)
    }

    /// Gives the segments the voices `assignment` says ("Голос N", N from 1
    /// by the number), and rebuilds the meeting's voices from them. Everything
    /// the server must hear again is marked: the changed segments, the voices
    /// (all, their sides included), and the labels that are gone. Returns the
    /// number of voices.
    fn apply_recluster(
        &self,
        meeting_id: &str,
        assignment: &HashMap<String, usize>,
        created_at: i64,
    ) -> Result<usize> {
        let mut conn = self.conn();
        let tx = conn.transaction()?;

        let rows: Vec<Row> = {
            let mut stmt = tx.prepare(
                "SELECT id, channel, start_time, end_time, voice, embedding FROM segments
                 WHERE meeting_id = ?1 ORDER BY start_time, channel, id",
            )?;
            let mapped = stmt.query_map([meeting_id], |row| {
                Ok(Row {
                    id: row.get(0)?,
                    channel: row.get(1)?,
                    start: row.get(2)?,
                    end: row.get(3)?,
                    voice: row.get(4)?,
                    embedding: decode_embedding(row.get(5)?),
                })
            })?;
            mapped.collect::<rusqlite::Result<_>>()?
        };
        // Old voices: the sides the user chose, and every label (to clear the gone ones).
        let mut old_labels: HashSet<String> = rows.iter().filter_map(|r| r.voice.clone()).collect();
        let mut user_sides: HashMap<String, Option<String>> = HashMap::new();
        {
            let mut stmt = tx.prepare(
                "SELECT label, side, side_user FROM meeting_voices WHERE meeting_id = ?1",
            )?;
            let mapped = stmt.query_map([meeting_id], |row| {
                Ok((row.get::<_, String>(0)?, row.get(1)?, row.get::<_, i64>(2)?))
            })?;
            for row in mapped {
                let (label, side, user) = row?;
                old_labels.insert(label.clone());
                if user != 0 {
                    user_sides.insert(label, side);
                }
            }
        }
        let on_server: bool = tx.query_row(
            "SELECT server_meeting_id IS NOT NULL FROM meetings WHERE id = ?1",
            [meeting_id],
            |row| row.get(0),
        )?;

        let count = assignment.values().max().map_or(0, |m| m + 1);
        let mut members: Vec<Vec<&Row>> = vec![Vec::new(); count];
        // Speech time of the user-labelled old voices inside each new one.
        let mut overlap: Vec<HashMap<&str, f64>> = vec![HashMap::new(); count];
        for row in &rows {
            let Some(&voice) = assignment.get(&row.id) else {
                continue;
            };
            members[voice].push(row);
            if let Some(old) = row.voice.as_deref().filter(|l| user_sides.contains_key(*l)) {
                *overlap[voice].entry(old).or_default() += (row.end - row.start).max(0.0);
            }
        }

        let new_labels: Vec<String> = (1..=count).map(|n| format!("{LABEL_PREFIX}{n}")).collect();
        for row in &rows {
            let Some(&voice) = assignment.get(&row.id) else {
                continue;
            };
            if row.voice.as_deref() != Some(new_labels[voice].as_str()) {
                tx.execute(
                    "UPDATE segments SET voice = ?2, synced = 0 WHERE id = ?1",
                    params![row.id, new_labels[voice]],
                )?;
            }
        }

        tx.execute(
            "DELETE FROM meeting_voices WHERE meeting_id = ?1",
            [meeting_id],
        )?;
        for (voice, label) in new_labels.iter().enumerate() {
            let Some(earliest) = members[voice].first() else {
                continue;
            };
            let embeddings: Vec<&Vec<f32>> = members[voice]
                .iter()
                .filter_map(|r| r.embedding.as_ref())
                .collect();
            // The user's side of the old voice that sounds most in this one; a
            // draw between different sides says nothing. No user's choice: the
            // channel decides, as for a voice heard live.
            let top = overlap[voice].values().fold(0.0f64, |a, b| a.max(*b));
            let inherited: Vec<&Option<String>> = overlap[voice]
                .iter()
                .filter(|(_, o)| **o >= top - 1e-9)
                .filter_map(|(l, _)| user_sides.get(*l))
                .collect();
            let (side, side_user) = if inherited.is_empty() {
                (default_side(&earliest.channel).map(str::to_string), false)
            } else if inherited.iter().all(|s| *s == inherited[0]) {
                (inherited[0].clone(), true)
            } else {
                (None, true)
            };
            tx.execute(
                "INSERT INTO meeting_voices (meeting_id, label, side, centroid, count,
                    first_channel, side_synced, side_user, created_at)
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6, 0, ?7, ?8)",
                params![
                    meeting_id,
                    label,
                    side,
                    serde_json::to_string(&unit_mean(&embeddings))?,
                    embeddings.len() as i64,
                    earliest.channel,
                    i64::from(side_user),
                    created_at,
                ],
            )?;
            tx.execute(
                "DELETE FROM stale_voice_roles WHERE meeting_id = ?1 AND label = ?2",
                params![meeting_id, label],
            )?;
        }
        if on_server {
            for label in old_labels.iter().filter(|l| !new_labels.contains(l)) {
                tx.execute(
                    "INSERT OR IGNORE INTO stale_voice_roles (meeting_id, label) VALUES (?1, ?2)",
                    params![meeting_id, label],
                )?;
            }
        }
        tx.commit()?;
        Ok(count)
    }
}

/// Re-clusters the meeting's voices. `None`: not enough to go on (old meeting
/// without embeddings, a short one), the online voices stay as they are.
pub(super) fn recluster_meeting(
    db: &MeetingDb,
    meeting_id: &str,
) -> Result<Option<ReclusterReport>> {
    let phrases = db.recluster_inputs(meeting_id)?;
    let k = db
        .get_meeting(meeting_id)?
        .and_then(|m| m.max_speakers)
        .and_then(|n| usize::try_from(n).ok());
    let Some(assignment) = recluster(&phrases, k) else {
        return Ok(None);
    };
    let voices_before = db.list_voices(meeting_id)?.len();
    let voices_after =
        db.apply_recluster(meeting_id, &assignment, chrono::Utc::now().timestamp())?;
    Ok(Some(ReclusterReport {
        phrases: phrases.len(),
        voices_before,
        voices_after,
    }))
}

#[cfg(test)]
mod tests {
    use super::super::db::{sample_meeting, Segment};
    use super::*;

    /// A phrase of `speaker` (a direction in 8 dimensions plus a small wobble).
    fn embedding(speaker: usize, n: usize) -> Vec<f32> {
        (0..8)
            .map(|d| {
                // A fixed pseudo-random wobble in [-0.1, 0.1].
                let hash = (n as u64 * 8 + d as u64 + 1).wrapping_mul(0x9E37_79B9_7F4A_7C15);
                let wobble = ((hash >> 40) as f32 / (1u64 << 24) as f32 - 0.5) / 5.0;
                f32::from(u8::from(d == speaker)) + wobble
            })
            .collect()
    }

    /// 60 phrases of 3 speakers (0, 1 on the system sound, 1 on the microphone),
    /// the online voices over-split: speaker 2 is "Голос 3" and "Голос 4".
    fn meeting_with_voices(server_id: Option<i64>) -> MeetingDb {
        let db = MeetingDb::open_in_memory().unwrap();
        // The user named three participants at the start.
        let mut meeting = sample_meeting("m", "2026-01-01T10:00:00.000Z");
        meeting.max_speakers = Some(3);
        db.insert_meeting(&meeting).unwrap();
        if let Some(id) = server_id {
            db.set_server_meeting_id("m", id).unwrap();
        }
        for n in 0..60 {
            let speaker = n % 3;
            let old = match speaker {
                0 => "Голос 1",
                1 => "Голос 2",
                _ if n % 2 == 0 => "Голос 3",
                _ => "Голос 4",
            };
            let segment = Segment {
                id: format!("s{n}"),
                meeting_id: "m".into(),
                channel: if speaker == 1 { "mic" } else { "system" }.into(),
                start_time: n as f64 * 3.0,
                end_time: n as f64 * 3.0 + 2.5,
                text: "фраза".into(),
                created_at: "2026-01-01T00:00:00.000Z".into(),
                synced: true,
                voice: Some(old.into()),
                language: None,
                translation: None,
                speaker: None,
                server_id: None,
            };
            db.insert_segment_embedded(&segment, Some(&embedding(speaker, n)))
                .unwrap();
        }
        for (n, label) in ["Голос 1", "Голос 2", "Голос 3", "Голос 4"]
            .iter()
            .enumerate()
        {
            let voice = super::super::voice::VoiceCentroid {
                label: (*label).into(),
                vector: vec![1.0],
                count: 1,
            };
            let side = if n == 1 {
                Some("self")
            } else {
                Some("opponent")
            };
            db.insert_voice("m", &voice, side, "system", 1).unwrap();
            db.mark_voice_synced_if("m", label, side).unwrap();
        }
        db
    }

    #[test]
    fn embeddings_round_trip_through_the_blob() {
        let db = meeting_with_voices(None);
        let inputs = db.recluster_inputs("m").unwrap();
        assert_eq!(inputs.len(), 60);
        assert_eq!(inputs[5].embedding.as_deref(), Some(&embedding(2, 5)[..]));
        // A segment stored the plain way has none.
        let plain = Segment {
            id: "plain".into(),
            meeting_id: "m".into(),
            channel: "mic".into(),
            start_time: 999.0,
            end_time: 1000.0,
            text: "x".into(),
            created_at: String::new(),
            synced: false,
            voice: None,
            language: None,
            translation: None,
            speaker: None,
            server_id: None,
        };
        db.insert_segment(&plain).unwrap();
        assert!(db
            .recluster_inputs("m")
            .unwrap()
            .last()
            .unwrap()
            .embedding
            .is_none());
    }

    #[test]
    fn the_stop_rebuilds_voices_and_marks_what_the_server_must_hear() {
        let db = meeting_with_voices(Some(5));
        // The user said "Голос 2" is us: that is the voice of the microphone speaker.
        db.set_voice_side("m", "Голос 2", Some("self")).unwrap();
        db.mark_voice_synced_if("m", "Голос 2", Some("self"))
            .unwrap();

        let report = recluster_meeting(&db, "m").unwrap().unwrap();
        assert_eq!(
            report,
            ReclusterReport {
                phrases: 60,
                voices_before: 4,
                voices_after: 3
            }
        );

        let voices = db.list_voices("m").unwrap();
        let labels: Vec<&str> = voices.iter().map(|v| v.label.as_str()).collect();
        assert_eq!(labels, ["Голос 1", "Голос 2", "Голос 3"]);
        // Numbered by the first phrase: speakers 0, 1, 2.
        assert_eq!(
            voices
                .iter()
                .map(|v| (v.count, v.first_channel.as_str()))
                .collect::<Vec<_>>(),
            [(20, "system"), (20, "mic"), (20, "system")]
        );
        // The user's side moved with the speaker; the others got the channel's side.
        assert_eq!(
            voices.iter().map(|v| v.side.as_deref()).collect::<Vec<_>>(),
            [Some("opponent"), Some("self"), Some("opponent")]
        );
        // Every voice is to be sent, the vanished label is to be cleared.
        assert_eq!(db.unsynced_voices("m").unwrap().len(), 3);
        assert_eq!(db.stale_voice_roles("m").unwrap(), ["Голос 4"]);

        let segments = db.list_segments("m").unwrap();
        assert!(segments.iter().all(|s| s.voice.is_some()));
        let by_id = |id: &str| segments.iter().find(|s| s.id == id).unwrap();
        // Speaker 2's phrases were "Голос 3"/"Голос 4": the odd ones changed, the even stayed.
        assert_eq!(by_id("s5").voice.as_deref(), Some("Голос 3"));
        assert!(!by_id("s5").synced);
        assert!(by_id("s2").synced);
        // Speaker 0 and 1 kept their labels: the server has them already.
        assert!(by_id("s0").synced && by_id("s1").synced);
        assert_eq!(db.unsynced_segments("m", 100).unwrap().len(), 10);
    }

    #[test]
    fn a_meeting_the_server_does_not_know_has_nothing_to_clear() {
        let db = meeting_with_voices(None);
        recluster_meeting(&db, "m").unwrap().unwrap();
        assert!(db.stale_voice_roles("m").unwrap().is_empty());
    }

    #[test]
    fn a_label_that_lives_again_is_sent_instead_of_cleared() {
        let db = meeting_with_voices(Some(5));
        recluster_meeting(&db, "m").unwrap().unwrap();
        // Resumed: the online clusterer names the next voice "Голос 4" again.
        let voice = super::super::voice::VoiceCentroid {
            label: "Голос 4".into(),
            vector: vec![1.0],
            count: 1,
        };
        db.insert_voice("m", &voice, None, "mixed", 2).unwrap();
        assert!(db.stale_voice_roles("m").unwrap().is_empty());
        let unsynced = db.unsynced_voices("m").unwrap();
        assert!(unsynced.contains(&("Голос 4".to_string(), None)));
    }

    #[test]
    fn a_meeting_without_embeddings_is_left_alone() {
        let db = MeetingDb::open_in_memory().unwrap();
        db.insert_meeting(&sample_meeting("m", "2026-01-01T10:00:00.000Z"))
            .unwrap();
        assert_eq!(recluster_meeting(&db, "m").unwrap(), None);
    }
}
