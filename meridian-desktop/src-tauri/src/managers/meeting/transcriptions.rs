//! «Расшифровка файлов»: audio files dropped onto the window are checked,
//! copied into the app's data folder (`transcriptions/<id>/<name>`) and put in
//! the queue (`db_transcriptions.rs`); `managers::sync` sends them to the server.

use std::path::{Path, PathBuf};

use log::warn;
use serde::Serialize;
use specta::Type;
use tauri_specta::Event;

use super::db_transcriptions::{TranscriptionItem, TR_ERROR, TR_QUEUED};
use super::documents::sanitize_file_name;
use super::{io_err, short_id, MeetingDb, MeetingManager};

/// The server refuses bigger files.
pub const MAX_TRANSCRIPTION_BYTES: u64 = 500 * 1024 * 1024;
/// The types the server takes for a transcription.
const AUDIO_EXTENSIONS: [&str; 7] = ["mp3", "wav", "m4a", "ogg", "flac", "opus", "webm"];

/// A row of the list changed (`id` says which, when it is one): reload the list.
#[derive(Clone, Debug, Serialize, Type, Event)]
pub struct TranscriptionsChanged {
    pub id: Option<String>,
}

fn extension(name: &str) -> String {
    Path::new(name)
        .extension()
        .map(|e| e.to_string_lossy().to_lowercase())
        .unwrap_or_default()
}

/// The MIME type to upload `name` with; `None` for a type the server refuses.
pub fn audio_mime(name: &str) -> Option<&'static str> {
    match extension(name).as_str() {
        "mp3" => Some("audio/mpeg"),
        "wav" => Some("audio/wav"),
        "m4a" => Some("audio/mp4"),
        "ogg" | "opus" => Some("audio/ogg"),
        "flac" => Some("audio/flac"),
        "webm" => Some("audio/webm"),
        _ => None,
    }
}

/// Why a file is not taken, as the user reads it in the list.
fn check_audio(name: &str, size: u64) -> Result<(), String> {
    if !AUDIO_EXTENSIONS.contains(&extension(name).as_str()) {
        return Err(
            "Этот тип файла не поддерживается (нужны MP3, WAV, M4A, OGG, FLAC, OPUS, WEBM)".into(),
        );
    }
    if size == 0 {
        return Err("Файл пустой".into());
    }
    if size > MAX_TRANSCRIPTION_BYTES {
        return Err("Файл больше 500 МБ".into());
    }
    Ok(())
}

/// Takes one file: a copy goes to `root/<id>/` and a `queued` row is made. A
/// refused or unreadable file still gets a row, in `error`, so the list says why.
fn add_file(db: &MeetingDb, root: &Path, source: &Path) -> anyhow::Result<TranscriptionItem> {
    let id = short_id();
    let name = source
        .file_name()
        .map(|n| n.to_string_lossy().into_owned())
        .unwrap_or_else(|| source.to_string_lossy().into_owned());
    let refuse = |size: u64, reason: &str| {
        db.insert_transcription(&id, &name, "", size as i64, TR_ERROR, Some(reason))
    };
    let size = match std::fs::metadata(source) {
        Ok(meta) if meta.is_file() => meta.len(),
        _ => return refuse(0, "Не удалось прочитать файл"),
    };
    if let Err(reason) = check_audio(&name, size) {
        return refuse(size, &reason);
    }
    let dir: PathBuf = root.join(&id);
    let target = dir.join(sanitize_file_name(&name));
    let copied = std::fs::create_dir_all(&dir).and_then(|()| std::fs::copy(source, &target));
    if let Err(e) = copied {
        warn!("Cannot copy a file for transcription: {e}");
        let _ = std::fs::remove_dir_all(&dir);
        return refuse(size, "Не удалось скопировать файл");
    }
    // The size of the copy is what gets uploaded.
    let copied_size = std::fs::metadata(&target).map_or(size, |m| m.len());
    let inserted = db.insert_transcription(
        &id,
        &name,
        &target.to_string_lossy(),
        copied_size as i64,
        TR_QUEUED,
        None,
    );
    if inserted.is_err() {
        let _ = std::fs::remove_dir_all(&dir);
    }
    inserted
}

