//! Sync bookkeeping in `meetings.db`: which meetings and segments still have
//! to go to the server, and how far the audio got.

use anyhow::Result;
use rusqlite::{params, OptionalExtension};

use super::db::{map_meeting, MeetingDb, MeetingInfo, Segment};

/// Stopped or interrupted, and waiting for the server. Meetings in `error`
/// wait for the user's retry.
pub(super) const READY_FOR_SYNC: &str = "status IN ('stopped', 'interrupted') AND sync_state = 'pending'";

impl MeetingDb {
    /// Meetings to send, oldest first.
    pub fn meetings_for_sync(&self) -> Result<Vec<MeetingInfo>> {
        let conn = self.conn();
        let mut stmt = conn.prepare(&format!(
            "SELECT * FROM meetings WHERE {READY_FOR_SYNC} ORDER BY started_at, id"
        ))?;
        let rows = stmt.query_map([], map_meeting)?;
        Ok(rows.collect::<rusqlite::Result<_>>()?)
    }

    pub fn count_meetings_for_sync(&self) -> Result<u32> {
        let count: i64 = self.conn().query_row(
            &format!("SELECT COUNT(*) FROM meetings WHERE {READY_FOR_SYNC}"),
            [],
            |row| row.get(0),
        )?;
        Ok(count as u32)
    }

    pub fn set_server_meeting_id(&self, id: &str, server_meeting_id: i64) -> Result<()> {
        self.conn().execute(
            "UPDATE meetings SET server_meeting_id = ?2 WHERE id = ?1",
            params![id, server_meeting_id],
        )?;
        Ok(())
    }

    /// The first `limit` segments the server has not confirmed, in time order.
    pub fn unsynced_segments(&self, meeting_id: &str, limit: usize) -> Result<Vec<Segment>> {
        let conn = self.conn();
        let mut stmt = conn.prepare(
            "SELECT * FROM segments WHERE meeting_id = ?1 AND synced = 0
             ORDER BY start_time, channel, id LIMIT ?2",
        )?;
        let rows = stmt.query_map(params![meeting_id, limit as i64], super::db::map_segment)?;
        Ok(rows.collect::<rusqlite::Result<_>>()?)
    }

    pub fn mark_segments_synced(&self, ids: &[String]) -> Result<()> {
        let mut conn = self.conn();
        let tx = conn.transaction()?;
        {
            let mut stmt = tx.prepare("UPDATE segments SET synced = 1 WHERE id = ?1")?;
            for id in ids {
                stmt.execute([id])?;
            }
        }
        tx.commit()?;
        Ok(())
    }

    /// `pending` keeps the meeting in the queue (with the reason, if any),
    /// `error` takes it out until the user retries, `synced` finishes it.
    pub fn set_sync_state(
        &self,
        id: &str,
        state: &str,
        error: Option<&str>,
        synced_at: Option<&str>,
    ) -> Result<()> {
        self.conn().execute(
            "UPDATE meetings SET sync_state = ?2, sync_error = ?3, synced_at = ?4 WHERE id = ?1",
            params![id, state, error, synced_at],
        )?;
        Ok(())
    }

    /// Puts a meeting that is not synced back in the queue. `false`: no such
    /// meeting, or it is synced already.
    pub fn reset_sync(&self, id: &str) -> Result<bool> {
        Ok(self.conn().execute(
            "UPDATE meetings SET sync_state = 'pending', sync_error = NULL
             WHERE id = ?1 AND sync_state != 'synced'",
            [id],
        )? > 0)
    }

    pub fn set_audio_state(&self, id: &str, state: &str) -> Result<()> {
        self.conn().execute(
            "UPDATE meetings SET audio_state = ?2 WHERE id = ?1",
            params![id, state],
        )?;
        Ok(())
    }

    /// Channels whose audio the server has confirmed.
    pub fn audio_done_channels(&self, id: &str) -> Result<Vec<String>> {
        let done: Option<String> = self
            .conn()
            .query_row("SELECT audio_done FROM meetings WHERE id = ?1", [id], |r| {
                r.get(0)
            })
            .optional()?;
        Ok(done
            .unwrap_or_default()
            .split(',')
            .filter(|c| !c.is_empty())
            .map(str::to_string)
            .collect())
    }

