//! `meetings.db`: meetings, recognized segments and notes. The sync columns
//! are maintained by `managers::sync` (see `db_sync.rs`).

use anyhow::{Context, Result};
use rusqlite::{params, Connection, OptionalExtension, Row};
use rusqlite_migration::{Migrations, M};
use serde::{Deserialize, Serialize};
use specta::Type;
use std::path::Path;
use std::sync::{Mutex, MutexGuard};

pub(super) static MIGRATIONS: &[M] = &[
    M::up(
        "CREATE TABLE meetings (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        capture_mode TEXT NOT NULL,
        started_at TEXT NOT NULL,
        ended_at TEXT,
        status TEXT NOT NULL,
        duration_seconds REAL NOT NULL DEFAULT 0,
        server_meeting_id INTEGER,
        sync_state TEXT NOT NULL DEFAULT 'pending',
        sync_error TEXT,
        synced_at TEXT,
        customer_id INTEGER,
        object_id INTEGER
    );
    CREATE TABLE segments (
        id TEXT PRIMARY KEY,
        meeting_id TEXT NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
        channel TEXT NOT NULL,
        start_time REAL NOT NULL,
        end_time REAL NOT NULL,
        text TEXT NOT NULL,
        created_at TEXT NOT NULL,
        synced INTEGER NOT NULL DEFAULT 0
    );
    CREATE INDEX idx_segments_meeting ON segments(meeting_id, start_time);
    CREATE TABLE notes (
        id TEXT PRIMARY KEY,
        meeting_id TEXT NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
        at_seconds REAL NOT NULL,
        text TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE INDEX idx_notes_meeting ON notes(meeting_id, at_seconds);",
    ),
    // Server sync: what became of the audio upload, and the channels already
    // confirmed on the server (comma separated).
    M::up(
        "ALTER TABLE meetings ADD COLUMN audio_state TEXT NOT NULL DEFAULT 'pending';
    ALTER TABLE meetings ADD COLUMN audio_done TEXT NOT NULL DEFAULT '';",
    ),
    // Library: the project's names next to its ids (`customer_id`/`object_id` are
    // there since the first version), the offline cache of the site's meetings
    // and projects, and the full-text index over local and server meetings.
    // `search_map` remembers the FTS row of each entry, so a re-index does not
    // scan the whole index.
    M::up(
        "ALTER TABLE meetings ADD COLUMN customer_name TEXT;
    ALTER TABLE meetings ADD COLUMN object_name TEXT;
    CREATE TABLE server_library (
        meeting_id INTEGER PRIMARY KEY,
        json TEXT NOT NULL,
        fetched_at TEXT NOT NULL
    );
    CREATE TABLE server_projects (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        json TEXT NOT NULL,
        fetched_at TEXT NOT NULL
    );
    CREATE TABLE server_views (
        meeting_id INTEGER PRIMARY KEY,
        json TEXT NOT NULL,
        fetched_at TEXT NOT NULL
    );
    CREATE VIRTUAL TABLE search_index USING fts5(
        kind UNINDEXED, ref_id UNINDEXED, title, body, tokenize = 'unicode61'
    );
    CREATE TABLE search_map (
        kind TEXT NOT NULL,
        ref_id TEXT NOT NULL,
        fts_rowid INTEGER NOT NULL,
        PRIMARY KEY (kind, ref_id)
    );",
    ),
    // Meeting context, as on the site. `context_dirty`: the server has not got
    // the latest context yet (see `db_context.rs`).
    M::up(
        "ALTER TABLE meetings ADD COLUMN negotiation_type TEXT;
    ALTER TABLE meetings ADD COLUMN key_terms TEXT;
    ALTER TABLE meetings ADD COLUMN opponent_weaknesses TEXT;
    ALTER TABLE meetings ADD COLUMN context_dirty INTEGER NOT NULL DEFAULT 0;",
    ),
    // Voices of a meeting ("Голос N", see `voice/` and `db_voices.rs`): the
    // segment's voice, and per meeting each voice's side, its centroid (JSON
    // vector) and whether the server has the side (`side_synced`).
    M::up(
        "ALTER TABLE segments ADD COLUMN voice TEXT;
    CREATE TABLE meeting_voices (
        meeting_id TEXT NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
        label TEXT NOT NULL,
        side TEXT,
        centroid TEXT NOT NULL,
        count INTEGER NOT NULL,
        first_channel TEXT NOT NULL,
        side_synced INTEGER NOT NULL DEFAULT 0,
        created_at INTEGER NOT NULL,
        PRIMARY KEY (meeting_id, label)
    );",
    ),
    // Sources of a meeting (files dropped onto the window): the upload queue.
    // `meeting_id` is the local meeting (`NULL` for a meeting of the site opened
    // from the library), `server_meeting_id` is filled once the server has the
    // meeting. States: pending, uploading, uploaded, error (see `db_documents.rs`).
    M::up(
        "CREATE TABLE document_queue (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        meeting_id TEXT REFERENCES meetings(id) ON DELETE CASCADE,
        server_meeting_id INTEGER,
        file_path TEXT NOT NULL,
        original_name TEXT NOT NULL,
        size INTEGER NOT NULL,
        mime TEXT NOT NULL,
        state TEXT NOT NULL DEFAULT 'pending',
        server_document_id INTEGER,
        error TEXT,
        attempts INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    );
    CREATE INDEX idx_document_queue_meeting ON document_queue(meeting_id);
    CREATE INDEX idx_document_queue_server ON document_queue(server_meeting_id);",
    ),
];

