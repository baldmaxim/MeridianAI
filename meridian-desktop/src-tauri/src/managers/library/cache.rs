//! The offline cache of the site's meetings, projects and opened meetings, in
//! `meetings.db` (`server_library`, `server_projects`, `server_views`). Every
//! write also refreshes the search index of the server's meetings.

use anyhow::Result;
use chrono::{SecondsFormat, Utc};
use log::warn;
use rusqlite::{params, Connection, OptionalExtension};
use serde::de::DeserializeOwned;

use super::search::{index_server_item, remove_kind, KIND_SERVER};
use super::types::{LibraryItem, MeetingView, ProjectCustomer};
use crate::managers::meeting::MeetingDb;

fn now_iso() -> String {
    Utc::now().to_rfc3339_opts(SecondsFormat::Millis, true)
}

/// A cached JSON that no longer fits the types (the server changed) is skipped.
fn parse<T: DeserializeOwned>(json: &str) -> Option<T> {
    match serde_json::from_str(json) {
        Ok(value) => Some(value),
        Err(e) => {
            warn!("Skipping an unreadable cache entry: {e}");
            None
        }
    }
}

fn cached_view(conn: &Connection, meeting_id: i64) -> Result<Option<MeetingView>> {
    let json: Option<String> = conn
        .query_row(
            "SELECT json FROM server_views WHERE meeting_id = ?1",
            [meeting_id],
            |row| row.get(0),
        )
        .optional()?;
    Ok(json.and_then(|json| parse(&json)))
}

impl MeetingDb {
    /// Replaces the cached library with `items` (what the server returned now)
    /// and re-indexes it. Opened meetings that left the library are dropped.
    pub fn put_library(&self, items: &[LibraryItem]) -> Result<()> {
        let mut conn = self.conn();
        let tx = conn.transaction()?;
        let fetched_at = now_iso();
        tx.execute("DELETE FROM server_library", [])?;
        for item in items {
            tx.execute(
                "INSERT INTO server_library (meeting_id, json, fetched_at) VALUES (?1, ?2, ?3)",
                params![item.meeting_id, serde_json::to_string(item)?, fetched_at],
            )?;
        }
        tx.execute(
            "DELETE FROM server_views WHERE meeting_id NOT IN (SELECT meeting_id FROM server_library)",
            [],
        )?;
        remove_kind(&tx, KIND_SERVER)?;
        for item in items {
            let view = cached_view(&tx, item.meeting_id)?;
            index_server_item(&tx, item, view.as_ref())?;
        }
        tx.commit()?;
        Ok(())
    }

    /// Newest first, and when the cache was written.
    pub fn get_library(&self) -> Result<(Vec<LibraryItem>, Option<String>)> {
        let conn = self.conn();
        let mut stmt = conn.prepare(
            "SELECT json, fetched_at FROM server_library
             ORDER BY json_extract(json, '$.started_at') DESC, meeting_id DESC",
        )?;
        let rows = stmt.query_map([], |row| {
            Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?))
        })?;
        let mut items = Vec::new();
        let mut fetched_at: Option<String> = None;
        for row in rows {
            let (json, at) = row?;
            if fetched_at.as_ref().is_none_or(|prev| at > *prev) {
                fetched_at = Some(at);
            }
            items.extend(parse(&json));
        }
        Ok((items, fetched_at))
    }

    pub fn put_projects(&self, projects: &[ProjectCustomer]) -> Result<()> {
        self.conn().execute(
            "INSERT INTO server_projects (id, json, fetched_at) VALUES (1, ?1, ?2)
             ON CONFLICT(id) DO UPDATE SET json = excluded.json, fetched_at = excluded.fetched_at",
            params![serde_json::to_string(projects)?, now_iso()],
        )?;
        Ok(())
    }

    pub fn get_projects(&self) -> Result<(Vec<ProjectCustomer>, Option<String>)> {
        let row: Option<(String, String)> = self
            .conn()
            .query_row(
                "SELECT json, fetched_at FROM server_projects WHERE id = 1",
                [],
                |row| Ok((row.get(0)?, row.get(1)?)),
            )
            .optional()?;
        Ok(match row {
            Some((json, at)) => (parse(&json).unwrap_or_default(), Some(at)),
            None => (Vec::new(), None),
        })
    }

    /// Keeps an opened meeting for offline viewing, refreshes its library row
    /// and adds its protocol and phrases to the search index.
    pub fn put_view(&self, view: &MeetingView) -> Result<()> {
        let mut conn = self.conn();
        let tx = conn.transaction()?;
        let (json, fetched_at) = (serde_json::to_string(view)?, now_iso());
        tx.execute(
            "INSERT INTO server_views (meeting_id, json, fetched_at) VALUES (?1, ?2, ?3)
             ON CONFLICT(meeting_id) DO UPDATE SET json = excluded.json,
                fetched_at = excluded.fetched_at",
            params![view.item.meeting_id, json, fetched_at],
        )?;
        tx.execute(
            "INSERT INTO server_library (meeting_id, json, fetched_at) VALUES (?1, ?2, ?3)
             ON CONFLICT(meeting_id) DO UPDATE SET json = excluded.json",
            params![
                view.item.meeting_id,
                serde_json::to_string(&view.item)?,
                fetched_at
            ],
        )?;
        index_server_item(&tx, &view.item, Some(view))?;
        tx.commit()?;
        Ok(())
    }

    pub fn get_view(&self, meeting_id: i64) -> Result<Option<MeetingView>> {
        cached_view(&self.conn(), meeting_id)
    }

    /// Forgets everything of the server (sign-out, or another account).
    pub fn clear_server_cache(&self) -> Result<()> {
        let mut conn = self.conn();
        let tx = conn.transaction()?;
        for table in ["server_library", "server_projects", "server_views"] {
            tx.execute(&format!("DELETE FROM {table}"), [])?;
        }
        remove_kind(&tx, KIND_SERVER)?;
        tx.commit()?;
        Ok(())
    }
}
