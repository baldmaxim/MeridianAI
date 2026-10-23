//! Sources of a meeting: files dropped onto the window are checked, copied into
//! the app's data folder (`meetings/<meeting>/docs/`) and put in the upload queue
//! (`db_documents.rs`); `managers::sync` sends them to the server.

use std::path::{Path, PathBuf};

use log::warn;
use serde::Serialize;
use specta::Type;

use super::{io_err, now_iso, short_id, storage, MeetingManager};

/// The server refuses bigger files.
pub const MAX_DOCUMENT_BYTES: u64 = 50 * 1024 * 1024;
const MAX_FILE_NAME_CHARS: usize = 120;

/// Why a dropped file was not taken.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Type)]
#[serde(rename_all = "snake_case")]
pub enum RejectReason {
    /// Not a type the server takes as a source.
    Extension,
    TooLarge,
    Empty,
    /// Not a file, or it could not be read or copied.
    Unreadable,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Type)]
pub struct RejectedDocument {
    pub name: String,
    pub reason: RejectReason,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Type)]
pub struct AddDocumentsResult {
    pub added: u32,
    pub rejected: Vec<RejectedDocument>,
}

fn extension(name: &str) -> String {
    Path::new(name)
        .extension()
        .map(|e| e.to_string_lossy().to_lowercase())
        .unwrap_or_default()
}

/// The MIME type to upload `name` with (the types the server takes as
/// sources: pdf, docx, xlsx, txt, md, csv); `None` for any other type.
pub fn mime_for(name: &str) -> Option<&'static str> {
    match extension(name).as_str() {
        "pdf" => Some("application/pdf"),
        "docx" => Some("application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        "xlsx" => Some("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        "txt" => Some("text/plain"),
        "md" => Some("text/markdown"),
        "csv" => Some("text/csv"),
        _ => None,
    }
}

/// Checks a file by its name and size; the MIME type to upload it with.
pub fn check_document(name: &str, size: u64) -> Result<&'static str, RejectReason> {
    let mime = mime_for(name).ok_or(RejectReason::Extension)?;
    if size == 0 {
        return Err(RejectReason::Empty);
    }
    if size > MAX_DOCUMENT_BYTES {
        return Err(RejectReason::TooLarge);
    }
    Ok(mime)
}

/// A name that is safe on disk: no path parts, no characters Windows refuses,
/// no control characters, at most `MAX_FILE_NAME_CHARS` (the extension is kept).
pub fn sanitize_file_name(name: &str) -> String {
    let last = name.rsplit(['/', '\\']).next().unwrap_or_default();
    let cleaned: String = last
        .chars()
        .map(|c| {
            if c.is_control() || matches!(c, '<' | '>' | ':' | '"' | '|' | '?' | '*') {
                '_'
            } else {
                c
            }
        })
        .collect();
    let cleaned = cleaned.trim_matches(|c: char| c == ' ' || c == '.');
    if cleaned.is_empty() {
        return "document".to_string();
    }
    if cleaned.chars().count() <= MAX_FILE_NAME_CHARS {
        return cleaned.to_string();
    }
    let ext = extension(cleaned);
    let keep = MAX_FILE_NAME_CHARS.saturating_sub(ext.chars().count() + 1);
    let stem: String = Path::new(cleaned)
        .file_stem()
        .map(|s| s.to_string_lossy().chars().take(keep).collect())
        .unwrap_or_default();
    if ext.is_empty() {
        stem
    } else {
        format!("{stem}.{ext}")
    }
}

/// `meetings/<dir>/docs`; `dir` is the local meeting's id or `server-<id>`.
pub fn docs_dir(meetings_root: &Path, dir: &str) -> PathBuf {
    storage::meeting_dir(meetings_root, dir).join("docs")
}

/// Where the copy of a dropped file goes; never an existing file.
fn copy_target(dir: &Path, safe_name: &str) -> PathBuf {
    let stamp = chrono::Utc::now().format("%Y%m%d%H%M%S%3f");
    let target = dir.join(format!("{stamp}_{safe_name}"));
    if target.exists() {
        dir.join(format!("{stamp}_{}_{safe_name}", short_id()))
    } else {
        target
    }
}