/// `online`: microphone plus system sound (two channels); `in_person`: one
/// microphone for everybody in the room.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize, Type)]
#[serde(rename_all = "snake_case")]
pub enum CaptureMode {
    Online,
    InPerson,
}

impl CaptureMode {
    fn as_str(self) -> &'static str {
        match self {
            Self::Online => "online",
            Self::InPerson => "in_person",
        }
    }

    fn parse(value: &str) -> Option<Self> {
        match value {
            "online" => Some(Self::Online),
            "in_person" => Some(Self::InPerson),
            _ => None,
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize, Type)]
#[serde(rename_all = "snake_case")]
pub enum MeetingStatus {
    Recording,
    Stopped,
    /// The app went away while recording; the audio up to then is on disk.
    Interrupted,
}

impl MeetingStatus {
    fn as_str(self) -> &'static str {
        match self {
            Self::Recording => "recording",
            Self::Stopped => "stopped",
            Self::Interrupted => "interrupted",
        }
    }

    fn parse(value: &str) -> Option<Self> {
        match value {
            "recording" => Some(Self::Recording),
            "stopped" => Some(Self::Stopped),
            "interrupted" => Some(Self::Interrupted),
            _ => None,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize, Type)]
pub struct MeetingInfo {
    pub id: String,
    pub title: String,
    pub capture_mode: CaptureMode,
    pub started_at: String,
    pub ended_at: Option<String>,
    pub status: MeetingStatus,
    pub duration_seconds: f64,
    pub server_meeting_id: Option<i64>,
    pub sync_state: String,
    pub sync_error: Option<String>,
    pub synced_at: Option<String>,
    pub customer_id: Option<i64>,
    pub object_id: Option<i64>,
    /// Names of the project, for showing it without the server's reference book.
    pub customer_name: Option<String>,
    pub object_name: Option<String>,
    /// Audio upload to the server: `pending`, `done`, `none` (nothing recorded),
    /// `no_storage` (the server has no file
    /// storage), `skipped` (a channel is too big or refused).
    pub audio_state: String,
    /// Meeting context, as on the site: type of the negotiation, key terms and
    /// goals, the opponent's weak points. `None`: not set.
    pub negotiation_type: Option<String>,
    pub key_terms: Option<String>,
    pub opponent_weaknesses: Option<String>,
    /// Link to the meeting on the site; filled in for synced meetings when
    /// an account is signed in. Not stored.
    pub web_url: Option<String>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize, Type)]
