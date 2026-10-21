//! Online clustering of phrase embeddings into "Голос 1/2/3".

use serde::{Deserialize, Serialize};

/// Cosine to the nearest centroid at or above which the phrase is that voice.
const JOIN_THRESHOLD: f32 = 0.55;
/// Cosine below which the phrase is a new voice (between the two: nearest, no update).
const NEW_THRESHOLD: f32 = 0.45;
/// A new voice is created only from a phrase at least this long.
const MIN_NEW_SECS: f32 = 1.5;
/// A centroid is updated only by phrases at least this long.
const MIN_UPDATE_SECS: f32 = 2.0;

const LABEL_PREFIX: &str = "Голос ";

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct VoiceCentroid {
    pub label: String,
    pub vector: Vec<f32>,
    pub count: u32,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum VoiceMatch {
    Existing(String),
    New(String),
}

pub struct VoiceClusterer {
    pub voices: Vec<VoiceCentroid>,
}

fn norm(v: &[f32]) -> f32 {
    v.iter().map(|x| x * x).sum::<f32>().sqrt()
}

fn cosine(a: &[f32], b: &[f32]) -> f32 {
    let denom = norm(a) * norm(b);
    if a.len() != b.len() || denom <= f32::EPSILON {
        return f32::NEG_INFINITY;
    }
    a.iter().zip(b).map(|(x, y)| x * y).sum::<f32>() / denom
}

fn normalized(v: &[f32]) -> Vec<f32> {
    let n = norm(v);
    if n <= f32::EPSILON {
        return v.to_vec();
    }
    v.iter().map(|x| x / n).collect()
}

impl VoiceClusterer {
    /// Restores the state from the database.
    pub fn new(voices: Vec<VoiceCentroid>) -> Self {
        Self { voices }
    }

    /// Assigns a phrase embedding (`duration_secs` is the phrase length) to a voice.
    /// `None` when the phrase is too short to start a new voice or the embedding is unusable.
    pub fn assign(&mut self, embedding: &[f32], duration_secs: f32) -> Option<VoiceMatch> {
        if embedding.is_empty() || norm(embedding) <= f32::EPSILON {
            return None;
        }
        let nearest = self
            .voices
            .iter()
            .enumerate()
            .map(|(i, v)| (i, cosine(embedding, &v.vector)))
            .filter(|(_, c)| c.is_finite())
            .max_by(|a, b| a.1.total_cmp(&b.1));

        match nearest {
            Some((i, sim)) if sim >= JOIN_THRESHOLD => {
                if duration_secs >= MIN_UPDATE_SECS {
                    self.update(i, embedding);
                }
                Some(VoiceMatch::Existing(self.voices[i].label.clone()))
            }
            Some((i, sim)) if sim >= NEW_THRESHOLD => {
                Some(VoiceMatch::Existing(self.voices[i].label.clone()))
            }
            _ if duration_secs >= MIN_NEW_SECS => {
                let label = format!("{LABEL_PREFIX}{}", self.next_number());
                self.voices.push(VoiceCentroid {
                    label: label.clone(),
                    vector: normalized(embedding),
                    count: 1,
                });
                Some(VoiceMatch::New(label))
            }
            _ => None,
        }
    }

    fn update(&mut self, index: usize, embedding: &[f32]) {
        let voice = &mut self.voices[index];
        let count = voice.count as f32;
        let emb = normalized(embedding);
        let mixed: Vec<f32> = voice
            .vector
            .iter()
            .zip(&emb)
            .map(|(old, new)| (old * count + new) / (count + 1.0))
            .collect();
        voice.vector = normalized(&mixed);
        voice.count = voice.count.saturating_add(1);
    }

    /// Highest existing "Голос N" plus one.
    fn next_number(&self) -> u32 {
        self.voices
            .iter()
            .filter_map(|v| {
                v.label
                    .strip_prefix(LABEL_PREFIX)?
                    .trim()
                    .parse::<u32>()
                    .ok()
            })
            .max()
            .unwrap_or(0)
            + 1
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Unit vector at `angle` radians in the first two dimensions.
    fn dir(angle: f32) -> Vec<f32> {
        vec![angle.cos(), angle.sin(), 0.0, 0.0]
    }

    fn centroid(label: &str, angle: f32, count: u32) -> VoiceCentroid {
        VoiceCentroid {
            label: label.into(),
            vector: dir(angle),
            count,
        }
    }

    #[test]
    fn first_long_phrase_creates_voice_one() {
        let mut c = VoiceClusterer::new(vec![]);
        assert_eq!(
            c.assign(&dir(0.0), 3.0),
            Some(VoiceMatch::New("Голос 1".into()))
        );
        assert_eq!(c.voices.len(), 1);
        assert_eq!(c.voices[0].count, 1);
    }

    #[test]
    fn similar_phrase_joins_and_moves_centroid() {
        let mut c = VoiceClusterer::new(vec![centroid("Голос 1", 0.0, 1)]);
        // cos(0.5) = 0.88 >= JOIN
        assert_eq!(
            c.assign(&dir(0.5), 3.0),
            Some(VoiceMatch::Existing("Голос 1".into()))
        );
        assert_eq!(c.voices[0].count, 2);
        let v = &c.voices[0].vector;
        assert!((norm(v) - 1.0).abs() < 1e-5);
        assert!(v[1] > 0.0, "centroid moved toward the new phrase");
    }

    #[test]
    fn dissimilar_phrase_becomes_new_voice() {
        let mut c = VoiceClusterer::new(vec![centroid("Голос 1", 0.0, 3)]);
        // cos(1.4) = 0.17 < NEW
        assert_eq!(
            c.assign(&dir(1.4), 2.0),
            Some(VoiceMatch::New("Голос 2".into()))
        );
        assert_eq!(c.voices.len(), 2);
        assert_eq!(c.voices[0].count, 3);
    }

    #[test]
    fn gray_zone_picks_nearest_without_update() {
        let mut c = VoiceClusterer::new(vec![
            centroid("Голос 1", 0.0, 4),
            centroid("Голос 2", 3.0, 4),
        ]);
        let before = c.voices[0].vector.clone();
        // cos(1.05) = 0.50: between NEW (0.45) and JOIN (0.55); nearest to Голос 1
        assert_eq!(
            c.assign(&dir(1.05), 5.0),
            Some(VoiceMatch::Existing("Голос 1".into()))
        );
        assert_eq!(c.voices.len(), 2);
        assert_eq!(c.voices[0].count, 4);
        assert_eq!(c.voices[0].vector, before);
    }

    #[test]
    fn short_phrase_never_creates_and_rarely_updates() {
        let mut c = VoiceClusterer::new(vec![centroid("Голос 1", 0.0, 1)]);
        // Dissimilar and shorter than 1.5 s: unknown.
        assert_eq!(c.assign(&dir(1.4), 1.0), None);
        assert_eq!(c.voices.len(), 1);
        // Similar but shorter than 2 s: joins, centroid untouched.
        assert_eq!(
            c.assign(&dir(0.3), 1.8),
            Some(VoiceMatch::Existing("Голос 1".into()))
        );
        assert_eq!(c.voices[0].count, 1);
        // 1.5 s is enough for a new voice.
        assert_eq!(
            c.assign(&dir(1.4), 1.5),
            Some(VoiceMatch::New("Голос 2".into()))
        );
    }

    #[test]
    fn numbering_continues_after_restore() {
        let mut c = VoiceClusterer::new(vec![
            centroid("Голос 1", 0.0, 5),
            centroid("Голос 3", 1.5, 2),
        ]);
        assert_eq!(
            c.assign(&dir(3.0), 3.0),
            Some(VoiceMatch::New("Голос 4".into()))
        );
    }

    #[test]
    fn bad_embeddings_are_ignored() {
        let mut c = VoiceClusterer::new(vec![]);
        assert_eq!(c.assign(&[], 3.0), None);
        assert_eq!(c.assign(&[0.0, 0.0], 3.0), None);
        assert!(c.voices.is_empty());
    }

    #[test]
    fn centroid_roundtrips_through_json() {
        let json = serde_json::to_string(&centroid("Голос 2", 0.3, 7)).unwrap();
        let back: VoiceCentroid = serde_json::from_str(&json).unwrap();
        assert_eq!((back.label.as_str(), back.count), ("Голос 2", 7));
    }
}
