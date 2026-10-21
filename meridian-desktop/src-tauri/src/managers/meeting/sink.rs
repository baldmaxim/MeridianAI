//! Where a recognized phrase goes: the echo check, the voice, the database.
//!
//! Voices: every phrase with text is embedded and put to a voice by the
//! meeting's one clusterer, shared by all its channels. A new voice is saved
//! with a default side (what the channel says), a known one only updates its
//! centroid. Without a voice model nothing is told apart and phrases are
//! stored as before.

use std::sync::Mutex;

use anyhow::Result;
use log::warn;

use super::db::{MeetingDb, Segment};
use super::db_voices::MeetingVoice;
use super::echo::is_echo;
use super::voice::{VoiceCentroid, VoiceClusterer, VoiceMatch};
use super::{CHANNEL_MIC, CHANNEL_SYSTEM};

/// Embedding of a phrase's 16 kHz samples; `None`: too short or failed.
pub(super) type EmbedFn = Box<dyn Fn(&[f32]) -> Option<Vec<f32>> + Send>;

pub(super) const SIDE_SELF: &str = "self";
pub(super) const SIDE_OPPONENT: &str = "opponent";

/// What `store` did.
#[derive(Debug, Default)]
pub(super) struct Stored {
    /// The segment as stored; `None`: it was the microphone's echo of the system sound.
    pub(super) segment: Option<Segment>,
    /// Microphone segments replaced by this one (the same speech, heard twice).
    pub(super) removed: Vec<String>,
    /// All voices of the meeting, when a new one appeared.
    pub(super) new_voices: Option<Vec<MeetingVoice>>,
}

pub(super) struct SegmentSink {
    db: std::sync::Arc<MeetingDb>,
    meeting_id: String,
    /// `None`: voices are off.
    embed: Option<EmbedFn>,
    clusterer: Mutex<VoiceClusterer>,
}

/// The side a new voice gets by the channel it was first heard in: the
/// system sound is the opponent, the microphone of an online meeting is us,
/// a room microphone (`mixed`) says nothing.
fn default_side(channel: &str) -> Option<&'static str> {
    match channel {
        CHANNEL_SYSTEM => Some(SIDE_OPPONENT),
        CHANNEL_MIC => Some(SIDE_SELF),
        _ => None,
    }
}

impl SegmentSink {
    pub(super) fn new(
        db: std::sync::Arc<MeetingDb>,
        meeting_id: &str,
        embed: Option<EmbedFn>,
        voices: Vec<VoiceCentroid>,
    ) -> Self {
        Self {
            db,
            meeting_id: meeting_id.to_string(),
            embed,
            clusterer: Mutex::new(VoiceClusterer::new(voices)),
        }
    }

    pub(super) fn store(&self, mut segment: Segment, samples: &[f32]) -> Result<Stored> {
        // Only an online meeting has two channels to hear one speech in.
        let online = segment.channel == CHANNEL_MIC || segment.channel == CHANNEL_SYSTEM;
        let mut echoes = Vec::new();
        if online {
            echoes = self
                .db
                .segments_overlapping(
                    &segment.meeting_id,
                    &segment.channel,
                    segment.start_time,
                    segment.end_time,
                )?
                .into_iter()
                .filter(|other| {
                    is_echo(
                        (segment.start_time, segment.end_time, &segment.text),
                        (other.start_time, other.end_time, &other.text),
                    )
                })
                .collect();
            // The system sound is the better copy: the microphone's is dropped.
            if segment.channel == CHANNEL_MIC && !echoes.is_empty() {
                return Ok(Stored::default());
            }
        }

        let mut new_voices = None;
        if let Some((label, is_new)) = self.identify(&segment, samples) {
            segment.voice = Some(label);
            if is_new {
                new_voices = self.db.list_voices(&self.meeting_id).ok();
            }
        }
        self.db.insert_segment(&segment)?;

        let mut removed = Vec::new();
        for echo in echoes {
            // A microphone copy the server already has stays.
            if self.db.delete_unsynced_segment(&echo.id)? {
                removed.push(echo.id);
            }
        }
        Ok(Stored {
            segment: Some(segment),
            removed,
            new_voices,
        })
    }