impl MeetingManager {
    /// Copies the files into the app's data folder and queues them for the
    /// server. A file that is refused does not stop the others.
    pub fn add_documents(
        &self,
        meeting_id: Option<&str>,
        server_meeting_id: Option<i64>,
        paths: Vec<String>,
    ) -> Result<AddDocumentsResult, String> {
        let (dir_name, local_id, server_id) = match (meeting_id, server_meeting_id) {
            (Some(id), passed) => {
                let meeting = self
                    .db
                    .get_meeting(id)
                    .map_err(io_err)?
                    .ok_or_else(|| "Встреча не найдена".to_string())?;
                (
                    meeting.id.clone(),
                    Some(meeting.id),
                    meeting.server_meeting_id.or(passed),
                )
            }
            (None, Some(server_id)) => (format!("server-{server_id}"), None, Some(server_id)),
            (None, None) => return Err("Не указана встреча".to_string()),
        };
        let docs = docs_dir(&self.root, &dir_name);
        let mut result = AddDocumentsResult {
            added: 0,
            rejected: Vec::new(),
        };
        for path in paths {
            let source = PathBuf::from(&path);
            let name = source
                .file_name()
                .map(|n| n.to_string_lossy().into_owned())
                .unwrap_or_else(|| path.clone());
            let reject = |reason| RejectedDocument {
                name: name.clone(),
                reason,
            };
            let size = match std::fs::metadata(&source) {
                Ok(meta) if meta.is_file() => meta.len(),
                _ => {
                    result.rejected.push(reject(RejectReason::Unreadable));
                    continue;
                }
            };
            let mime = match check_document(&name, size) {
                Ok(mime) => mime,
                Err(reason) => {
                    result.rejected.push(reject(reason));
                    continue;
                }
            };
            let target = match std::fs::create_dir_all(&docs) {
                Ok(()) => copy_target(&docs, &sanitize_file_name(&name)),
                Err(e) => {
                    warn!("Cannot create {}: {e}", docs.display());
                    result.rejected.push(reject(RejectReason::Unreadable));
                    continue;
                }
            };
            if let Err(e) = std::fs::copy(&source, &target) {
                warn!("Cannot copy a source file of a meeting: {e}");
                let _ = std::fs::remove_file(&target);
                result.rejected.push(reject(RejectReason::Unreadable));
                continue;
            }
            // The size of the copy is what gets uploaded.
            let copied = std::fs::metadata(&target).map_or(size, |m| m.len());
            let inserted = self.db.insert_document(
                local_id.as_deref(),
                server_id,
                &target.to_string_lossy(),
                &name,
                copied as i64,
                mime,
                &now_iso(),
            );
            match inserted {
                Ok(_) => result.added += 1,
                Err(e) => {
                    warn!("Cannot queue a source file of a meeting: {e:#}");
                    let _ = std::fs::remove_file(&target);
                    result.rejected.push(reject(RejectReason::Unreadable));
                }
            }
        }
        Ok(result)
    }

    /// Takes a queued file out of the queue and deletes its copy. `Ok(false)`:
    /// it is being uploaded right now.
    pub fn remove_queued_document(&self, queue_id: i64) -> Result<bool, String> {
        match self.db.remove_queued_document(queue_id).map_err(io_err)? {
            super::db_documents::RemoveOutcome::Removed(path) => {
                if let Err(e) = std::fs::remove_file(&path) {
                    if e.kind() != std::io::ErrorKind::NotFound {
                        warn!("Cannot delete the copy of a queued file: {e}");
                    }
                }
                Ok(true)
            }
            super::db_documents::RemoveOutcome::Busy => Ok(false),
            super::db_documents::RemoveOutcome::NotFound => Ok(true),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn allowed_types_are_found_case_insensitively() {
        for name in [
            "a.pdf", "A.PDF", "b.Docx", "c.xlsx", "d.txt", "e.md", "f.CSV",
        ] {
            assert!(check_document(name, 100).is_ok(), "{name}");
        }
        assert_eq!(check_document("a.exe", 100), Err(RejectReason::Extension));
        assert_eq!(check_document("noext", 100), Err(RejectReason::Extension));
        assert_eq!(
            check_document("a.pdf.exe", 100),
            Err(RejectReason::Extension)
        );
        assert_eq!(check_document("a.doc", 100), Err(RejectReason::Extension));
    }

    #[test]
    fn size_limits_are_enforced() {
        assert!(check_document("a.pdf", MAX_DOCUMENT_BYTES).is_ok());
        assert_eq!(
            check_document("a.pdf", MAX_DOCUMENT_BYTES + 1),
            Err(RejectReason::TooLarge)
        );
        assert_eq!(check_document("a.pdf", 0), Err(RejectReason::Empty));
        // The extension is checked first.
        assert_eq!(
            check_document("a.exe", MAX_DOCUMENT_BYTES + 1),
            Err(RejectReason::Extension)
        );
    }

    #[test]
    fn names_lose_paths_and_bad_characters() {
        assert_eq!(sanitize_file_name("../../etc/passwd.txt"), "passwd.txt");
        assert_eq!(
            sanitize_file_name(r"C:\Users\me\Договор.pdf"),
            "Договор.pdf"
        );
        assert_eq!(
            sanitize_file_name("a<b>:c|d?e*f\".csv"),
            "a_b__c_d_e_f_.csv"
        );
        assert_eq!(sanitize_file_name("tab\there.md"), "tab_here.md");
        assert_eq!(sanitize_file_name("  .. "), "document");
        assert_eq!(sanitize_file_name(""), "document");
        assert_eq!(sanitize_file_name("a/"), "document");
    }

    #[test]
    fn long_names_are_cut_but_keep_the_extension() {
        let name = format!("{}.pdf", "я".repeat(300));
        let safe = sanitize_file_name(&name);
        assert_eq!(safe.chars().count(), MAX_FILE_NAME_CHARS);
        assert!(safe.ends_with(".pdf"));
        assert!(!safe.contains('/'));
    }

    #[test]
    fn copy_target_stays_inside_the_docs_folder() {
        let dir = tempfile::tempdir().unwrap();
        let a = copy_target(dir.path(), "x.pdf");
        assert_eq!(a.parent().unwrap(), dir.path());
        std::fs::write(&a, b"1").unwrap();
        // Same millisecond, same name: never the same file.
        let b = copy_target(dir.path(), "x.pdf");
        assert_ne!(a, b);
    }

    #[test]
    fn docs_live_under_the_meeting_folder() {
        let root = Path::new("/data/meetings");
        assert_eq!(docs_dir(root, "abc"), Path::new("/data/meetings/abc/docs"));
        assert_eq!(
            docs_dir(root, "server-7"),
            Path::new("/data/meetings/server-7/docs")
        );
    }
}
