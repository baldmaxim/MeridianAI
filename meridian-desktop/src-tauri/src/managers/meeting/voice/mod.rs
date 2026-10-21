//! Offline "whose voice" engine for meeting phrases: a speaker embedding
//! (CAM++ ONNX through `tract`, Kaldi-compatible fbank on `rustfft`) plus online
//! clustering into "Голос 1/2/3". Engine only: recording and the database
//! call it from the outside.

mod cluster;
mod embed;
mod fbank;

pub use cluster::{VoiceCentroid, VoiceClusterer, VoiceMatch};
pub use embed::VoiceEmbedder;

/// File name of the speaker model inside `resources/models` (fetched by
/// `scripts/fetch-voice-model.mjs`).
pub const VOICE_MODEL_FILE: &str = "campplus-sv-zh-en-16k.onnx";