    /// The phrase's voice and whether it is a new one.
    fn identify(&self, segment: &Segment, samples: &[f32]) -> Option<(String, bool)> {
        let embedding = (self.embed.as_ref()?)(samples)?;
        let duration = (segment.end_time - segment.start_time) as f32;
        let mut clusterer = self.clusterer.lock().unwrap_or_else(|e| e.into_inner());
        let total_before: u32 = clusterer.voices.iter().map(|v| v.count).sum();
        let found = clusterer.assign(&embedding, duration)?;
        let (label, is_new) = match &found {
            VoiceMatch::New(label) => (label.clone(), true),
            VoiceMatch::Existing(label) => (label.clone(), false),
        };
        let voice = clusterer.voices.iter().find(|v| v.label == label)?;
        let result = if is_new {
            self.db.insert_voice(
                &self.meeting_id,
                voice,
                default_side(&segment.channel),
                &segment.channel,
                chrono::Utc::now().timestamp(),
            )
        } else if clusterer.voices.iter().map(|v| v.count).sum::<u32>() != total_before {
            self.db.update_voice_centroid(&self.meeting_id, voice)
        } else {
            Ok(())
        };
        if let Err(e) = result {
            warn!("Cannot save the voice {label}: {e:#}");
        }
        Some((label, is_new))
    }
}

#[cfg(test)]
mod tests {
    use std::sync::Arc;

    use super::super::db::sample_meeting;
    use super::*;

    /// A fake embedding: the first sample picks one of three orthogonal directions.
    fn fake_embed() -> EmbedFn {
        Box::new(|samples| {
            let mut v = vec![0.0; 3];
            v[samples.first().copied().unwrap_or(0.0) as usize % 3] = 1.0;
            Some(v)
        })
    }

    fn sink(embed: Option<EmbedFn>) -> (Arc<MeetingDb>, SegmentSink) {
        let db = Arc::new(MeetingDb::open_in_memory().unwrap());
        db.insert_meeting(&sample_meeting("m", "2026-01-01T10:00:00.000Z"))
            .unwrap();
        let sink = SegmentSink::new(Arc::clone(&db), "m", embed, Vec::new());
        (db, sink)
    }

    fn segment(id: &str, channel: &str, start: f64, end: f64, text: &str) -> Segment {
        Segment {
            id: id.to_string(),
            meeting_id: "m".to_string(),
            channel: channel.to_string(),
            start_time: start,
            end_time: end,
            text: text.to_string(),
            created_at: "2026-01-01T00:00:00.000Z".to_string(),
            synced: false,
            voice: None,
        }
    }

    #[test]
    fn without_a_voice_model_phrases_are_stored_without_a_voice() {
        let (db, sink) = sink(None);
        let stored = sink
            .store(segment("a", "mic", 0.0, 3.0, "привет"), &[0.0; 4])
            .unwrap();
        assert_eq!(stored.segment.unwrap().voice, None);
        assert!(stored.new_voices.is_none());
        assert_eq!(db.list_segments("m").unwrap().len(), 1);
        assert!(db.list_voices("m").unwrap().is_empty());
    }

    #[test]
    fn voices_get_default_sides_by_the_channel_they_first_sounded_in() {
        let (db, sink) = sink(Some(fake_embed()));
        let first = sink
            .store(segment("a", "system", 0.0, 3.0, "первая"), &[0.0])
            .unwrap();
        assert_eq!(first.segment.unwrap().voice.as_deref(), Some("Голос 1"));
        assert_eq!(first.new_voices.unwrap().len(), 1);
        let second = sink
            .store(segment("b", "mic", 10.0, 13.0, "вторая"), &[1.0])
            .unwrap();
        assert_eq!(second.segment.unwrap().voice.as_deref(), Some("Голос 2"));
        // The same voice again (on another channel) is not a new voice.
        let third = sink
            .store(segment("c", "mic", 20.0, 23.0, "третья"), &[0.0])
            .unwrap();
        assert_eq!(third.segment.unwrap().voice.as_deref(), Some("Голос 1"));
        assert!(third.new_voices.is_none());

        let voices = db.list_voices("m").unwrap();
        assert_eq!(voices[0].side.as_deref(), Some("opponent"));
        assert_eq!(voices[0].first_channel, "system");
        assert_eq!(voices[0].count, 2, "a phrase of 3 s updates the centroid");
        assert_eq!(voices[1].side.as_deref(), Some("self"));
    }

