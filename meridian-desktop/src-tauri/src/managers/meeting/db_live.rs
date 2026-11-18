//! Phrases the server recognized live (ElevenLabs): stored next to the local
//! ones, but already on the server, so the sync never sends them again.

use anyhow::Result;
use rusqlite::{params, OptionalExtension};

use super::db::{map_segment, MeetingDb, Segment};

/// A phrase as the server's live stream reports it.
#[derive(Clone, Debug, PartialEq)]
pub(super) struct ServerSegment {
    pub(super) meeting_id: String,
    /// The server's id; it is the local id as well, so a repeat is an update.
    pub(super) server_id: String,
    /// `mic`, `system` or `mixed`: the side the server named.
    pub(super) channel: String,
    pub(super) start_time: f64,
    pub(super) end_time: f64,
    pub(super) text: String,
    pub(super) language: Option<String>,
    pub(super) translation: Option<String>,
    pub(super) speaker: Option<String>,
    pub(super) created_at: String,
}

impl MeetingDb {
    /// Inserts the phrase, or updates the one with this server id (text and
    /// times follow the server; a language, translation or speaker the update
    /// lacks stays as it was). Returns the stored phrase.
    pub(super) fn upsert_server_segment(&self, seg: &ServerSegment) -> Result<Segment> {
        let conn = self.conn();
        conn.execute(
            "INSERT INTO segments (id, meeting_id, channel, start_time, end_time, text,
                created_at, synced, language, translation, speaker, server_id)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, 1, ?8, ?9, ?10, ?1)
             ON CONFLICT(id) DO UPDATE SET
                channel = excluded.channel,
                start_time = excluded.start_time,
                end_time = excluded.end_time,
                text = excluded.text,
                language = COALESCE(excluded.language, language),
                translation = COALESCE(excluded.translation, translation),
                speaker = COALESCE(excluded.speaker, speaker)
             WHERE segments.server_id IS NOT NULL",
            params![
                seg.server_id,
                seg.meeting_id,
                seg.channel,
                seg.start_time,
                seg.end_time,
                seg.text,
                seg.created_at,
                seg.language,
                seg.translation,
                seg.speaker,
            ],
        )?;
        Ok(conn.query_row(
            "SELECT * FROM segments WHERE id = ?1",
            [&seg.server_id],
            map_segment,
        )?)
    }

    /// The side the server named for a phrase (`mic` or `system`). `None`: no
    /// such phrase here.
    pub(super) fn set_segment_channel(
        &self,
        meeting_id: &str,
        server_id: &str,
        channel: &str,
    ) -> Result<Option<Segment>> {
        let conn = self.conn();
        let changed = conn.execute(
            "UPDATE segments SET channel = ?3
             WHERE id = ?2 AND meeting_id = ?1 AND server_id = ?2",
            params![meeting_id, server_id, channel],
        )?;
        read_if_changed(&conn, server_id, changed)
    }

    /// The Russian translation of a phrase. `None`: no such phrase here.
    pub(super) fn set_segment_translation(
        &self,
        meeting_id: &str,
        server_id: &str,
        translation: &str,
    ) -> Result<Option<Segment>> {
        let conn = self.conn();
        let changed = conn.execute(
            "UPDATE segments SET translation = ?3
             WHERE id = ?2 AND meeting_id = ?1 AND server_id = ?2",
            params![meeting_id, server_id, translation],
        )?;
        read_if_changed(&conn, server_id, changed)
    }

    /// The speaker the server told apart. `None`: no such phrase here.
    pub(super) fn set_segment_speaker(
        &self,
        meeting_id: &str,
        server_id: &str,
        speaker: &str,
    ) -> Result<Option<Segment>> {
        let conn = self.conn();
        let changed = conn.execute(
            "UPDATE segments SET speaker = ?3
             WHERE id = ?2 AND meeting_id = ?1 AND server_id = ?2",
            params![meeting_id, server_id, speaker],
        )?;
        read_if_changed(&conn, server_id, changed)
    }
}

fn read_if_changed(
    conn: &rusqlite::Connection,
    server_id: &str,
    changed: usize,
) -> Result<Option<Segment>> {
    if changed == 0 {
        return Ok(None);
    }
    Ok(conn
        .query_row(
            "SELECT * FROM segments WHERE id = ?1",
            [server_id],
            map_segment,
        )
        .optional()?)
}