pub struct Segment {
    pub id: String,
    pub meeting_id: String,
    /// `mic`, `system`, or `mixed` for an in-person meeting.
    pub channel: String,
    pub start_time: f64,
    pub end_time: f64,
    pub text: String,
    pub created_at: String,
    pub synced: bool,
    /// Whose voice it is ("Голос 1"); `None`: not told apart (no voice model,
    /// a too short phrase, a meeting from before voices).
    pub voice: Option<String>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize, Type)]
pub struct Note {
    pub id: String,
    pub meeting_id: String,
    pub at_seconds: f64,
    pub text: String,
    pub updated_at: String,
}

fn column_error(column: usize, value: &str) -> rusqlite::Error {
    rusqlite::Error::FromSqlConversionFailure(
        column,
        rusqlite::types::Type::Text,
        format!("unexpected value '{value}'").into(),
    )
}

pub(super) fn map_meeting(row: &Row<'_>) -> rusqlite::Result<MeetingInfo> {
    let mode: String = row.get("capture_mode")?;
    let status: String = row.get("status")?;
    Ok(MeetingInfo {
        id: row.get("id")?,
        title: row.get("title")?,
        capture_mode: CaptureMode::parse(&mode).ok_or_else(|| column_error(2, &mode))?,
        started_at: row.get("started_at")?,
        ended_at: row.get("ended_at")?,
        status: MeetingStatus::parse(&status).ok_or_else(|| column_error(5, &status))?,
        duration_seconds: row.get("duration_seconds")?,
        server_meeting_id: row.get("server_meeting_id")?,
        sync_state: row.get("sync_state")?,
        sync_error: row.get("sync_error")?,
        synced_at: row.get("synced_at")?,
        customer_id: row.get("customer_id")?,
        object_id: row.get("object_id")?,
        customer_name: row.get("customer_name")?,
        object_name: row.get("object_name")?,
        audio_state: row.get("audio_state")?,
        negotiation_type: row.get("negotiation_type")?,
        key_terms: row.get("key_terms")?,
        opponent_weaknesses: row.get("opponent_weaknesses")?,
        web_url: None,
    })
}

pub(super) fn map_segment(row: &Row<'_>) -> rusqlite::Result<Segment> {
    Ok(Segment {
        id: row.get("id")?,
        meeting_id: row.get("meeting_id")?,
        channel: row.get("channel")?,
        start_time: row.get("start_time")?,
        end_time: row.get("end_time")?,
        text: row.get("text")?,
        created_at: row.get("created_at")?,
        synced: row.get::<_, i64>("synced")? != 0,
        voice: row.get("voice")?,
    })
}

fn map_note(row: &Row<'_>) -> rusqlite::Result<Note> {
    Ok(Note {
        id: row.get("id")?,
        meeting_id: row.get("meeting_id")?,
        at_seconds: row.get("at_seconds")?,
        text: row.get("text")?,
        updated_at: row.get("updated_at")?,
    })
}

pub struct MeetingDb {
    conn: Mutex<Connection>,
}

impl MeetingDb {
    pub fn open(path: &Path) -> Result<Self> {
        let conn =
            Connection::open(path).with_context(|| format!("cannot open {}", path.display()))?;
        Self::init(conn)
    }

    #[cfg(test)]
    pub fn open_in_memory() -> Result<Self> {
        Self::init(Connection::open_in_memory()?)
    }

    fn init(mut conn: Connection) -> Result<Self> {
        // WAL keeps readers (the UI) from waiting on the recognizer's inserts.
        conn.execute_batch("PRAGMA journal_mode = WAL; PRAGMA foreign_keys = ON;")?;
        let migrations = Migrations::new(MIGRATIONS.to_vec());
        #[cfg(debug_assertions)]
        migrations.validate().expect("Invalid meeting migrations");
        migrations.to_latest(&mut conn)?;
        Ok(Self {
            conn: Mutex::new(conn),
        })
    }

