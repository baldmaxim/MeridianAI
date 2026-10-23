//! The upload queue of meeting sources (`document_queue` in `meetings.db`):
//! files copied into the app's data folder that wait to go to the server.

use anyhow::Result;
use rusqlite::{params, OptionalExtension, Row};
use serde::Serialize;
use specta::Type;

use super::db::MeetingDb;

pub const DOC_PENDING: &str = "pending";
pub const DOC_UPLOADING: &str = "uploading";
pub const DOC_ERROR: &str = "error";

/// A queue row as the sync sees it.
#[derive(Clone, Debug, PartialEq)]
pub struct DocumentRow {
    pub id: i64,
    pub meeting_id: Option<String>,
    pub server_meeting_id: Option<i64>,
    pub file_path: String,
    pub original_name: String,
    pub size: i64,
    pub mime: String,
    pub server_document_id: Option<i64>,
}

/// A file that has not reached the server, as the UI shows it.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Type)]
pub struct QueuedDocument {
    pub id: i64,
    pub original_name: String,
    pub size: i64,
    /// `pending`, `uploading` or `error`.
    pub state: String,
    pub error: Option<String>,
}

/// What `remove_queued_document` did.
#[derive(Debug, PartialEq, Eq)]
pub enum RemoveOutcome {
    /// Removed; the local copy is at this path.
    Removed(String),
    /// Being uploaded right now.
    Busy,
    NotFound,
}

fn map_row(row: &Row<'_>) -> rusqlite::Result<DocumentRow> {
    Ok(DocumentRow {
        id: row.get("id")?,
        meeting_id: row.get("meeting_id")?,
        server_meeting_id: row.get("server_meeting_id")?,
        file_path: row.get("file_path")?,
        original_name: row.get("original_name")?,
        size: row.get("size")?,
        mime: row.get("mime")?,
        server_document_id: row.get("server_document_id")?,
    })
}

impl MeetingDb {
    #[allow(clippy::too_many_arguments)]
    pub fn insert_document(
        &self,
        meeting_id: Option<&str>,
        server_meeting_id: Option<i64>,
        file_path: &str,
        original_name: &str,
        size: i64,
        mime: &str,
        created_at: &str,
    ) -> Result<i64> {
        let conn = self.conn();
        conn.execute(
            "INSERT INTO document_queue
                (meeting_id, server_meeting_id, file_path, original_name, size, mime, created_at)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)",
            params![
                meeting_id,
                server_meeting_id,
                file_path,
                original_name,
                size,
                mime,
                created_at
            ],
        )?;
        Ok(conn.last_insert_rowid())
    }

    /// Rows of local meetings the server knows by now get its meeting id.
    pub fn link_documents_to_server_meetings(&self) -> Result<usize> {
        Ok(self.conn().execute(
            "UPDATE document_queue
             SET server_meeting_id = (SELECT m.server_meeting_id FROM meetings m
                                      WHERE m.id = document_queue.meeting_id)
             WHERE server_meeting_id IS NULL AND meeting_id IS NOT NULL
               AND (SELECT m.server_meeting_id FROM meetings m
                    WHERE m.id = document_queue.meeting_id) IS NOT NULL",
            [],
        )?)
    }

    /// Rows waiting for an upload whose meeting is on the server, oldest first.
    /// `meeting_id`: only the rows of this local meeting.
    pub fn documents_to_send(&self, meeting_id: Option<&str>) -> Result<Vec<DocumentRow>> {
        let conn = self.conn();
        let mut stmt = conn.prepare(
            "SELECT * FROM document_queue
             WHERE state = 'pending' AND server_meeting_id IS NOT NULL
               AND (?1 IS NULL OR meeting_id = ?1)
             ORDER BY id",
        )?;
        let rows = stmt.query_map([meeting_id], map_row)?;
        Ok(rows.collect::<rusqlite::Result<_>>()?)
    }

    /// An upload cut short by a crash starts over (the sync thread is the only
    /// one that sets `uploading`, and it is not mid-pass when this runs).
    pub fn reset_uploading_documents(&self) -> Result<usize> {
        Ok(self.conn().execute(
            "UPDATE document_queue SET state = 'pending' WHERE state = 'uploading'",
            [],
        )?)
    }

    pub fn set_document_state(
        &self,
        id: i64,
        state: &str,
        error: Option<&str>,
        bump_attempts: bool,
    ) -> Result<()> {
        self.conn().execute(
            "UPDATE document_queue
             SET state = ?2, error = ?3, attempts = attempts + ?4 WHERE id = ?1",
            params![id, state, error, i64::from(bump_attempts)],
        )?;
        Ok(())
    }

    pub fn set_document_server_id(&self, id: i64, server_document_id: Option<i64>) -> Result<()> {
        self.conn().execute(
            "UPDATE document_queue SET server_document_id = ?2 WHERE id = ?1",
            params![id, server_document_id],
        )?;
        Ok(())
    }

    pub fn mark_document_uploaded(&self, id: i64, server_document_id: i64) -> Result<()> {
        self.conn().execute(
            "UPDATE document_queue
             SET state = 'uploaded', server_document_id = ?2, error = NULL WHERE id = ?1",
            params![id, server_document_id],
        )?;
        Ok(())
    }

    /// Files not yet on the server for a local meeting and/or a meeting of the site.
    pub fn list_queued_documents(
        &self,
        meeting_id: Option<&str>,
        server_meeting_id: Option<i64>,
    ) -> Result<Vec<QueuedDocument>> {
        if meeting_id.is_none() && server_meeting_id.is_none() {
            return Ok(Vec::new());
        }
        let conn = self.conn();
        let mut stmt = conn.prepare(
            "SELECT id, original_name, size, state, error FROM document_queue
             WHERE state != 'uploaded' AND (meeting_id = ?1 OR server_meeting_id = ?2)
             ORDER BY id",
        )?;
        let rows = stmt.query_map(params![meeting_id, server_meeting_id], |row| {
            Ok(QueuedDocument {
                id: row.get(0)?,
                original_name: row.get(1)?,
                size: row.get(2)?,
                state: row.get(3)?,
                error: row.get(4)?,
            })
        })?;
        Ok(rows.collect::<rusqlite::Result<_>>()?)
    }

    /// Takes a file out of the queue unless it is being uploaded.
    pub fn remove_queued_document(&self, id: i64) -> Result<RemoveOutcome> {
        let conn = self.conn();
        let found: Option<(String, String)> = conn
            .query_row(
                "SELECT state, file_path FROM document_queue WHERE id = ?1",
                [id],
                |row| Ok((row.get(0)?, row.get(1)?)),
            )
            .optional()?;
        let Some((state, path)) = found else {
            return Ok(RemoveOutcome::NotFound);
        };
        if state == DOC_UPLOADING {
            return Ok(RemoveOutcome::Busy);
        }
        // The state is checked again in the statement: the sync may have
        // claimed the row since the lookup.
        let removed = conn.execute(
            "DELETE FROM document_queue WHERE id = ?1 AND state != 'uploading'",
            [id],
        )?;
        Ok(if removed > 0 {
            RemoveOutcome::Removed(path)
        } else {
            RemoveOutcome::Busy
        })
    }

    /// Claims a row for an upload; `false` when it is gone or not pending any more.
    pub fn claim_document(&self, id: i64) -> Result<bool> {
        Ok(self.conn().execute(
            "UPDATE document_queue SET state = 'uploading' WHERE id = ?1 AND state = 'pending'",
            [id],
        )? > 0)
    }
}

