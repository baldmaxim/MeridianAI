//! Voices of a meeting: the lazily loaded voice model, and the commands'
//! side of reading and changing voices.

use std::sync::{Arc, OnceLock};

use log::{info, warn};
use tauri::{AppHandle, Manager};
use tauri_specta::Event;

use super::db_voices::MeetingVoice;
use super::sink::{EmbedFn, SIDE_OPPONENT, SIDE_SELF};
use super::voice::{VoiceEmbedder, VOICE_MODEL_FILE};
use super::{io_err, MeetingManager, MeetingVoices};

pub(super) type EmbedderCell = Arc<OnceLock<Option<Arc<VoiceEmbedder>>>>;

/// The voice model, loaded on first use and then shared by all meetings. A
/// missing file or a failed load is logged once; voices stay off, recording
/// works as before.
fn embedder(app: &AppHandle, cell: &EmbedderCell) -> Option<Arc<VoiceEmbedder>> {
    cell.get_or_init(|| {
        let path = match app.path().resolve(
            format!("resources/models/{VOICE_MODEL_FILE}"),
            tauri::path::BaseDirectory::Resource,
        ) {
            Ok(path) => path,
            Err(e) => {
                warn!("Voice model path unavailable, voices are off: {e}");
                return None;
            }
        };
        if !path.is_file() {
            warn!("Voice model {} not found, voices are off", path.display());
            return None;
        }
        match VoiceEmbedder::load(&path) {
            Ok(embedder) => {
                info!("Voice model loaded");
                Some(Arc::new(embedder))
            }
            Err(e) => {
                warn!("Cannot load the voice model, voices are off: {e:#}");
                None
            }
        }
    })
    .clone()
}

/// The embedding function for a meeting's sink; `None`: voices are off.
pub(super) fn embed_fn(app: &AppHandle, cell: &EmbedderCell) -> Option<EmbedFn> {
    let embedder = embedder(app, cell)?;
    Some(Box::new(move |samples| embedder.embed(samples)))
}

impl MeetingManager {
    pub fn list_voices(&self, meeting_id: &str) -> Result<Vec<MeetingVoice>, String> {
        self.db.list_voices(meeting_id).map_err(io_err)
    }

    /// Sets the side of a voice (`self`, `opponent`, `None`), tells the UI
    /// and leaves the sending to the sync (the caller wakes it).
    pub fn set_voice_side(
        &self,
        meeting_id: &str,
        label: &str,
        side: Option<String>,
    ) -> Result<(), String> {
        if let Some(side) = side.as_deref() {
            if side != SIDE_SELF && side != SIDE_OPPONENT {
                return Err("Сторона голоса: «self», «opponent» или пусто".to_string());
            }
        }
        if !self
            .db
            .set_voice_side(meeting_id, label, side.as_deref())
            .map_err(io_err)?
        {
            return Err("Голос не найден".to_string());
        }
        let _ = MeetingVoices {
            meeting_id: meeting_id.to_string(),
            voices: self.list_voices(meeting_id)?,
        }
        .emit(&self.app);
        Ok(())
    }
}
