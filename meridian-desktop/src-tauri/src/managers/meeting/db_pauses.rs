//! The stretches in which a meeting's recording did not run because the
//! computer slept. The audio has no hole there (nothing is added for the
//! sleep), so the meeting's time goes on from the same point; this list is how
//! to tell what the wall clock said: a phrase at `at_seconds` or later was
//! spoken that much later than the plain sum of the audio suggests.

use anyhow::Result;
use rusqlite::params;

use super::db::MeetingDb;

/// One sleep during a meeting.
#[derive(Clone, Debug, PartialEq)]
pub struct Pause {
    /// The meeting's time (seconds of audio) at which the computer went away.
    pub at_seconds: f64,
    /// The wall clock before and after, RFC 3339.
    pub paused_at: String,
    pub resumed_at: String,
    /// `sleep`.
    pub kind: String,
}

impl MeetingDb {
    pub fn add_pause(&self, meeting_id: &str, pause: &Pause) -> Result<()> {
        self.conn().execute(
            "INSERT INTO meeting_pauses (meeting_id, at_seconds, paused_at, resumed_at, kind)
             VALUES (?1, ?2, ?3, ?4, ?5)",
            params![
                meeting_id,
                pause.at_seconds,
                pause.paused_at,
                pause.resumed_at,
                pause.kind
            ],
        )?;
        Ok(())
    }

    /// The meeting's pauses in the order they happened.
    #[cfg_attr(not(test), allow(dead_code))]
    pub fn list_pauses(&self, meeting_id: &str) -> Result<Vec<Pause>> {
        let conn = self.conn();
        let mut stmt = conn.prepare(
            "SELECT at_seconds, paused_at, resumed_at, kind FROM meeting_pauses
             WHERE meeting_id = ?1 ORDER BY at_seconds, id",
        )?;
        let rows = stmt.query_map([meeting_id], |row| {
            Ok(Pause {
                at_seconds: row.get(0)?,
                paused_at: row.get(1)?,
                resumed_at: row.get(2)?,
                kind: row.get(3)?,
            })
        })?;
        Ok(rows.collect::<rusqlite::Result<_>>()?)
    }
}

#[cfg(test)]
mod tests {
    use super::super::db::sample_meeting;
    use super::*;

    #[test]
    fn pauses_are_kept_in_order_and_go_with_the_meeting() {
        let db = MeetingDb::open_in_memory().unwrap();
        db.insert_meeting(&sample_meeting("m", "2026-01-01T10:00:00.000Z"))
            .unwrap();
        let pause = |at: f64| Pause {
            at_seconds: at,
            paused_at: "2026-01-01T10:05:00.000Z".into(),
            resumed_at: "2026-01-01T18:05:00.000Z".into(),
            kind: "sleep".into(),
        };
        db.add_pause("m", &pause(600.0)).unwrap();
        db.add_pause("m", &pause(300.0)).unwrap();
        let at: Vec<f64> = db
            .list_pauses("m")
            .unwrap()
            .iter()
            .map(|p| p.at_seconds)
            .collect();
        assert_eq!(at, [300.0, 600.0]);
        assert!(db.list_pauses("other").unwrap().is_empty());
        // Deleting the meeting takes its pauses.
        db.delete_meeting("m").unwrap();
        assert!(db.list_pauses("m").unwrap().is_empty());
    }
}