#[cfg(test)]
mod tests {
    use super::super::db::sample_meeting;
    use super::*;

    fn server_segment(id: &str, start: f64, text: &str) -> ServerSegment {
        ServerSegment {
            meeting_id: "m".to_string(),
            server_id: id.to_string(),
            channel: "system".to_string(),
            start_time: start,
            end_time: start + 2.0,
            text: text.to_string(),
            language: None,
            translation: None,
            speaker: None,
            created_at: "2026-01-01T10:00:00.000Z".to_string(),
        }
    }

    fn db() -> MeetingDb {
        let db = MeetingDb::open_in_memory().unwrap();
        db.insert_meeting(&sample_meeting("m", "2026-01-01T10:00:00.000Z"))
            .unwrap();
        db
    }

    #[test]
    fn a_server_phrase_is_stored_as_already_synced() {
        let db = db();
        let stored = db
            .upsert_server_segment(&server_segment("abc", 1.0, "привет"))
            .unwrap();
        assert!(stored.synced);
        assert_eq!(stored.server_id.as_deref(), Some("abc"));
        assert_eq!(stored.id, "abc");
        // Nothing for the sync to send.
        assert!(db.unsynced_segments("m", 10).unwrap().is_empty());
        assert_eq!(db.list_segments("m").unwrap().len(), 1);
    }

    #[test]
    fn a_repeat_updates_and_keeps_what_the_update_lacks() {
        let db = db();
        let mut first = server_segment("abc", 1.0, "merhaba");
        first.language = Some("tr".to_string());
        first.speaker = Some("s1_speaker_0".to_string());
        db.upsert_server_segment(&first).unwrap();
        let again = db
            .upsert_server_segment(&server_segment("abc", 1.5, "merhaba!"))
            .unwrap();
        assert_eq!(db.list_segments("m").unwrap().len(), 1);
        assert_eq!(again.text, "merhaba!");
        assert_eq!(again.start_time, 1.5);
        assert_eq!(again.language.as_deref(), Some("tr"));
        assert_eq!(again.speaker.as_deref(), Some("s1_speaker_0"));
    }

    #[test]
    fn translation_and_speaker_arrive_after_the_phrase() {
        let db = db();
        db.upsert_server_segment(&server_segment("abc", 1.0, "merhaba"))
            .unwrap();
        let with_translation = db
            .set_segment_translation("m", "abc", "здравствуйте")
            .unwrap()
            .unwrap();
        assert_eq!(
            with_translation.translation.as_deref(),
            Some("здравствуйте")
        );
        let with_speaker = db
            .set_segment_speaker("m", "abc", "s1_speaker_1")
            .unwrap()
            .unwrap();
        assert_eq!(with_speaker.speaker.as_deref(), Some("s1_speaker_1"));
        assert_eq!(with_speaker.translation.as_deref(), Some("здравствуйте"));
        // A phrase we do not have, or another meeting's: nothing changes.
        assert!(db
            .set_segment_translation("m", "missing", "x")
            .unwrap()
            .is_none());
        assert!(db
            .set_segment_translation("other", "abc", "x")
            .unwrap()
            .is_none());
    }

    #[test]
    fn a_side_hint_moves_the_phrase_to_its_channel() {
        let db = db();
        let mut seg = server_segment("abc", 1.0, "да");
        seg.channel = "mixed".to_string();
        db.upsert_server_segment(&seg).unwrap();
        let hinted = db.set_segment_channel("m", "abc", "mic").unwrap().unwrap();
        assert_eq!(hinted.channel, "mic");
        assert!(db
            .set_segment_channel("m", "missing", "mic")
            .unwrap()
            .is_none());
    }

    #[test]
    fn a_local_phrase_cannot_be_changed_by_the_server_stream() {
        let db = db();
        let local = Segment {
            id: "loc".to_string(),
            meeting_id: "m".to_string(),
            channel: "mic".to_string(),
            start_time: 0.0,
            end_time: 1.0,
            text: "локально".to_string(),
            created_at: "2026-01-01T10:00:00.000Z".to_string(),
            synced: false,
            voice: None,
            language: None,
            translation: None,
            speaker: None,
            server_id: None,
        };
        db.insert_segment(&local).unwrap();
        assert!(db
            .set_segment_translation("m", "loc", "x")
            .unwrap()
            .is_none());
        assert_eq!(db.list_segments("m").unwrap()[0].translation, None);
    }
}
