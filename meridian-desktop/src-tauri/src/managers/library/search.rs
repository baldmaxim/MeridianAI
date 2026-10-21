//! Full-text search (SQLite FTS5, `unicode61`: case-insensitive for Russian) over
//! the local meetings (title, phrases, notes) and the server's meetings (title,
//! topic, project, summary, and the protocol and phrases once the meeting has
//! been opened). One entry per meeting: `(kind, ref_id)`.

use anyhow::Result;
use rusqlite::{params, Connection, OptionalExtension};

use super::types::{LibraryItem, MeetingView, SearchHit, SearchKind};
use crate::managers::meeting::MeetingDb;

pub(super) const KIND_LOCAL: &str = "local";
pub(super) const KIND_SERVER: &str = "server";
/// Queries shorter than this (in characters) find nothing.
const MIN_QUERY_CHARS: usize = 2;
const DEFAULT_LIMIT: u32 = 30;
const MAX_LIMIT: u32 = 200;
const NO_TITLE: &str = "Без названия";

/// `ё` is searched as `е`: speech recognition writes `е` everywhere, people type
/// both. `unicode61` keeps them apart, so the text and the query are folded.
fn fold_yo(text: &str) -> String {
    text.replace('ё', "е").replace('Ё', "Е")
}

/// Adds or replaces the entry. The FTS row is found through `search_map`, so
/// the index itself is never scanned.
pub(super) fn upsert_entry(
    conn: &Connection,
    kind: &str,
    ref_id: &str,
    title: &str,
    body: &str,
) -> Result<()> {
    remove_entry(conn, kind, ref_id)?;
    // The title column stays as written (it is shown); a folded copy of a title
    // with `ё` goes in front of the body, where the folded query finds it.
    let mut folded = fold_yo(body);
    if title.contains(['ё', 'Ё']) {
        folded = format!("{}\n{folded}", fold_yo(title));
    }
    conn.execute(
        "INSERT INTO search_index (kind, ref_id, title, body) VALUES (?1, ?2, ?3, ?4)",
        params![kind, ref_id, title, folded],
    )?;
    conn.execute(
        "INSERT INTO search_map (kind, ref_id, fts_rowid) VALUES (?1, ?2, ?3)",
        params![kind, ref_id, conn.last_insert_rowid()],
    )?;
    Ok(())
}

pub(super) fn remove_entry(conn: &Connection, kind: &str, ref_id: &str) -> Result<()> {
    let rowid: Option<i64> = conn
        .query_row(
            "SELECT fts_rowid FROM search_map WHERE kind = ?1 AND ref_id = ?2",
            params![kind, ref_id],
            |row| row.get(0),
        )
        .optional()?;
    if let Some(rowid) = rowid {
        conn.execute("DELETE FROM search_index WHERE rowid = ?1", [rowid])?;
        conn.execute(
            "DELETE FROM search_map WHERE kind = ?1 AND ref_id = ?2",
            params![kind, ref_id],
        )?;
    }
    Ok(())
}

/// Drops every entry of the kind.
pub(super) fn remove_kind(conn: &Connection, kind: &str) -> Result<()> {
    conn.execute(
        "DELETE FROM search_index WHERE rowid IN (SELECT fts_rowid FROM search_map WHERE kind = ?1)",
        [kind],
    )?;
    conn.execute("DELETE FROM search_map WHERE kind = ?1", [kind])?;
    Ok(())
}

/// A server meeting's entry; `view` adds the protocol and the phrases.
pub(super) fn index_server_item(
    conn: &Connection,
    item: &LibraryItem,
    view: Option<&MeetingView>,
) -> Result<()> {
    let mut parts: Vec<&str> = [
        &item.meeting_topic,
        &item.customer_name,
        &item.object_name,
        &item.micro_summary,
    ]
    .into_iter()
    .filter_map(|part| part.as_deref())
    .collect();
    if let Some(view) = view {
        parts.extend(view.protocol_markdown.as_deref());
        parts.extend(view.segments.iter().map(|s| s.text.as_str()));
    }
    upsert_entry(
        conn,
        KIND_SERVER,
        &item.meeting_id.to_string(),
        item.title.as_deref().unwrap_or_default(),
        &parts.join("\n"),
    )
}

/// `"word"*` for every word, so quotes and operators typed by the user are
/// plain text. `None`: nothing to search for.
pub(super) fn match_expression(query: &str) -> Option<String> {
    let query = query.trim();
    if query.chars().count() < MIN_QUERY_CHARS {
        return None;
    }
    let query = fold_yo(query);
    let terms: Vec<String> = query
        .split_whitespace()
        .filter(|word| word.chars().any(char::is_alphanumeric))
        .map(|word| {
            let word: String = word.chars().filter(|c| *c != '\0').collect();
            format!("\"{}\"*", word.replace('"', "\"\""))
        })
        .collect();
    (!terms.is_empty()).then(|| terms.join(" "))
}