    pub(crate) fn conn(&self) -> MutexGuard<'_, Connection> {
        self.conn.lock().unwrap_or_else(|e| e.into_inner())
    }

    pub fn insert_meeting(&self, meeting: &MeetingInfo) -> Result<()> {
        self.conn().execute(
            "INSERT INTO meetings (id, title, capture_mode, started_at, ended_at, status,
                duration_seconds, server_meeting_id, sync_state, sync_error, synced_at,
                customer_id, object_id, customer_name, object_name,
                negotiation_type, key_terms, opponent_weaknesses)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, ?14, ?15,
                ?16, ?17, ?18)",
            params![
                meeting.id,
                meeting.title,
                meeting.capture_mode.as_str(),
                meeting.started_at,
                meeting.ended_at,
                meeting.status.as_str(),
                meeting.duration_seconds,
                meeting.server_meeting_id,
                meeting.sync_state,
                meeting.sync_error,
                meeting.synced_at,
                meeting.customer_id,
                meeting.object_id,
                meeting.customer_name,
                meeting.object_name,
                meeting.negotiation_type,
                meeting.key_terms,
                meeting.opponent_weaknesses,
            ],
        )?;
        Ok(())
    }

    pub fn get_meeting(&self, id: &str) -> Result<Option<MeetingInfo>> {
        Ok(self
            .conn()
            .query_row("SELECT * FROM meetings WHERE id = ?1", [id], map_meeting)
            .optional()?)
    }

    /// Newest first.
    pub fn list_meetings(&self) -> Result<Vec<MeetingInfo>> {
        let conn = self.conn();
        let mut stmt = conn.prepare("SELECT * FROM meetings ORDER BY started_at DESC, id")?;
        let rows = stmt.query_map([], map_meeting)?;
        Ok(rows.collect::<rusqlite::Result<_>>()?)
    }

    /// A stopped or interrupted meeting goes back to recording.
    pub fn mark_recording(&self, id: &str) -> Result<()> {
        self.conn().execute(
            "UPDATE meetings SET status = 'recording', ended_at = NULL WHERE id = ?1",
            [id],
        )?;
        Ok(())
    }

    pub fn finish_meeting(
        &self,
        id: &str,
        status: MeetingStatus,
        ended_at: &str,
        duration_seconds: f64,
    ) -> Result<()> {
        self.conn().execute(
            "UPDATE meetings SET status = ?2, ended_at = ?3, duration_seconds = ?4 WHERE id = ?1",
            params![id, status.as_str(), ended_at, duration_seconds],
        )?;
        Ok(())
    }

    /// Ids of meetings still marked as recording: nothing is recording right
    /// after the app starts, so these were cut off.
    pub fn recording_meeting_ids(&self) -> Result<Vec<String>> {
        let conn = self.conn();
        let mut stmt = conn.prepare("SELECT id FROM meetings WHERE status = 'recording'")?;
        let rows = stmt.query_map([], |row| row.get(0))?;
        Ok(rows.collect::<rusqlite::Result<_>>()?)
    }

    pub fn rename_meeting(&self, id: &str, title: &str) -> Result<bool> {
        Ok(self
            .conn()
            .execute("UPDATE meetings SET title = ?2 WHERE id = ?1", [id, title])?
            > 0)
    }

    /// Sets or clears the meeting's project. `false`: no such meeting.
    pub fn set_meeting_project(
        &self,
        id: &str,
        customer_id: Option<i64>,
        customer_name: Option<&str>,
        object_id: Option<i64>,
        object_name: Option<&str>,
    ) -> Result<bool> {
        Ok(self.conn().execute(
            "UPDATE meetings SET customer_id = ?2, customer_name = ?3,
                object_id = ?4, object_name = ?5 WHERE id = ?1",
            params![id, customer_id, customer_name, object_id, object_name],
        )? > 0)
    }

    /// Removes the meeting with its segments and notes.
    pub fn delete_meeting(&self, id: &str) -> Result<bool> {
        Ok(self
            .conn()
            .execute("DELETE FROM meetings WHERE id = ?1", [id])?
            > 0)
    }

    pub fn insert_segment(&self, segment: &Segment) -> Result<()> {
        self.conn().execute(
            "INSERT INTO segments (id, meeting_id, channel, start_time, end_time, text,
                created_at, synced, voice)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9)",
            params![
                segment.id,
                segment.meeting_id,
                segment.channel,
                segment.start_time,
                segment.end_time,
                segment.text,
                segment.created_at,
                i64::from(segment.synced),
                segment.voice,
            ],
        )?;
        Ok(())
    }

    pub fn list_segments(&self, meeting_id: &str) -> Result<Vec<Segment>> {
        let conn = self.conn();
        let mut stmt = conn.prepare(
            "SELECT * FROM segments WHERE meeting_id = ?1 ORDER BY start_time, channel, id",
        )?;
        let rows = stmt.query_map([meeting_id], map_segment)?;
        Ok(rows.collect::<rusqlite::Result<_>>()?)
    }

    pub fn upsert_note(&self, note: &Note) -> Result<()> {
        self.conn().execute(
            "INSERT INTO notes (id, meeting_id, at_seconds, text, updated_at)
             VALUES (?1, ?2, ?3, ?4, ?5)
             ON CONFLICT(id) DO UPDATE SET
                at_seconds = excluded.at_seconds,
                text = excluded.text,
                updated_at = excluded.updated_at",
            params![
                note.id,
                note.meeting_id,
                note.at_seconds,
                note.text,
                note.updated_at
            ],
        )?;
        Ok(())
    }

    pub fn list_notes(&self, meeting_id: &str) -> Result<Vec<Note>> {
        let conn = self.conn();
        let mut stmt =
            conn.prepare("SELECT * FROM notes WHERE meeting_id = ?1 ORDER BY at_seconds, id")?;
        let rows = stmt.query_map([meeting_id], map_note)?;
        Ok(rows.collect::<rusqlite::Result<_>>()?)
    }

    pub fn delete_note(&self, id: &str) -> Result<bool> {
        Ok(self
            .conn()
            .execute("DELETE FROM notes WHERE id = ?1", [id])?
            > 0)
    }
}