    #[test]
    fn a_room_microphone_voice_has_no_side() {
        let (db, sink) = sink(Some(fake_embed()));
        sink.store(segment("a", "mixed", 0.0, 3.0, "в комнате"), &[2.0])
            .unwrap();
        assert_eq!(db.list_voices("m").unwrap()[0].side, None);
        // Nothing to tell the server about it.
        assert!(db.unsynced_voices("m").unwrap().is_empty());
    }

    #[test]
    fn the_clusterer_is_restored_from_the_database() {
        let (db, first) = sink(Some(fake_embed()));
        first
            .store(segment("a", "system", 0.0, 3.0, "раз"), &[0.0])
            .unwrap();
        first
            .store(segment("b", "system", 5.0, 8.0, "два"), &[1.0])
            .unwrap();
        // The meeting is resumed: a new sink, the voices come from the database.
        let resumed = SegmentSink::new(
            Arc::clone(&db),
            "m",
            Some(fake_embed()),
            db.voice_centroids("m").unwrap(),
        );
        let again = resumed
            .store(segment("c", "system", 20.0, 23.0, "три"), &[1.0])
            .unwrap();
        assert_eq!(again.segment.unwrap().voice.as_deref(), Some("Голос 2"));
        let fresh = resumed
            .store(segment("d", "system", 30.0, 33.0, "четыре"), &[2.0])
            .unwrap();
        assert_eq!(fresh.segment.unwrap().voice.as_deref(), Some("Голос 3"));
    }

    #[test]
    fn a_microphone_echo_of_the_system_sound_is_not_stored() {
        let (db, sink) = sink(Some(fake_embed()));
        sink.store(
            segment("sys", "system", 10.0, 14.0, "Добрый день, коллеги"),
            &[0.0],
        )
        .unwrap();
        let echo = sink
            .store(
                segment("mic", "mic", 10.3, 14.2, "добрый день коллеги"),
                &[0.0],
            )
            .unwrap();
        assert!(echo.segment.is_none() && echo.removed.is_empty());
        // The echo does not count towards a voice either.
        assert_eq!(db.list_voices("m").unwrap()[0].count, 1);
        assert_eq!(db.list_segments("m").unwrap().len(), 1);

        // Our own words in the same second stay.
        let own = sink
            .store(
                segment("own", "mic", 10.0, 14.0, "Мы готовы обсудить цену"),
                &[1.0],
            )
            .unwrap();
        assert!(own.segment.is_some());
    }

    #[test]
    fn a_later_system_phrase_replaces_the_unsynced_microphone_copy_only() {
        let (db, sink) = sink(None);
        sink.store(
            segment("m1", "mic", 0.0, 4.0, "Давайте начнём встречу"),
            &[],
        )
        .unwrap();
        sink.store(
            segment("m2", "mic", 5.0, 9.0, "Давайте начнём обсуждение"),
            &[],
        )
        .unwrap();
        db.mark_segments_synced(&["m2".to_string()]).unwrap();

        let first = sink
            .store(
                segment("s1", "system", 0.1, 4.1, "давайте начнем встречу"),
                &[],
            )
            .unwrap();
        assert_eq!(first.removed, ["m1"]);
        let second = sink
            .store(
                segment("s2", "system", 5.1, 9.1, "давайте начнем обсуждение"),
                &[],
            )
            .unwrap();
        assert!(second.removed.is_empty(), "the synced copy stays");

        let ids: Vec<String> = db
            .list_segments("m")
            .unwrap()
            .into_iter()
            .map(|s| s.id)
            .collect();
        assert_eq!(ids, ["s1", "m2", "s2"]);
    }

    #[test]
    fn an_in_person_meeting_never_looks_for_echoes() {
        let (db, sink) = sink(None);
        sink.store(segment("a", "mixed", 0.0, 3.0, "хорошо"), &[])
            .unwrap();
        let again = sink
            .store(segment("b", "mixed", 0.5, 3.0, "хорошо"), &[])
            .unwrap();
        assert!(again.segment.is_some());
        assert_eq!(db.list_segments("m").unwrap().len(), 2);
    }
}