impl MeetingDb {
    /// Re-reads the local meeting (title, phrases, notes) into the index; a
    /// meeting that is gone leaves the index.
    pub fn index_local_meeting(&self, id: &str) -> Result<()> {
        let conn = self.conn();
        let row: Option<(String, [Option<String>; 3])> = conn
            .query_row(
                "SELECT title, negotiation_type, key_terms, opponent_weaknesses
                   FROM meetings WHERE id = ?1",
                [id],
                |row| {
                    Ok((
                        row.get(0)?,
                        [row.get(1)?, row.get(2)?, row.get(3)?],
                    ))
                },
            )
            .optional()?;
        let Some((title, context)) = row else {
            return remove_entry(&conn, KIND_LOCAL, id);
        };
        // The context (type, key terms, weak points) is searched like the rest.
        let mut texts: Vec<String> = context.into_iter().flatten().collect();
        for sql in [
            "SELECT text FROM segments WHERE meeting_id = ?1 ORDER BY start_time, channel, id",
            "SELECT text FROM notes WHERE meeting_id = ?1 ORDER BY at_seconds, id",
        ] {
            let mut stmt = conn.prepare(sql)?;
            let rows = stmt.query_map([id], |row| row.get::<_, String>(0))?;
            for row in rows {
                texts.push(row?);
            }
        }
        upsert_entry(&conn, KIND_LOCAL, id, &title, &texts.join("\n"))
    }

    pub fn remove_local_index(&self, id: &str) -> Result<()> {
        remove_entry(&self.conn(), KIND_LOCAL, id)
    }

    /// Indexes the finished meetings that are not in the index yet (meetings
    /// recorded before the index existed, or interrupted ones). Returns how many.
    pub fn index_missing_local(&self) -> Result<usize> {
        let ids: Vec<String> = {
            let conn = self.conn();
            let mut stmt = conn.prepare(
                "SELECT id FROM meetings WHERE status != 'recording'
                   AND id NOT IN (SELECT ref_id FROM search_map WHERE kind = 'local')",
            )?;
            let rows = stmt.query_map([], |row| row.get(0))?;
            rows.collect::<rusqlite::Result<_>>()?
        };
        for id in &ids {
            self.index_local_meeting(id)?;
        }
        Ok(ids.len())
    }

    /// The meeting a note belongs to.
    pub fn note_meeting_id(&self, note_id: &str) -> Result<Option<String>> {
        Ok(self
            .conn()
            .query_row(
                "SELECT meeting_id FROM notes WHERE id = ?1",
                [note_id],
                |row| row.get(0),
            )
            .optional()?)
    }

    /// Best matches first. A server meeting recorded in this app (its
    /// `client_uuid` is a local meeting) is not repeated: the local one is returned.
    pub fn search_meetings(&self, query: &str, limit: Option<u32>) -> Result<Vec<SearchHit>> {
        let Some(expression) = match_expression(query) else {
            return Ok(Vec::new());
        };
        let limit = limit.unwrap_or(DEFAULT_LIMIT).clamp(1, MAX_LIMIT);
        let conn = self.conn();
        let mut stmt = conn.prepare(
            "SELECT search_index.kind, search_index.ref_id, search_index.title,
                    snippet(search_index, -1, '[', ']', '…', 16),
                    CASE search_index.kind
                        WHEN 'local' THEN
                            (SELECT started_at FROM meetings WHERE id = search_index.ref_id)
                        ELSE
                            (SELECT json_extract(json, '$.started_at') FROM server_library
                              WHERE meeting_id = CAST(search_index.ref_id AS INTEGER))
                    END
             FROM search_index
             WHERE search_index MATCH ?1
               AND NOT (search_index.kind = 'server' AND EXISTS (
                    SELECT 1 FROM server_library l
                      JOIN meetings m ON m.id = json_extract(l.json, '$.client_uuid')
                     WHERE l.meeting_id = CAST(search_index.ref_id AS INTEGER)))
             ORDER BY rank
             LIMIT ?2",
        )?;
        let rows = stmt.query_map(params![expression, limit], |row| {
            let kind: String = row.get(0)?;
            let title: String = row.get(2)?;
            Ok(SearchHit {
                kind: if kind == KIND_LOCAL {
                    SearchKind::Local
                } else {
                    SearchKind::Server
                },
                id: row.get(1)?,
                title: if title.trim().is_empty() {
                    NO_TITLE.to_string()
                } else {
                    title
                },
                snippet: row.get(3)?,
                started_at: row.get(4)?,
            })
        })?;
        Ok(rows.collect::<rusqlite::Result<_>>()?)
    }
}