/// Deletes the local copy and its (then empty) folder.
pub fn delete_local_copy(local_path: &str) {
    if local_path.is_empty() {
        return;
    }
    let path = Path::new(local_path);
    if let Err(e) = std::fs::remove_file(path) {
        if e.kind() != std::io::ErrorKind::NotFound {
            warn!("Cannot delete the copy of a file for transcription: {e}");
        }
    }
    if let Some(dir) = path.parent() {
        // Only an empty folder goes.
        let _ = std::fs::remove_dir(dir);
    }
}

impl MeetingManager {
    fn transcriptions_root(&self) -> Result<PathBuf, String> {
        crate::portable::app_data_dir(&self.app)
            .map(|dir| dir.join("transcriptions"))
            .map_err(io_err)
    }

    /// Copies the files into the app's data folder and queues them. A refused
    /// file does not stop the others: it comes back as an `error` item.
    pub fn add_transcriptions(&self, paths: Vec<String>) -> Result<Vec<TranscriptionItem>, String> {
        let root = self.transcriptions_root()?;
        let mut items = Vec::new();
        for path in paths {
            match add_file(&self.db, &root, Path::new(&path)) {
                Ok(item) => items.push(item),
                Err(e) => warn!("Cannot queue a file for transcription: {e:#}"),
            }
        }
        Ok(items)
    }

    /// Deletes the row and the local copy, in any state (the server keeps its own).
    pub fn remove_transcription(&self, id: &str) -> Result<(), String> {
        if let Some(path) = self.db.remove_transcription(id).map_err(io_err)? {
            delete_local_copy(&path);
        }
        Ok(())
    }

    pub fn emit_transcriptions_changed(&self, id: Option<&str>) {
        let _ = TranscriptionsChanged {
            id: id.map(str::to_string),
        }
        .emit(&self.app);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn setup() -> (MeetingDb, tempfile::TempDir, tempfile::TempDir) {
        (
            MeetingDb::open_in_memory().unwrap(),
            tempfile::tempdir().unwrap(),
            tempfile::tempdir().unwrap(),
        )
    }

    #[test]
    fn extensions_and_sizes_are_checked() {
        for name in [
            "a.mp3", "A.WAV", "b.m4a", "c.ogg", "d.flac", "e.opus", "f.webm",
        ] {
            assert!(check_audio(name, 1).is_ok(), "{name}");
            assert!(audio_mime(name).is_some(), "{name}");
        }
        assert!(check_audio("a.pdf", 1).is_err());
        assert!(check_audio("a.mp3", 0).is_err());
        assert!(check_audio("a.mp3", MAX_TRANSCRIPTION_BYTES).is_ok());
        assert!(check_audio("a.mp3", MAX_TRANSCRIPTION_BYTES + 1).is_err());
    }

    #[test]
    fn a_file_is_copied_and_queued() {
        let (db, src, root) = setup();
        let source = src.path().join("Запись.mp3");
        std::fs::write(&source, b"audio").unwrap();

        let item = add_file(&db, root.path(), &source).unwrap();
        assert_eq!(item.status, TR_QUEUED);
        assert_eq!(item.filename, "Запись.mp3");
        assert_eq!(item.size, 5);
        let row = &db.transcriptions_to_send().unwrap()[0];
        assert!(Path::new(&row.local_path).starts_with(root.path()));
        assert_eq!(std::fs::read(&row.local_path).unwrap(), b"audio");

        delete_local_copy(&row.local_path);
        assert!(!Path::new(&row.local_path).exists());
        assert!(!root.path().join(&item.id).exists(), "the folder goes too");
    }

    #[test]
    fn a_refused_file_becomes_an_error_row() {
        let (db, src, root) = setup();
        let bad = src.path().join("a.pdf");
        std::fs::write(&bad, b"x").unwrap();
        let item = add_file(&db, root.path(), &bad).unwrap();
        assert_eq!(item.status, TR_ERROR);
        assert!(item.error.is_some());
        let missing = add_file(&db, root.path(), &src.path().join("none.mp3")).unwrap();
        assert_eq!(missing.status, TR_ERROR);
        assert!(db.transcriptions_to_send().unwrap().is_empty());
        assert!(!db.has_active_transcriptions().unwrap());
    }
}