    pub fn add_audio_done_channel(&self, id: &str, channel: &str) -> Result<()> {
        let mut done = self.audio_done_channels(id)?;
        if !done.iter().any(|c| c == channel) {
            done.push(channel.to_string());
        }
        self.conn().execute(
            "UPDATE meetings SET audio_done = ?2 WHERE id = ?1",
            params![id, done.join(",")],
        )?;
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::super::db::sample_meeting;
    use super::super::MeetingStatus;
    use super::*;

    #[test]
    fn queue_holds_finished_pending_meetings_only() {
        let db = MeetingDb::open_in_memory().unwrap();
        db.insert_meeting(&sample_meeting("live", "2026-01-01T10:00:00.000Z"))
            .unwrap();
        for (id, state) in [("a", "pending"), ("b", "synced"), ("c", "error")] {
            let mut meeting = sample_meeting(id, "2026-01-01T09:00:00.000Z");
            meeting.status = MeetingStatus::Stopped;
            meeting.sync_state = state.to_string();
            db.insert_meeting(&meeting).unwrap();
        }
        let ids: Vec<String> = db
            .meetings_for_sync()
            .unwrap()
            .into_iter()
            .map(|m| m.id)
            .collect();
        assert_eq!(ids, ["a"]);
        assert_eq!(db.count_meetings_for_sync().unwrap(), 1);

        // "Retry" returns an error meeting to the queue; a synced one stays.
        assert!(db.reset_sync("c").unwrap());
        assert!(!db.reset_sync("b").unwrap());
        assert!(!db.reset_sync("missing").unwrap());
        assert_eq!(db.count_meetings_for_sync().unwrap(), 2);
    }

    #[test]
    fn audio_progress_is_remembered() {
        let db = MeetingDb::open_in_memory().unwrap();
        db.insert_meeting(&sample_meeting("m", "2026-01-01T10:00:00.000Z"))
            .unwrap();
        assert_eq!(db.get_meeting("m").unwrap().unwrap().audio_state, "pending");
        assert!(db.audio_done_channels("m").unwrap().is_empty());
        db.add_audio_done_channel("m", "mic").unwrap();
        db.add_audio_done_channel("m", "mic").unwrap();
        db.add_audio_done_channel("m", "system").unwrap();
        assert_eq!(db.audio_done_channels("m").unwrap(), ["mic", "system"]);
        db.set_audio_state("m", "done").unwrap();
        assert_eq!(db.get_meeting("m").unwrap().unwrap().audio_state, "done");
    }

    #[test]
    fn upgrade_keeps_existing_meetings() {
        // A database from before the sync columns: migrate it and read it back.
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("meetings.db");
        {
            let conn = rusqlite::Connection::open(&path).unwrap();
            conn.execute_batch(
                "CREATE TABLE meetings (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL, capture_mode TEXT NOT NULL,
                    started_at TEXT NOT NULL, ended_at TEXT, status TEXT NOT NULL,
                    duration_seconds REAL NOT NULL DEFAULT 0, server_meeting_id INTEGER,
                    sync_state TEXT NOT NULL DEFAULT 'pending', sync_error TEXT, synced_at TEXT,
                    customer_id INTEGER, object_id INTEGER);
                 CREATE TABLE segments (
                    id TEXT PRIMARY KEY,
                    meeting_id TEXT NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
                    channel TEXT NOT NULL, start_time REAL NOT NULL, end_time REAL NOT NULL,
                    text TEXT NOT NULL, created_at TEXT NOT NULL, synced INTEGER NOT NULL DEFAULT 0);
                 CREATE INDEX idx_segments_meeting ON segments(meeting_id, start_time);
                 CREATE TABLE notes (
                    id TEXT PRIMARY KEY,
                    meeting_id TEXT NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
                    at_seconds REAL NOT NULL, text TEXT NOT NULL, updated_at TEXT NOT NULL);
                 CREATE INDEX idx_notes_meeting ON notes(meeting_id, at_seconds);
                 INSERT INTO meetings (id, title, capture_mode, started_at, status)
                    VALUES ('old', 'Старая', 'online', '2026-01-01T10:00:00.000Z', 'stopped');
                 PRAGMA user_version = 1;",
            )
            .unwrap();
        }
        let db = MeetingDb::open(&path).unwrap();
        let old = db.get_meeting("old").unwrap().unwrap();
        assert_eq!(old.audio_state, "pending");
        assert_eq!(old.sync_state, "pending");
    }
}
