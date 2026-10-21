//! Voices of a meeting in `meetings.db`: who spoke ("Голос N"), on which side
//! each voice is, the centroid the clusterer restores from, and which sides
//! the server has not got yet.

use anyhow::Result;
use rusqlite::params;
use serde::Serialize;
use specta::Type;

use super::db::{map_meeting, MeetingDb, MeetingInfo};
use super::db_sync::READY_FOR_SYNC;
use super::voice::VoiceCentroid;

/// A voice of a meeting, as the UI shows it.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Type)]
pub struct MeetingVoice {
    pub label: String,
    /// `self`, `opponent` or `None` (not told).
    pub side: Option<String>,
    /// Phrases that went into the voice's centroid.
    pub count: u32,
    /// Where the voice was first heard: `mic`, `system` or `mixed`.
    pub first_channel: String,
}

/// "Голос 12" -> 12; labels without a number go last.
fn voice_number(label: &str) -> u32 {
    label
        .rsplit(' ')
        .next()
        .and_then(|n| n.parse().ok())
        .unwrap_or(u32::MAX)
}

impl MeetingDb {
    /// By the voice's number.
    pub fn list_voices(&self, meeting_id: &str) -> Result<Vec<MeetingVoice>> {
        let conn = self.conn();
        let mut stmt = conn.prepare(
            "SELECT label, side, count, first_channel FROM meeting_voices WHERE meeting_id = ?1",
        )?;
        let rows = stmt.query_map([meeting_id], |row| {
            Ok(MeetingVoice {
                label: row.get(0)?,
                side: row.get(1)?,
                count: row.get::<_, i64>(2)?.max(0) as u32,
                first_channel: row.get(3)?,
            })
        })?;
        let mut voices: Vec<MeetingVoice> = rows.collect::<rusqlite::Result<_>>()?;
        voices.sort_by(|a, b| {
            (voice_number(&a.label), &a.label).cmp(&(voice_number(&b.label), &b.label))
        });
        Ok(voices)
    }

    /// The centroids to restore the clusterer from. An unreadable one is skipped.
    pub fn voice_centroids(&self, meeting_id: &str) -> Result<Vec<VoiceCentroid>> {
        let conn = self.conn();
        let mut stmt = conn
            .prepare("SELECT label, centroid, count FROM meeting_voices WHERE meeting_id = ?1")?;
        let rows = stmt.query_map([meeting_id], |row| {
            Ok((
                row.get::<_, String>(0)?,
                row.get::<_, String>(1)?,
                row.get::<_, i64>(2)?,
            ))
        })?;
        let mut centroids = Vec::new();
        for row in rows {
            let (label, json, count) = row?;
            if let Ok(vector) = serde_json::from_str::<Vec<f32>>(&json) {
                centroids.push(VoiceCentroid {
                    label,
                    vector,
                    count: count.max(0) as u32,
                });
            }
        }
        Ok(centroids)
    }

    /// A voice heard for the first time. Without a side there is nothing for
    /// the server to learn, so it counts as synced.
    pub fn insert_voice(
        &self,
        meeting_id: &str,
        voice: &VoiceCentroid,
        side: Option<&str>,
        first_channel: &str,
        created_at: i64,
    ) -> Result<()> {
        self.conn().execute(
            "INSERT INTO meeting_voices (meeting_id, label, side, centroid, count,
                first_channel, side_synced, created_at)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8)",
            params![
                meeting_id,
                voice.label,
                side,
                serde_json::to_string(&voice.vector)?,
                voice.count,
                first_channel,
                i64::from(side.is_none()),
                created_at,
            ],
        )?;
        Ok(())
    }

    pub fn update_voice_centroid(&self, meeting_id: &str, voice: &VoiceCentroid) -> Result<()> {
        self.conn().execute(
            "UPDATE meeting_voices SET centroid = ?3, count = ?4
             WHERE meeting_id = ?1 AND label = ?2",
            params![
                meeting_id,
                voice.label,
                serde_json::to_string(&voice.vector)?,
                voice.count
            ],
        )?;
        Ok(())
    }

    /// Sets the side (`self`, `opponent`, `None`) and marks it as not yet on
    /// the server. `false`: no such voice.
    pub fn set_voice_side(
        &self,
        meeting_id: &str,
        label: &str,
        side: Option<&str>,
    ) -> Result<bool> {
        Ok(self.conn().execute(
            "UPDATE meeting_voices SET side = ?3, side_synced = 0
             WHERE meeting_id = ?1 AND label = ?2",
            params![meeting_id, label, side],
        )? > 0)
    }

    /// Voices (label, side) whose side the server has not got.
    pub fn unsynced_voices(&self, meeting_id: &str) -> Result<Vec<(String, Option<String>)>> {
        let conn = self.conn();
        let mut stmt = conn.prepare(
            "SELECT label, side FROM meeting_voices
             WHERE meeting_id = ?1 AND side_synced = 0 ORDER BY created_at, label",
        )?;
        let rows = stmt.query_map([meeting_id], |row| Ok((row.get(0)?, row.get(1)?)))?;
        Ok(rows.collect::<rusqlite::Result<_>>()?)
    }

    /// The server has the side that was sent; the flag stays if it was
    /// changed meanwhile.
    pub fn mark_voice_synced_if(
        &self,
        meeting_id: &str,
        label: &str,
        side: Option<&str>,
    ) -> Result<bool> {
        Ok(self.conn().execute(
            "UPDATE meeting_voices SET side_synced = 1
             WHERE meeting_id = ?1 AND label = ?2 AND side IS ?3",
            params![meeting_id, label, side],
        )? > 0)
    }

    /// Meetings that are on the server, wait with a changed voice side and are
    /// not in the main sync queue (that one sends the sides itself).
    pub fn meetings_with_pending_voices(&self) -> Result<Vec<MeetingInfo>> {
        let conn = self.conn();
        let mut stmt = conn.prepare(&format!(
            "SELECT * FROM meetings
             WHERE server_meeting_id IS NOT NULL AND status != 'recording'
               AND NOT ({READY_FOR_SYNC})
               AND EXISTS (SELECT 1 FROM meeting_voices v
                           WHERE v.meeting_id = meetings.id AND v.side_synced = 0)
             ORDER BY started_at, id"
        ))?;
        let rows = stmt.query_map([], map_meeting)?;
        Ok(rows.collect::<rusqlite::Result<_>>()?)
    }
}

