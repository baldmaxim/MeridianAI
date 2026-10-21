//! The meeting context (type of the negotiation, key terms, the opponent's
//! weak points) in `meetings.db`, and what is still to be sent to the server.

use anyhow::Result;
use rusqlite::{params, OptionalExtension};

use super::db::{map_meeting, MeetingDb, MeetingInfo};
use super::db_sync::READY_FOR_SYNC;

impl MeetingDb {
    /// Stores the context as given and marks it as not yet on the server.
    /// `false`: no such meeting.
    pub fn set_meeting_context(
        &self,
        id: &str,
        negotiation_type: Option<&str>,
        key_terms: Option<&str>,
        opponent_weaknesses: Option<&str>,
    ) -> Result<bool> {
        Ok(self.conn().execute(
            "UPDATE meetings SET negotiation_type = ?2, key_terms = ?3,
                opponent_weaknesses = ?4, context_dirty = 1 WHERE id = ?1",
            params![id, negotiation_type, key_terms, opponent_weaknesses],
        )? > 0)
    }

    /// Whether the server lacks the latest context of the meeting.
    pub fn context_dirty(&self, id: &str) -> Result<bool> {
        let dirty: Option<i64> = self
            .conn()
            .query_row(
                "SELECT context_dirty FROM meetings WHERE id = ?1",
                [id],
                |row| row.get(0),
            )
            .optional()?;
        Ok(dirty.unwrap_or(0) != 0)
    }

    /// The server has the context that was sent. The flag stays when the
    /// context was edited meanwhile. `true`: the flag was cleared.
    pub fn clear_context_dirty_if(
        &self,
        id: &str,
        negotiation_type: Option<&str>,
        key_terms: Option<&str>,
        opponent_weaknesses: Option<&str>,
    ) -> Result<bool> {
        Ok(self.conn().execute(
            "UPDATE meetings SET context_dirty = 0
             WHERE id = ?1 AND context_dirty = 1 AND negotiation_type IS ?2
               AND key_terms IS ?3 AND opponent_weaknesses IS ?4",
            params![id, negotiation_type, key_terms, opponent_weaknesses],
        )? > 0)
    }

    /// Meetings that are on the server and wait with a changed context, but
    /// are not in the main sync queue (that one sends the context itself).
    pub fn meetings_with_pending_context(&self) -> Result<Vec<MeetingInfo>> {
        let conn = self.conn();
        let mut stmt = conn.prepare(&format!(
            "SELECT * FROM meetings
             WHERE context_dirty = 1 AND server_meeting_id IS NOT NULL
               AND NOT ({READY_FOR_SYNC})
             ORDER BY started_at, id"
        ))?;
        let rows = stmt.query_map([], map_meeting)?;
        Ok(rows.collect::<rusqlite::Result<_>>()?)
    }
}

#[cfg(test)]
mod tests {
    use super::super::db::{sample_meeting, MIGRATIONS};
    use super::super::MeetingStatus;
    use super::*;

    fn stopped(db: &MeetingDb, id: &str, state: &str, server_id: Option<i64>) {
        let mut meeting = sample_meeting(id, "2026-01-01T09:00:00.000Z");
        meeting.status = MeetingStatus::Stopped;
        meeting.sync_state = state.to_string();
        meeting.server_meeting_id = server_id;
        db.insert_meeting(&meeting).unwrap();
    }

    #[test]
    fn migration_v4_keeps_meetings_and_adds_context_columns() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("meetings.db");
        {
            let mut conn = rusqlite::Connection::open(&path).unwrap();
            rusqlite_migration::Migrations::new(MIGRATIONS[..3].to_vec())
                .to_latest(&mut conn)
                .unwrap();
            conn.execute(
                "INSERT INTO meetings (id, title, capture_mode, started_at, status, customer_name)
                 VALUES ('old', 'Старая', 'online', '2026-01-01T10:00:00.000Z', 'stopped', 'ООО')",
                [],
            )
            .unwrap();
            let version: i32 = conn
                .pragma_query_value(None, "user_version", |row| row.get(0))
                .unwrap();
            assert_eq!(version, 3);
        }
        let db = MeetingDb::open(&path).unwrap();
        let old = db.get_meeting("old").unwrap().unwrap();
        assert_eq!(old.customer_name.as_deref(), Some("ООО"));
        assert!(old.negotiation_type.is_none());
        assert!(old.key_terms.is_none());
        assert!(old.opponent_weaknesses.is_none());
        assert!(!db.context_dirty("old").unwrap());
        let version: i32 = db
            .conn()
            .pragma_query_value(None, "user_version", |row| row.get(0))
            .unwrap();
        assert_eq!(version, 4);
        assert_eq!(MIGRATIONS.len(), 4);
    }

    #[test]
    fn setting_the_context_marks_it_dirty_and_clearing_it_stores_null() {
        let db = MeetingDb::open_in_memory().unwrap();
        stopped(&db, "m", "synced", Some(5));
        assert!(!db.context_dirty("m").unwrap());

        assert!(db
            .set_meeting_context("m", Some("price"), Some("срок 3 месяца"), None)
            .unwrap());
        let meeting = db.get_meeting("m").unwrap().unwrap();
        assert_eq!(meeting.negotiation_type.as_deref(), Some("price"));
        assert_eq!(meeting.key_terms.as_deref(), Some("срок 3 месяца"));
        assert!(meeting.opponent_weaknesses.is_none());
        assert!(db.context_dirty("m").unwrap());
        assert!(!db.set_meeting_context("ghost", None, None, None).unwrap());

        // The flag goes only when the context is the one that was sent.
        assert!(!db
            .clear_context_dirty_if("m", Some("price"), Some("другое"), None)
            .unwrap());
        assert!(db.context_dirty("m").unwrap());
        assert!(db
            .clear_context_dirty_if("m", Some("price"), Some("срок 3 месяца"), None)
            .unwrap());
        assert!(!db.context_dirty("m").unwrap());

        // Clearing everything is a change too.
        db.set_meeting_context("m", None, None, None).unwrap();
        let meeting = db.get_meeting("m").unwrap().unwrap();
        assert!(meeting.negotiation_type.is_none() && meeting.key_terms.is_none());
        assert!(db.context_dirty("m").unwrap());
    }

    #[test]
    fn only_meetings_outside_the_main_queue_are_listed_for_the_context_pass() {
        let db = MeetingDb::open_in_memory().unwrap();
        stopped(&db, "synced", "synced", Some(1));
        stopped(&db, "queued", "pending", Some(2));
        stopped(&db, "not_on_server", "synced", None);
        stopped(&db, "clean", "synced", Some(3));
        for id in ["synced", "queued", "not_on_server"] {
            db.set_meeting_context(id, Some("x"), None, None).unwrap();
        }
        let ids: Vec<String> = db
            .meetings_with_pending_context()
            .unwrap()
            .into_iter()
            .map(|m| m.id)
            .collect();
        assert_eq!(ids, ["synced"]);
    }

    #[test]
    fn the_context_is_searchable_in_the_local_index() {
        let db = MeetingDb::open_in_memory().unwrap();
        stopped(&db, "m", "pending", None);
        db.set_meeting_context("m", None, Some("гарантийный удерживаемый платёж"), None)
            .unwrap();
        db.index_local_meeting("m").unwrap();
        let hits = db.search_meetings("удерживаемый", None).unwrap();
        assert_eq!(hits.len(), 1);
        assert_eq!(hits[0].id, "m");
    }
}
