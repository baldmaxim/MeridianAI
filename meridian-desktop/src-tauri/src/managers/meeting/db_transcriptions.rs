//! The queue of «Расшифровка файлов» (`transcription_queue` in `meetings.db`):
//! audio files copied into the app's data folder that go to the server, are
//! recognized there, and whose transcript is kept here to be read offline.

use anyhow::{Context, Result};
use chrono::{SecondsFormat, Utc};
use rusqlite::{params, OptionalExtension, Row};
use serde::{Deserialize, Serialize};
use specta::Type;

use super::db::MeetingDb;

pub const TR_QUEUED: &str = "queued";
pub const TR_PROCESSING: &str = "processing";
pub const TR_ERROR: &str = "error";

fn now() -> String {
    Utc::now().to_rfc3339_opts(SecondsFormat::Millis, true)
}

/// A queue row as the sync sees it.
#[derive(Clone, Debug, PartialEq)]
pub struct TranscriptionRow {
    pub id: String,
    pub filename: String,
    pub local_path: String,
    pub size: i64,
    /// The bytes are in the storage: only the confirm is left.
    pub uploaded: bool,
    pub server_file_id: Option<i64>,
    pub server_job_id: Option<i64>,
}

/// A file of the list, without the (big) transcript.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Type)]
pub struct TranscriptionItem {
    pub id: String,
    pub filename: String,
    pub size: i64,
    /// `queued`, `uploading`, `processing`, `done` or `error`.
    pub status: String,
    /// The server's own status while it is working on the file.
    pub server_status: Option<String>,
    /// A refusal (status `error`) or the reason the last attempt failed
    /// (status `queued`).
    pub error: Option<String>,
    pub created_at: String,
    pub updated_at: String,
}

/// One phrase of the transcript.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize, Type)]
pub struct TranscriptSegment {
    pub speaker: String,
    pub start: f64,
    pub end: f64,
    pub text: String,
}

/// What is stored in `transcript_json`.
#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
pub struct StoredTranscript {
    pub text: String,
    pub segments: Vec<TranscriptSegment>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Type)]
pub struct TranscriptionDetail {
    pub item: TranscriptionItem,
    pub text: String,
    pub segments: Vec<TranscriptSegment>,
}

const ITEM_COLUMNS: &str =
    "id, filename, size, status, server_status, error, created_at, updated_at";

fn map_item(row: &Row<'_>) -> rusqlite::Result<TranscriptionItem> {
    Ok(TranscriptionItem {
        id: row.get(0)?,
        filename: row.get(1)?,
        size: row.get(2)?,
        status: row.get(3)?,
        server_status: row.get(4)?,
        error: row.get(5)?,
        created_at: row.get(6)?,
        updated_at: row.get(7)?,
    })
}

fn map_row(row: &Row<'_>) -> rusqlite::Result<TranscriptionRow> {
    Ok(TranscriptionRow {
        id: row.get("id")?,
        filename: row.get("filename")?,
        local_path: row.get("local_path")?,
        size: row.get("size")?,
        uploaded: row.get::<_, i64>("uploaded")? != 0,
        server_file_id: row.get("server_file_id")?,
        server_job_id: row.get("server_job_id")?,
    })
}

