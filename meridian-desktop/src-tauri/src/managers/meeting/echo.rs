//! Echo of the other side in the microphone: in an online meeting the
//! speakers' sound gets into the mic, so the same phrase is recognized in both
//! channels. `is_echo` says whether two phrases of different channels are one.

use anyhow::Result;
use rusqlite::params;

use super::db::{map_segment, MeetingDb, Segment};

/// Share of the shorter phrase that must overlap in time.
const MIN_OVERLAP: f64 = 0.5;
/// Similarity of the normalized texts (normalized Levenshtein).
const MIN_SIMILARITY: f64 = 0.75;

/// Lower case, letters, digits and single spaces only.
fn normalize(text: &str) -> String {
    let cleaned: String = text
        .chars()
        .filter_map(|c| {
            if c.is_alphanumeric() {
                Some(c.to_lowercase().collect::<String>())
            } else if c.is_whitespace() {
                Some(" ".to_string())
            } else {
                None
            }
        })
        .collect();
    cleaned.split_whitespace().collect::<Vec<_>>().join(" ")
}

/// A phrase: start and end in seconds, and the text.
pub(super) type Span<'a> = (f64, f64, &'a str);

/// Whether two phrases (of different channels) are the same speech: they
/// overlap by at least half of the shorter one and read alike.
pub(super) fn is_echo(a: Span<'_>, b: Span<'_>) -> bool {
    let shorter = (a.1 - a.0).min(b.1 - b.0);
    if shorter <= 0.0 {
        return false;
    }
    let overlap = a.1.min(b.1) - a.0.max(b.0);
    if overlap / shorter < MIN_OVERLAP {
        return false;
    }
    let (a, b) = (normalize(a.2), normalize(b.2));
    !a.is_empty() && !b.is_empty() && strsim::normalized_levenshtein(&a, &b) >= MIN_SIMILARITY
}

impl MeetingDb {
    /// Segments of the meeting's other channels that overlap `start..end`.
    pub fn segments_overlapping(
        &self,
        meeting_id: &str,
        other_than_channel: &str,
        start: f64,
        end: f64,
    ) -> Result<Vec<Segment>> {
        let conn = self.conn();
        let mut stmt = conn.prepare(
            "SELECT * FROM segments
             WHERE meeting_id = ?1 AND channel != ?2 AND start_time < ?4 AND end_time > ?3
             ORDER BY start_time, id",
        )?;
        let rows = stmt.query_map(
            params![meeting_id, other_than_channel, start, end],
            map_segment,
        )?;
        Ok(rows.collect::<rusqlite::Result<_>>()?)
    }

    /// Deletes a segment the server has not got. `false`: it is synced (or gone).
    pub fn delete_unsynced_segment(&self, id: &str) -> Result<bool> {
        Ok(self
            .conn()
            .execute("DELETE FROM segments WHERE id = ?1 AND synced = 0", [id])?
            > 0)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn normalizing_drops_case_punctuation_and_extra_spaces() {
        assert_eq!(
            normalize("  Добрый,  ДЕНЬ!\nКак дела? 2 раза "),
            "добрый день как дела 2 раза"
        );
        assert_eq!(normalize("…!?"), "");
    }

    #[test]
    fn the_same_words_at_the_same_time_are_an_echo() {
        let system = (10.0, 14.0, "Добрый день, коллеги, начинаем.");
        let mic = (10.4, 14.3, "добрый день коллеги начинаем");
        assert!(is_echo(system, mic) && is_echo(mic, system));
    }

    #[test]
    fn a_slightly_misheard_echo_still_matches() {
        let system = (0.0, 5.0, "Мы готовы подписать договор до пятницы");
        let mic = (0.2, 5.1, "мы готовы подписать договор до пятницы а");
        assert!(is_echo(system, mic));
        let mic = (0.2, 5.1, "мы готовы подписать договоры до пятницы");
        assert!(is_echo(system, mic));
    }

    #[test]
    fn different_words_are_not_an_echo_even_at_the_same_time() {
        let system = (0.0, 4.0, "Цена слишком высокая для нас");
        let mic = (0.0, 4.0, "Давайте вернёмся к графику работ");
        assert!(!is_echo(system, mic));
    }

    #[test]
    fn the_same_words_at_another_time_are_not_an_echo() {
        let system = (0.0, 4.0, "хорошо договорились");
        assert!(!is_echo(system, (4.0, 7.0, "хорошо договорились")));
        // Overlap under half of the shorter phrase.
        assert!(!is_echo(system, (3.0, 6.0, "хорошо договорились")));
        // Exactly half of the shorter one counts.
        assert!(is_echo(system, (3.0, 5.0, "хорошо договорились")));
    }

    #[test]
    fn a_short_phrase_inside_a_long_one_is_compared_by_text() {
        // The overlap is the whole short phrase, but the long one reads differently.
        let long = (
            0.0,
            20.0,
            "мы обсуждали сроки поставки арматуры и бетона на объект",
        );
        assert!(!is_echo(long, (5.0, 7.0, "да")));
    }

    #[test]
    fn empty_text_and_empty_spans_never_match() {
        assert!(!is_echo((0.0, 2.0, "..."), (0.0, 2.0, "...")));
        assert!(!is_echo((1.0, 1.0, "да"), (0.0, 2.0, "да")));
    }

    #[test]
    fn overlapping_segments_of_the_other_channel_are_found_and_unsynced_ones_deleted() {
        use super::super::db::sample_meeting;
        let db = MeetingDb::open_in_memory().unwrap();
        db.insert_meeting(&sample_meeting("m", "2026-01-01T10:00:00.000Z"))
            .unwrap();
        let segment = |id: &str, channel: &str, start: f64, end: f64, synced: bool| Segment {
            id: id.to_string(),
            meeting_id: "m".to_string(),
            channel: channel.to_string(),
            start_time: start,
            end_time: end,
            text: "текст".to_string(),
            created_at: "2026-01-01T00:00:00.000Z".to_string(),
            synced,
            voice: None,
        };
        for s in [
            segment("a", "mic", 0.0, 3.0, false),
            segment("b", "mic", 3.0, 6.0, true),
            segment("c", "system", 1.0, 2.0, false),
            segment("d", "mic", 10.0, 12.0, false),
        ] {
            db.insert_segment(&s).unwrap();
        }
        let found = db.segments_overlapping("m", "system", 2.5, 3.5).unwrap();
        assert_eq!(
            found.iter().map(|s| s.id.as_str()).collect::<Vec<_>>(),
            ["a", "b"]
        );
        assert!(db
            .segments_overlapping("m", "system", 6.0, 9.0)
            .unwrap()
            .is_empty());

        assert!(db.delete_unsynced_segment("a").unwrap());
        assert!(!db.delete_unsynced_segment("b").unwrap(), "synced stays");
        assert!(!db.delete_unsynced_segment("a").unwrap());
        assert_eq!(db.list_segments("m").unwrap().len(), 3);
    }
}