#[cfg(test)]
mod tests {
    use super::super::db::sample_meeting;
    use super::*;

    fn centroid(label: &str, count: u32) -> VoiceCentroid {
        VoiceCentroid {
            label: label.to_string(),
            vector: vec![0.6, 0.8],
            count,
        }
    }

    fn db_with_meeting() -> MeetingDb {
        let db = MeetingDb::open_in_memory().unwrap();
        db.insert_meeting(&sample_meeting("m", "2026-01-01T10:00:00.000Z"))
            .unwrap();
        db
    }

    #[test]
    fn voices_are_listed_by_number_with_their_centroids() {
        let db = db_with_meeting();
        for (label, side) in [
            ("Голос 10", None),
            ("Голос 2", Some("opponent")),
            ("Голос 1", Some("self")),
        ] {
            db.insert_voice("m", &centroid(label, 3), side, "mic", 100)
                .unwrap();
        }
        let voices = db.list_voices("m").unwrap();
        let labels: Vec<&str> = voices.iter().map(|v| v.label.as_str()).collect();
        assert_eq!(labels, ["Голос 1", "Голос 2", "Голос 10"]);
        assert_eq!(voices[0].side.as_deref(), Some("self"));
        assert_eq!(
            (voices[0].count, voices[0].first_channel.as_str()),
            (3, "mic")
        );

        db.update_voice_centroid(
            "m",
            &VoiceCentroid {
                label: "Голос 1".into(),
                vector: vec![1.0, 0.0],
                count: 4,
            },
        )
        .unwrap();
        let centroids = db.voice_centroids("m").unwrap();
        let first = centroids.iter().find(|c| c.label == "Голос 1").unwrap();
        assert_eq!((first.vector.clone(), first.count), (vec![1.0, 0.0], 4));
        assert!(db.list_voices("other").unwrap().is_empty());
    }

    #[test]
    fn side_changes_are_unsynced_until_the_same_side_is_confirmed() {
        let db = db_with_meeting();
        db.insert_voice("m", &centroid("Голос 1", 1), Some("opponent"), "system", 1)
            .unwrap();
        db.insert_voice("m", &centroid("Голос 2", 1), None, "mixed", 2)
            .unwrap();
        // A voice without a side has nothing to send.
        assert_eq!(
            db.unsynced_voices("m").unwrap(),
            [("Голос 1".to_string(), Some("opponent".to_string()))]
        );

        assert!(db.set_voice_side("m", "Голос 2", Some("self")).unwrap());
        assert!(!db.set_voice_side("m", "Голос 9", Some("self")).unwrap());
        assert_eq!(db.unsynced_voices("m").unwrap().len(), 2);

        // Changed while being sent: the confirmation of the old side is ignored.
        assert!(!db
            .mark_voice_synced_if("m", "Голос 2", Some("opponent"))
            .unwrap());
        assert!(db
            .mark_voice_synced_if("m", "Голос 2", Some("self"))
            .unwrap());
        assert!(db
            .mark_voice_synced_if("m", "Голос 1", Some("opponent"))
            .unwrap());
        assert!(db.unsynced_voices("m").unwrap().is_empty());

        db.set_voice_side("m", "Голос 1", None).unwrap();
        assert_eq!(db.unsynced_voices("m").unwrap().len(), 1);
    }

    #[test]
    fn deleting_a_meeting_deletes_its_voices() {
        let db = db_with_meeting();
        db.insert_voice("m", &centroid("Голос 1", 1), None, "mic", 1)
            .unwrap();
        assert!(db.delete_meeting("m").unwrap());
        assert!(db.list_voices("m").unwrap().is_empty());
    }

    #[test]
    fn pending_voices_are_found_only_for_meetings_outside_the_main_queue() {
        let db = MeetingDb::open_in_memory().unwrap();
        let cases = [
            ("synced", "synced", Some(1)),
            ("queued", "pending", Some(2)),
            ("local", "synced", None),
        ];
        for (id, state, server_id) in cases {
            let mut meeting = sample_meeting(id, "2026-01-01T09:00:00.000Z");
            meeting.status = super::super::MeetingStatus::Stopped;
            meeting.sync_state = state.to_string();
            meeting.server_meeting_id = server_id;
            db.insert_meeting(&meeting).unwrap();
            db.insert_voice(id, &centroid("Голос 1", 1), Some("self"), "mic", 1)
                .unwrap();
        }
        let ids: Vec<String> = db
            .meetings_with_pending_voices()
            .unwrap()
            .into_iter()
            .map(|m| m.id)
            .collect();
        assert_eq!(ids, ["synced"]);
    }
}