impl MeetingDb {
    /// A new row; `error` is set for a file that was refused at once.
    pub fn insert_transcription(
        &self,
        id: &str,
        filename: &str,
        local_path: &str,
        size: i64,
        status: &str,
        error: Option<&str>,
    ) -> Result<TranscriptionItem> {
        let stamp = now();
        self.conn().execute(
            "INSERT INTO transcription_queue
                (id, filename, local_path, size, status, error, created_at, updated_at)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?7)",
            params![id, filename, local_path, size, status, error, stamp],
        )?;
        self.get_transcription_item(id)?
            .context("The inserted transcription is missing")
    }

    pub fn get_transcription_item(&self, id: &str) -> Result<Option<TranscriptionItem>> {
        Ok(self
            .conn()
            .query_row(
                &format!("SELECT {ITEM_COLUMNS} FROM transcription_queue WHERE id = ?1"),
                [id],
                map_item,
            )
            .optional()?)
    }

    /// Newest first, without the transcripts.
    pub fn list_transcriptions(&self) -> Result<Vec<TranscriptionItem>> {
        let conn = self.conn();
        let mut stmt = conn.prepare(&format!(
            "SELECT {ITEM_COLUMNS} FROM transcription_queue
             ORDER BY created_at DESC, rowid DESC"
        ))?;
        let rows = stmt.query_map([], map_item)?;
        Ok(rows.collect::<rusqlite::Result<_>>()?)
    }

    pub fn get_transcription_detail(&self, id: &str) -> Result<Option<TranscriptionDetail>> {
        let Some(item) = self.get_transcription_item(id)? else {
            return Ok(None);
        };
        let json: Option<String> = self.conn().query_row(
            "SELECT transcript_json FROM transcription_queue WHERE id = ?1",
            [id],
            |row| row.get(0),
        )?;
        let stored: StoredTranscript = match json {
            Some(json) => serde_json::from_str(&json).context("Broken stored transcript")?,
            None => StoredTranscript::default(),
        };
        Ok(Some(TranscriptionDetail {
            item,
            text: stored.text,
            segments: stored.segments,
        }))
    }

    /// Rows waiting for an upload, oldest first.
    pub fn transcriptions_to_send(&self) -> Result<Vec<TranscriptionRow>> {
        self.rows_with_status(TR_QUEUED)
    }

    /// Rows the server is working on, oldest first.
    pub fn transcriptions_processing(&self) -> Result<Vec<TranscriptionRow>> {
        self.rows_with_status(TR_PROCESSING)
    }

    fn rows_with_status(&self, status: &str) -> Result<Vec<TranscriptionRow>> {
        let conn = self.conn();
        let mut stmt = conn.prepare(
            "SELECT * FROM transcription_queue WHERE status = ?1 ORDER BY created_at, rowid",
        )?;
        let rows = stmt.query_map([status], map_row)?;
        Ok(rows.collect::<rusqlite::Result<_>>()?)
    }

    /// Whether the sync has anything to do for the transcriptions.
    pub fn has_active_transcriptions(&self) -> Result<bool> {
        Ok(self.conn().query_row(
            "SELECT EXISTS(SELECT 1 FROM transcription_queue
                           WHERE status IN ('queued', 'uploading', 'processing'))",
            [],
            |row| row.get(0),
        )?)
    }

    /// An upload cut short by a crash starts over (see `reset_uploading_documents`).
    pub fn reset_uploading_transcriptions(&self) -> Result<usize> {
        Ok(self.conn().execute(
            "UPDATE transcription_queue SET status = 'queued' WHERE status = 'uploading'",
            [],
        )?)
    }

    /// Claims a row for an upload; `false` when it is gone or not queued any more.
    pub fn claim_transcription(&self, id: &str) -> Result<bool> {
        Ok(self.conn().execute(
            "UPDATE transcription_queue SET status = 'uploading', updated_at = ?2
             WHERE id = ?1 AND status = 'queued'",
            params![id, now()],
        )? > 0)
    }

    pub fn set_transcription_state(
        &self,
        id: &str,
        status: &str,
        error: Option<&str>,
        bump_attempts: bool,
    ) -> Result<()> {
        self.conn().execute(
            "UPDATE transcription_queue
             SET status = ?2, error = ?3, attempts = attempts + ?4, updated_at = ?5
             WHERE id = ?1",
            params![id, status, error, i64::from(bump_attempts), now()],
        )?;
        Ok(())
    }

    /// The server's file id (written right after the upload session) and whether
    /// the bytes reached the storage.
    pub fn set_transcription_file(
        &self,
        id: &str,
        server_file_id: Option<i64>,
        uploaded: bool,
    ) -> Result<()> {
        self.conn().execute(
            "UPDATE transcription_queue SET server_file_id = ?2, uploaded = ?3 WHERE id = ?1",
            params![id, server_file_id, i64::from(uploaded)],
        )?;
        Ok(())
    }

    /// The confirm went through: the server has the file and works on it.
    pub fn mark_transcription_confirmed(
        &self,
        id: &str,
        server_job_id: i64,
        server_status: &str,
    ) -> Result<()> {
        self.conn().execute(
            "UPDATE transcription_queue
             SET status = 'processing', uploaded = 1, server_job_id = ?2,
                 server_status = ?3, error = NULL, updated_at = ?4
             WHERE id = ?1",
            params![id, server_job_id, server_status, now()],
        )?;
        Ok(())
    }

    pub fn set_transcription_server_status(&self, id: &str, server_status: &str) -> Result<()> {
        self.conn().execute(
            "UPDATE transcription_queue SET server_status = ?2, updated_at = ?3
             WHERE id = ?1 AND server_status IS NOT ?2",
            params![id, server_status, now()],
        )?;
        Ok(())
    }

    /// The transcript is ready: keep it here to be read offline.
    pub fn finish_transcription(
        &self,
        id: &str,
        server_status: &str,
        transcript: &StoredTranscript,
    ) -> Result<()> {
        let json = serde_json::to_string(transcript)?;
        self.conn().execute(
            "UPDATE transcription_queue
             SET status = 'done', server_status = ?2, transcript_json = ?3,
                 error = NULL, updated_at = ?4
             WHERE id = ?1",
            params![id, server_status, json, now()],
        )?;
        Ok(())
    }

    /// Deletes the row (in any state); the path of its local copy, if it was there.
    pub fn remove_transcription(&self, id: &str) -> Result<Option<String>> {
        let conn = self.conn();
        let path: Option<String> = conn
            .query_row(
                "SELECT local_path FROM transcription_queue WHERE id = ?1",
                [id],
                |row| row.get(0),
            )
            .optional()?;
        conn.execute("DELETE FROM transcription_queue WHERE id = ?1", [id])?;
        Ok(path)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn add(db: &MeetingDb, id: &str) -> TranscriptionItem {
        db.insert_transcription(id, "a.mp3", "/x/a.mp3", 10, TR_QUEUED, None)
            .unwrap()
    }

    #[test]
    fn rows_are_listed_newest_first_without_transcripts() {
        let db = MeetingDb::open_in_memory().unwrap();
        add(&db, "a");
        add(&db, "b");
        let list = db.list_transcriptions().unwrap();
        assert_eq!(
            list.iter().map(|i| i.id.as_str()).collect::<Vec<_>>(),
            ["b", "a"]
        );
        assert_eq!(list[0].status, TR_QUEUED);
        assert!(db.has_active_transcriptions().unwrap());
        assert_eq!(db.transcriptions_to_send().unwrap().len(), 2);
    }

    #[test]
    fn a_row_goes_through_the_states_to_done() {
        let db = MeetingDb::open_in_memory().unwrap();
        add(&db, "a");
        assert!(db.claim_transcription("a").unwrap());
        assert!(!db.claim_transcription("a").unwrap());
        assert!(db.transcriptions_to_send().unwrap().is_empty());

        db.set_transcription_file("a", Some(7), false).unwrap();
        db.set_transcription_file("a", Some(7), true).unwrap();
        // A crash: the row is queued again and resumes with the confirm.
        assert_eq!(db.reset_uploading_transcriptions().unwrap(), 1);
        let row = &db.transcriptions_to_send().unwrap()[0];
        assert_eq!(row.server_file_id, Some(7));
        assert!(row.uploaded);

        db.mark_transcription_confirmed("a", 55, "uploaded")
            .unwrap();
        let row = &db.transcriptions_processing().unwrap()[0];
        assert_eq!(row.server_job_id, Some(55));
        db.set_transcription_server_status("a", "transcribing")
            .unwrap();
        let item = db.get_transcription_item("a").unwrap().unwrap();
        assert_eq!(item.status, TR_PROCESSING);
        assert_eq!(item.server_status.as_deref(), Some("transcribing"));

        let transcript = StoredTranscript {
            text: "Привет".into(),
            segments: vec![TranscriptSegment {
                speaker: "speaker_0".into(),
                start: 0.0,
                end: 1.5,
                text: "Привет".into(),
            }],
        };
        db.finish_transcription("a", "done", &transcript).unwrap();
        assert!(!db.has_active_transcriptions().unwrap());
        let detail = db.get_transcription_detail("a").unwrap().unwrap();
        assert_eq!(detail.item.status, "done");
        assert_eq!(detail.text, "Привет");
        assert_eq!(detail.segments, transcript.segments);
    }

    #[test]
    fn errors_are_kept_and_rows_can_be_removed_in_any_state() {
        let db = MeetingDb::open_in_memory().unwrap();
        add(&db, "a");
        add(&db, "b");
        db.claim_transcription("a").unwrap();
        db.set_transcription_state("a", TR_ERROR, Some("отказ"), true)
            .unwrap();
        let item = db.get_transcription_item("a").unwrap().unwrap();
        assert_eq!(item.status, TR_ERROR);
        assert_eq!(item.error.as_deref(), Some("отказ"));
        assert!(db
            .get_transcription_detail("a")
            .unwrap()
            .unwrap()
            .text
            .is_empty());

        db.claim_transcription("b").unwrap();
        assert_eq!(
            db.remove_transcription("b").unwrap().as_deref(),
            Some("/x/a.mp3")
        );
        assert_eq!(db.remove_transcription("b").unwrap(), None);
        assert_eq!(db.list_transcriptions().unwrap().len(), 1);
        assert!(db.get_transcription_detail("b").unwrap().is_none());
    }
}