#[cfg(test)]
pub(super) fn sample_meeting(id: &str, started_at: &str) -> MeetingInfo {
    MeetingInfo {
        id: id.to_string(),
        title: format!("Встреча {id}"),
        capture_mode: CaptureMode::Online,
        started_at: started_at.to_string(),
        ended_at: None,
        status: MeetingStatus::Recording,
        duration_seconds: 0.0,
        server_meeting_id: None,
        sync_state: "pending".to_string(),
        sync_error: None,
        synced_at: None,
        customer_id: None,
        object_id: None,
        customer_name: None,
        object_name: None,
        audio_state: "pending".to_string(),
        negotiation_type: None,
        key_terms: None,
        opponent_weaknesses: None,
        web_url: None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn segment(id: &str, meeting: &str, start: f64, text: &str) -> Segment {
        Segment {
            id: id.to_string(),
            meeting_id: meeting.to_string(),
            channel: "mic".to_string(),
            start_time: start,
            end_time: start + 1.0,
            text: text.to_string(),
            created_at: "2026-01-01T00:00:00.000Z".to_string(),
            synced: false,
            voice: None,
        }
    }

    #[test]
    fn creates_schema_and_is_idempotent_on_reopen() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("meetings.db");
        let db = MeetingDb::open(&path).unwrap();
        db.insert_meeting(&sample_meeting("a", "2026-01-01T10:00:00.000Z"))
            .unwrap();
        drop(db);

        let db = MeetingDb::open(&path).unwrap();
        assert_eq!(db.list_meetings().unwrap().len(), 1);
        let version: i32 = db
            .conn()
            .pragma_query_value(None, "user_version", |row| row.get(0))
            .unwrap();
        assert_eq!(version, MIGRATIONS.len() as i32);
    }

    #[test]
    fn meeting_crud_and_ordering() {
        let db = MeetingDb::open_in_memory().unwrap();
        db.insert_meeting(&sample_meeting("old", "2026-01-01T10:00:00.000Z"))
            .unwrap();
        let mut newer = sample_meeting("new", "2026-02-01T10:00:00.000Z");
        newer.capture_mode = CaptureMode::InPerson;
        newer.customer_id = Some(7);
        db.insert_meeting(&newer).unwrap();

        let list = db.list_meetings().unwrap();
        assert_eq!(
            list.iter().map(|m| m.id.as_str()).collect::<Vec<_>>(),
            ["new", "old"]
        );
        assert_eq!(db.get_meeting("new").unwrap().unwrap(), newer);
        assert!(db.get_meeting("missing").unwrap().is_none());

        assert!(db.rename_meeting("old", "Планёрка").unwrap());
        assert_eq!(db.get_meeting("old").unwrap().unwrap().title, "Планёрка");
        assert!(!db.rename_meeting("missing", "x").unwrap());

        db.finish_meeting(
            "old",
            MeetingStatus::Stopped,
            "2026-01-01T11:00:00.000Z",
            3600.0,
        )
        .unwrap();
        let old = db.get_meeting("old").unwrap().unwrap();
        assert_eq!(old.status, MeetingStatus::Stopped);
        assert_eq!(old.duration_seconds, 3600.0);
        assert_eq!(old.ended_at.as_deref(), Some("2026-01-01T11:00:00.000Z"));

        db.mark_recording("old").unwrap();
        let old = db.get_meeting("old").unwrap().unwrap();
        assert_eq!(old.status, MeetingStatus::Recording);
        assert!(old.ended_at.is_none());
    }

    #[test]
    fn segments_and_notes_belong_to_meeting_and_cascade() {
        let db = MeetingDb::open_in_memory().unwrap();
        db.insert_meeting(&sample_meeting("m", "2026-01-01T10:00:00.000Z"))
            .unwrap();
        db.insert_meeting(&sample_meeting("other", "2026-01-02T10:00:00.000Z"))
            .unwrap();
        db.insert_segment(&segment("s2", "m", 5.0, "второй"))
            .unwrap();
        db.insert_segment(&segment("s1", "m", 1.0, "первый"))
            .unwrap();
        db.insert_segment(&segment("s3", "other", 0.0, "чужой"))
            .unwrap();

        let texts: Vec<String> = db
            .list_segments("m")
            .unwrap()
            .into_iter()
            .map(|s| s.text)
            .collect();
        assert_eq!(texts, ["первый", "второй"]);

        let note = Note {
            id: "n1".into(),
            meeting_id: "m".into(),
            at_seconds: 12.5,
            text: "срок до пятницы".into(),
            updated_at: "2026-01-01T10:01:00.000Z".into(),
        };
        db.upsert_note(&note).unwrap();
        let edited = Note {
            text: "срок до четверга".into(),
            updated_at: "2026-01-01T10:02:00.000Z".into(),
            ..note.clone()
        };
        db.upsert_note(&edited).unwrap();
        assert_eq!(db.list_notes("m").unwrap(), vec![edited.clone()]);

        // A note for a meeting that does not exist is refused.
        let orphan = Note {
            id: "n2".into(),
            meeting_id: "ghost".into(),
            ..note.clone()
        };
        assert!(db.upsert_note(&orphan).is_err());

        assert!(db.delete_note("n1").unwrap());
        assert!(!db.delete_note("n1").unwrap());
        db.upsert_note(&note).unwrap();

        assert!(db.delete_meeting("m").unwrap());
        assert!(db.list_segments("m").unwrap().is_empty());
        assert!(db.list_notes("m").unwrap().is_empty());
        assert_eq!(db.list_segments("other").unwrap().len(), 1);
    }

    #[test]
    fn recording_meetings_are_listed_for_recovery() {
        let db = MeetingDb::open_in_memory().unwrap();
        db.insert_meeting(&sample_meeting("live", "2026-01-01T10:00:00.000Z"))
            .unwrap();
        let mut done = sample_meeting("done", "2026-01-01T09:00:00.000Z");
        done.status = MeetingStatus::Stopped;
        db.insert_meeting(&done).unwrap();
        assert_eq!(db.recording_meeting_ids().unwrap(), vec!["live"]);
    }
}
