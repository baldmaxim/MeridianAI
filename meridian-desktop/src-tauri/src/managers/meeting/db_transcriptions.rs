//! The queue of «Расшифровка файлов» (`transcription_queue` in `meetings.db`):
//! audio files copied into the app's data folder that go to the server, are
//! recognized there, and whose transcript is kept here to be read offline.

use std::collections::HashSet;

use anyhow::{Context, Result};
use chrono::{DateTime, NaiveDateTime, SecondsFormat, Utc};
use rusqlite::{params, OptionalExtension, Row};
use serde::{Deserialize, Serialize};
use specta::Type;

use super::db::MeetingDb;
use super::short_id;

pub const TR_QUEUED: &str = "queued";
pub const TR_PROCESSING: &str = "processing";
pub const TR_ERROR: &str = "error";

fn now() -> String {
    Utc::now().to_rfc3339_opts(SecondsFormat::Millis, true)
}

/// A time of the server as the rows keep it (`now()` format, so that the list
/// sorts together). The server sends a naive UTC time with microseconds
/// (`2026-11-20T10:00:00.123456`, the fraction may be missing); a time with an
/// offset is taken as it is. An unreadable one becomes the current time.
fn normalize_server_time(raw: &str) -> String {
    let raw = raw.trim();
    let parsed = NaiveDateTime::parse_from_str(raw, "%Y-%m-%dT%H:%M:%S%.f")
        .map(|naive| naive.and_utc())
        .or_else(|_| DateTime::parse_from_rfc3339(raw).map(|t| t.with_timezone(&Utc)));
    match parsed {
        Ok(time) => time.to_rfc3339_opts(SecondsFormat::Millis, true),
        Err(_) => now(),
    }
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
                &format!(
                    "SELECT {ITEM_COLUMNS} FROM transcription_queue WHERE id = ?1 AND hidden = 0"
                ),
                [id],
                map_item,
            )
            .optional()?)
    }

    /// Newest first, without the transcripts.
    pub fn list_transcriptions(&self) -> Result<Vec<TranscriptionItem>> {
        let conn = self.conn();
        let mut stmt = conn.prepare(&format!(
            "SELECT {ITEM_COLUMNS} FROM transcription_queue WHERE hidden = 0
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
            "SELECT * FROM transcription_queue WHERE status = ?1 AND hidden = 0
             ORDER BY created_at, rowid",
        )?;
        let rows = stmt.query_map([status], map_row)?;
        Ok(rows.collect::<rusqlite::Result<_>>()?)
    }

    /// Whether the sync has anything to do for the transcriptions.
    pub fn has_active_transcriptions(&self) -> Result<bool> {
        Ok(self.conn().query_row(
            "SELECT EXISTS(SELECT 1 FROM transcription_queue
                           WHERE status IN ('queued', 'uploading', 'processing')
                             AND hidden = 0)",
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
        let mut conn = self.conn();
        let tx = conn.transaction()?;
        // A lost confirm answer: the pull may have brought this job as a row of
        // its own. That row goes; if the user had removed it, this one is hidden too.
        let removed_by_user: bool = tx.query_row(
            "SELECT EXISTS (SELECT 1 FROM transcription_queue
                            WHERE server_job_id = ?1 AND id != ?2
                              AND local_path = '' AND hidden = 1)",
            params![server_job_id, id],
            |row| row.get(0),
        )?;
        tx.execute(
            "DELETE FROM transcription_queue
             WHERE server_job_id = ?1 AND id != ?2 AND local_path = '' AND hidden = 0",
            params![server_job_id, id],
        )?;
        tx.execute(
            "UPDATE transcription_queue
             SET status = 'processing', uploaded = 1, server_job_id = ?2,
                 server_status = ?3, error = NULL, hidden = hidden OR ?5, updated_at = ?4
             WHERE id = ?1",
            params![id, server_job_id, server_status, now(), removed_by_user],
        )?;
        tx.commit()?;
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

    /// Ids of the server's jobs that have a row, hidden ones included.
    pub fn known_server_job_ids(&self) -> Result<HashSet<i64>> {
        let conn = self.conn();
        let mut stmt = conn.prepare(
            "SELECT server_job_id FROM transcription_queue WHERE server_job_id IS NOT NULL",
        )?;
        let ids = stmt.query_map([], |row| row.get(0))?;
        Ok(ids.collect::<rusqlite::Result<_>>()?)
    }

    /// A row for a job the server has but this PC does not (the site, another
    /// PC): no local copy, the bytes are on the server already. `false` when the
    /// job has a row. `created_at` is the server's time.
    #[allow(clippy::too_many_arguments)]
    pub fn insert_server_transcription(
        &self,
        server_job_id: i64,
        filename: &str,
        size: i64,
        status: &str,
        server_status: &str,
        error: Option<&str>,
        created_at: &str,
    ) -> Result<bool> {
        Ok(self.conn().execute(
            "INSERT INTO transcription_queue
                (id, filename, local_path, size, status, uploaded, server_job_id,
                 server_status, error, created_at, updated_at)
             SELECT ?1, ?2, '', ?3, ?4, 1, ?5, ?6, ?7, ?8, ?9
             WHERE NOT EXISTS (SELECT 1 FROM transcription_queue WHERE server_job_id = ?5)",
            params![
                short_id(),
                filename,
                size.max(0),
                status,
                server_job_id,
                server_status,
                error,
                normalize_server_time(created_at),
                now()
            ],
        )? > 0)
    }

    /// Takes the row out of the list (in any state); the path of its local copy,
    /// if it was there. A row of a job the server has is kept hidden, without
    /// the transcript, so that the pull does not bring the job back.
    pub fn remove_transcription(&self, id: &str) -> Result<Option<String>> {
        let conn = self.conn();
        let found: Option<(String, Option<i64>)> = conn
            .query_row(
                "SELECT local_path, server_job_id FROM transcription_queue WHERE id = ?1",
                [id],
                |row| Ok((row.get(0)?, row.get(1)?)),
            )
            .optional()?;
        let Some((path, server_job_id)) = found else {
            return Ok(None);
        };
        if server_job_id.is_some() {
            conn.execute(
                "UPDATE transcription_queue
                 SET hidden = 1, transcript_json = NULL, local_path = '', updated_at = ?2
                 WHERE id = ?1",
                params![id, now()],
            )?;
        } else {
            conn.execute("DELETE FROM transcription_queue WHERE id = ?1", [id])?;
        }
        Ok(Some(path))
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

    #[test]
    fn server_time_is_written_like_a_local_one() {
        for (raw, expected) in [
            ("2026-11-20T10:00:00.123456", "2026-11-20T10:00:00.123Z"),
            ("2026-11-20T10:00:00", "2026-11-20T10:00:00.000Z"),
            ("2026-11-20T10:00:00.5Z", "2026-11-20T10:00:00.500Z"),
            ("2026-11-20T15:00:00+05:00", "2026-11-20T10:00:00.000Z"),
        ] {
            assert_eq!(normalize_server_time(raw), expected, "{raw}");
        }
        assert!(normalize_server_time("мусор").ends_with('Z'));
    }

    #[test]
    fn a_server_job_gets_a_row_once_and_sorts_by_its_time() {
        let db = MeetingDb::open_in_memory().unwrap();
        add(&db, "local");
        assert!(db
            .insert_server_transcription(
                9,
                "site.mp3",
                2048,
                TR_PROCESSING,
                "done",
                None,
                "2020-01-01T00:00:00.5"
            )
            .unwrap());
        assert!(!db
            .insert_server_transcription(
                9,
                "site.mp3",
                2048,
                TR_PROCESSING,
                "done",
                None,
                "2020-01-01T00:00:00"
            )
            .unwrap());
        assert!(db.known_server_job_ids().unwrap().contains(&9));

        let list = db.list_transcriptions().unwrap();
        assert_eq!(list.len(), 2);
        assert_eq!(
            list[0].id, "local",
            "an old server job is below a new local file"
        );
        assert_eq!(list[1].filename, "site.mp3");
        assert_eq!(list[1].size, 2048);
        assert_eq!(list[1].created_at, "2020-01-01T00:00:00.500Z");
        // Waiting for the poll, never for an upload.
        let row = &db.transcriptions_processing().unwrap()[0];
        assert_eq!((row.server_job_id, row.uploaded), (Some(9), true));
        assert_eq!(db.transcriptions_to_send().unwrap().len(), 1);
        assert_eq!(db.transcriptions_to_send().unwrap()[0].id, "local");
    }

    #[test]
    fn removing_a_server_job_hides_it_and_keeps_its_id_known() {
        let db = MeetingDb::open_in_memory().unwrap();
        add(&db, "mine");
        db.mark_transcription_confirmed("mine", 5, "uploaded")
            .unwrap();
        db.finish_transcription(
            "mine",
            "done",
            &StoredTranscript {
                text: "Текст".into(),
                segments: vec![],
            },
        )
        .unwrap();
        add(&db, "plain");
        db.insert_server_transcription(
            6,
            "b.mp3",
            1,
            TR_PROCESSING,
            "uploaded",
            None,
            "2026-01-01T00:00:00",
        )
        .unwrap();

        assert_eq!(
            db.remove_transcription("mine").unwrap().as_deref(),
            Some("/x/a.mp3")
        );
        assert!(db.remove_transcription("plain").unwrap().is_some());
        assert!(db.remove_transcription("nope").unwrap().is_none());
        // The tombstone: out of the list, the queues and the lookups, but known.
        let ids = db.known_server_job_ids().unwrap();
        assert!(ids.contains(&5) && ids.contains(&6) && !ids.contains(&7));
        assert!(db.get_transcription_item("mine").unwrap().is_none());
        assert!(db.get_transcription_detail("mine").unwrap().is_none());
        assert_eq!(db.list_transcriptions().unwrap().len(), 1);
        db.remove_transcription("mine").unwrap();
        // The job 6 is still waiting for its poll; the hidden one is not.
        let waiting = db.transcriptions_processing().unwrap();
        assert_eq!(waiting.len(), 1);
        assert_eq!(waiting[0].server_job_id, Some(6));
        db.remove_transcription(&waiting[0].id).unwrap();
        assert!(!db.has_active_transcriptions().unwrap());
        let stored: Option<String> = db
            .conn()
            .query_row(
                "SELECT transcript_json FROM transcription_queue WHERE server_job_id = 5",
                [],
                |row| row.get(0),
            )
            .unwrap();
        assert!(stored.is_none());
    }

    #[test]
    fn a_confirm_after_a_lost_answer_does_not_leave_a_twin() {
        let db = MeetingDb::open_in_memory().unwrap();
        add(&db, "mine");
        // The pull brought the job 5 before the confirm answer came.
        db.insert_server_transcription(
            5,
            "a.mp3",
            10,
            TR_PROCESSING,
            "uploaded",
            None,
            "2026-01-01T00:00:00",
        )
        .unwrap();
        assert_eq!(db.list_transcriptions().unwrap().len(), 2);
        db.mark_transcription_confirmed("mine", 5, "uploaded")
            .unwrap();
        let list = db.list_transcriptions().unwrap();
        assert_eq!(list.len(), 1);
        assert_eq!(list[0].id, "mine");
        assert_eq!(db.transcriptions_processing().unwrap().len(), 1);

        // The twin was removed by the user: the own row goes too.
        add(&db, "other");
        db.insert_server_transcription(
            8,
            "b.mp3",
            10,
            TR_PROCESSING,
            "uploaded",
            None,
            "2026-01-01T00:00:00",
        )
        .unwrap();
        let twin = db
            .list_transcriptions()
            .unwrap()
            .into_iter()
            .find(|i| i.filename == "b.mp3")
            .unwrap();
        db.remove_transcription(&twin.id).unwrap();
        db.mark_transcription_confirmed("other", 8, "uploaded")
            .unwrap();
        assert!(db.get_transcription_item("other").unwrap().is_none());
        assert!(db.known_server_job_ids().unwrap().contains(&8));
        assert_eq!(db.list_transcriptions().unwrap().len(), 1);
    }
}