#[cfg(test)]
mod tests {
    use super::super::db::sample_meeting;
    use super::*;

    fn add(db: &MeetingDb, meeting: Option<&str>, server: Option<i64>, name: &str) -> i64 {
        db.insert_document(
            meeting,
            server,
            "/x/a.pdf",
            name,
            10,
            "application/pdf",
            "t",
        )
        .unwrap()
    }

    #[test]
    fn rows_wait_for_the_server_meeting_then_are_linked() {
        let db = MeetingDb::open_in_memory().unwrap();
        db.insert_meeting(&sample_meeting("m", "2026-01-01T10:00:00.000Z"))
            .unwrap();
        add(&db, Some("m"), None, "a.pdf");
        assert!(db.documents_to_send(None).unwrap().is_empty());

        db.set_server_meeting_id("m", 77).unwrap();
        assert_eq!(db.link_documents_to_server_meetings().unwrap(), 1);
        let rows = db.documents_to_send(Some("m")).unwrap();
        assert_eq!(rows.len(), 1);
        assert_eq!(rows[0].server_meeting_id, Some(77));
        assert!(db.documents_to_send(Some("other")).unwrap().is_empty());
    }

    #[test]
    fn queue_lists_and_removes_but_not_while_uploading() {
        let db = MeetingDb::open_in_memory().unwrap();
        let a = add(&db, None, Some(5), "a.pdf");
        let b = add(&db, None, Some(5), "b.pdf");
        add(&db, None, Some(6), "other.pdf");
        assert!(db.claim_document(a).unwrap());
        assert!(!db.claim_document(a).unwrap());

        let list = db.list_queued_documents(None, Some(5)).unwrap();
        assert_eq!(list.len(), 2);
        assert_eq!(list[0].state, DOC_UPLOADING);

        assert_eq!(db.remove_queued_document(a).unwrap(), RemoveOutcome::Busy);
        assert_eq!(
            db.remove_queued_document(b).unwrap(),
            RemoveOutcome::Removed("/x/a.pdf".to_string())
        );
        assert_eq!(
            db.remove_queued_document(b).unwrap(),
            RemoveOutcome::NotFound
        );

        db.mark_document_uploaded(a, 900).unwrap();
        assert!(db.list_queued_documents(None, Some(5)).unwrap().is_empty());
    }

    #[test]
    fn crash_during_upload_returns_the_row_to_pending() {
        let db = MeetingDb::open_in_memory().unwrap();
        let a = add(&db, None, Some(5), "a.pdf");
        db.claim_document(a).unwrap();
        db.set_document_server_id(a, Some(42)).unwrap();
        assert_eq!(db.reset_uploading_documents().unwrap(), 1);
        let rows = db.documents_to_send(None).unwrap();
        assert_eq!(rows[0].server_document_id, Some(42));
    }

    #[test]
    fn deleting_a_meeting_drops_its_queue() {
        let db = MeetingDb::open_in_memory().unwrap();
        db.insert_meeting(&sample_meeting("m", "2026-01-01T10:00:00.000Z"))
            .unwrap();
        add(&db, Some("m"), None, "a.pdf");
        db.delete_meeting("m").unwrap();
        assert!(db
            .list_queued_documents(Some("m"), None)
            .unwrap()
            .is_empty());
    }
}
