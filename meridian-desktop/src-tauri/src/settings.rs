use crate::secrets::SecretStore;
use log::warn;
use serde::de::{self, Visitor};
use serde::{Deserialize, Deserializer, Serialize};
use specta::Type;
use tauri::AppHandle;
use tauri_plugin_store::StoreExt;

#[derive(Serialize, Debug, Clone, Copy, PartialEq, Eq, Type)]
#[serde(rename_all = "lowercase")]
pub enum LogLevel {
    Trace,
    Debug,
    Info,
    Warn,
    Error,
}

// Custom deserializer to handle both old numeric format (1-5) and new string format ("trace", "debug", etc.)
impl<'de> Deserialize<'de> for LogLevel {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        struct LogLevelVisitor;

        impl<'de> Visitor<'de> for LogLevelVisitor {
            type Value = LogLevel;

            fn expecting(&self, formatter: &mut std::fmt::Formatter) -> std::fmt::Result {
                formatter.write_str("a string or integer representing log level")
            }

            fn visit_str<E: de::Error>(self, value: &str) -> Result<LogLevel, E> {
                match value.to_lowercase().as_str() {
                    "trace" => Ok(LogLevel::Trace),
                    "debug" => Ok(LogLevel::Debug),
                    "info" => Ok(LogLevel::Info),
                    "warn" => Ok(LogLevel::Warn),
                    "error" => Ok(LogLevel::Error),
                    _ => Err(E::unknown_variant(
                        value,
                        &["trace", "debug", "info", "warn", "error"],
                    )),
                }
            }

            fn visit_u64<E: de::Error>(self, value: u64) -> Result<LogLevel, E> {
                match value {
                    1 => Ok(LogLevel::Trace),
                    2 => Ok(LogLevel::Debug),
                    3 => Ok(LogLevel::Info),
                    4 => Ok(LogLevel::Warn),
                    5 => Ok(LogLevel::Error),
                    _ => Err(E::invalid_value(de::Unexpected::Unsigned(value), &"1-5")),
                }
            }
        }

        deserializer.deserialize_any(LogLevelVisitor)
    }
}

impl From<LogLevel> for tauri_plugin_log::LogLevel {
    fn from(level: LogLevel) -> Self {
        match level {
            LogLevel::Trace => tauri_plugin_log::LogLevel::Trace,
            LogLevel::Debug => tauri_plugin_log::LogLevel::Debug,
            LogLevel::Info => tauri_plugin_log::LogLevel::Info,
            LogLevel::Warn => tauri_plugin_log::LogLevel::Warn,
            LogLevel::Error => tauri_plugin_log::LogLevel::Error,
        }
    }
}

#[derive(Serialize, Deserialize, Debug, Clone, Copy, PartialEq, Eq, Type, Default)]
#[serde(rename_all = "snake_case")]
pub enum ModelUnloadTimeout {
    Never,
    Immediately,
    Min2,
    #[default]
    Min5,
    Min10,
    Min15,
    Hour1,
    Sec15, // Debug mode only
}

/// Script applied to Mandarin and Cantonese output. Other languages are never
/// converted.
#[derive(Serialize, Deserialize, Debug, Clone, Copy, PartialEq, Eq, Type, Default)]
#[serde(rename_all = "snake_case")]
pub enum ChineseScript {
    /// Keep whatever script the model produced.
    #[default]
    AsTranscribed,
    Simplified,
    Traditional,
}

impl ModelUnloadTimeout {
    pub fn to_minutes(self) -> Option<u64> {
        match self {
            ModelUnloadTimeout::Never => None,
            ModelUnloadTimeout::Immediately => Some(0), // Special case for immediate unloading
            ModelUnloadTimeout::Min2 => Some(2),
            ModelUnloadTimeout::Min5 => Some(5),
            ModelUnloadTimeout::Min10 => Some(10),
            ModelUnloadTimeout::Min15 => Some(15),
            ModelUnloadTimeout::Hour1 => Some(60),
            ModelUnloadTimeout::Sec15 => Some(0), // Special case for debug - handled separately
        }
    }

    pub fn to_seconds(self) -> Option<u64> {
        match self {
            ModelUnloadTimeout::Never => None,
            ModelUnloadTimeout::Immediately => Some(0), // Special case for immediate unloading
            ModelUnloadTimeout::Sec15 => Some(15),
            _ => self.to_minutes().map(|m| m * 60),
        }
    }
}

/// UI appearance mode. `System` follows the OS `prefers-color-scheme`; `Light`
/// and `Dark` force one of the two palettes Handy already ships.
#[derive(Serialize, Deserialize, Debug, Clone, Copy, PartialEq, Eq, Type)]
#[serde(rename_all = "snake_case")]
pub enum Theme {
    System,
    Light,
    Dark,
}

#[derive(Serialize, Deserialize, Debug, Clone, Copy, PartialEq, Eq, Type, Default)]
#[serde(rename_all = "snake_case")]
pub enum TranscribeAcceleratorSetting {
    #[default]
    Auto,
    Cpu,
    Gpu,
}

#[derive(Serialize, Deserialize, Debug, Clone, Copy, PartialEq, Eq, Type, Default)]
#[serde(rename_all = "snake_case")]
pub enum VadBackend {
    #[default]
    Silero,
    Earshot,
}

/// Where a meeting's live text comes from.
#[derive(Serialize, Deserialize, Debug, Clone, Copy, PartialEq, Eq, Type, Default)]
#[serde(rename_all = "snake_case")]
pub enum RecognitionMode {
    /// The server (ElevenLabs) recognizes the sound as it is recorded; without
    /// a connection the meeting is recorded like a dictaphone (no live text).
    #[default]
    Online,
    /// The local model (GigaAM) recognizes phrases on this computer.
    Local,
}

/* still handy for composing the initial JSON in the store ------------- */
/// The container-level `serde(default)` (backed by the `Default` impl below)
/// guarantees every field — including ones added in the future — falls back to
/// its `get_default_settings()` value when missing from a stored settings
/// object, so a partial store can never fail the whole load (#1619).
/// Field-level defaults below take precedence where present.
#[derive(Serialize, Deserialize, Debug, Clone, Type)]
#[serde(default)]
pub struct AppSettings {
    /// Internal settings schema marker for one-time migrations. Fresh installs
    /// start at the current version; existing stores missing this key are
    /// treated as version 0 and migrated forward.
    #[serde(default = "default_settings_schema_version")]
    pub settings_schema_version: u32,
    #[serde(default = "default_start_hidden")]
    pub start_hidden: bool,
    #[serde(default = "default_model")]
    pub selected_model: String,
    #[serde(default)]
    pub onboarding_completed: bool,
    #[serde(default)]
    pub selected_microphone: Option<String>,
    /// The device whose sound an online meeting records (the other side's
    /// voice). `None`: the default playback device / first monitor.
    #[serde(default)]
    pub meeting_system_device: Option<String>,
    /// Which input channel to use on the selected microphone device.
    /// None means "average all channels" (original behavior).
    #[serde(default)]
    pub selected_channel: Option<u16>,
    #[serde(default = "default_selected_language")]
    pub selected_language: String,
    #[serde(default = "default_debug_mode")]
    pub debug_mode: bool,
    #[serde(default = "default_log_level")]
    pub log_level: LogLevel,
    #[serde(default)]
    pub custom_words: Vec<String>,
    #[serde(default)]
    pub model_unload_timeout: ModelUnloadTimeout,
    #[serde(default = "default_word_correction_threshold")]
    pub word_correction_threshold: f64,
    #[serde(default = "default_app_language")]
    pub app_language: String,
    #[serde(default = "default_theme")]
    pub theme: Theme,
    /// Accent color preset id (see `ACCENT_COLORS`); the frontend maps it to a
    /// palette via `data-accent`.
    #[serde(default = "default_accent_color")]
    pub accent_color: String,
    #[serde(default)]
    pub experimental_enabled: bool,
    #[serde(default = "default_show_tray_icon")]
    pub show_tray_icon: bool,
    #[serde(default = "default_filler_word_removal_enabled")]
    pub filler_word_removal_enabled: bool,
    #[serde(default)]
    pub custom_filler_words: Option<Vec<String>>,
    #[serde(default = "default_number_normalization_enabled")]
    pub number_normalization_enabled: bool,
    /// Fresh installs default from the OS locale; existing stores are migrated
    /// in `apply_settings_migrations`.
    #[serde(default)]
    pub chinese_script: ChineseScript,
    #[serde(default)]
    pub transcribe_accelerator: TranscribeAcceleratorSetting,
    /// Stable transcribe.cpp device selector. This is derived from the backend's
    /// `device_id` when available (or its name for backends such as Metal),
    /// never from the process-local device registry index.
    #[serde(
        default = "default_transcribe_gpu_device",
        deserialize_with = "deserialize_transcribe_gpu_device"
    )]
    pub transcribe_gpu_device: Option<String>,
    /// Experimental detector implementation. Silero remains the stable default.
    #[serde(default)]
    pub vad_backend: VadBackend,
    /// Decode long audio in chunks cut at pauses, for models whose accuracy
    /// degrades on long audio.
    #[serde(default = "default_long_form_chunking")]
    pub long_form_chunking: bool,
    /// Meridian server for the login form: the last one signed in to. The
    /// signed-in account keeps its own copy in `account.json`.
    #[serde(default = "default_server_url")]
    pub server_url: String,
    /// Send the meetings' audio to the server together with the text.
    #[serde(default = "default_upload_audio")]
    pub upload_audio: bool,
    /// Live text of a meeting: the server (default) or the local model.
    #[serde(default)]
    pub recognition_mode: RecognitionMode,
}

fn default_server_url() -> String {
    crate::managers::sync::account::DEFAULT_SERVER_URL.to_string()
}

fn default_upload_audio() -> bool {
    true
}

fn default_model() -> String {
    "".to_string()
}

const CURRENT_SETTINGS_SCHEMA_VERSION: u32 = 3;

/// From this version on the removed post-processing's API keys are gone from
/// the OS credential store.
const PURGED_POST_PROCESS_KEYS_SCHEMA_VERSION: u64 = 3;

fn default_settings_schema_version() -> u32 {
    CURRENT_SETTINGS_SCHEMA_VERSION
}

fn default_start_hidden() -> bool {
    false
}

fn default_selected_language() -> String {
    "ru".to_string()
}

fn default_long_form_chunking() -> bool {
    true
}

fn default_filler_word_removal_enabled() -> bool {
    true
}

fn default_number_normalization_enabled() -> bool {
    true
}

fn default_chinese_script() -> ChineseScript {
    tauri_plugin_os::locale()
        .and_then(|locale| crate::chinese_script::chinese_script_for_locale(&locale))
        .unwrap_or_default()
}

fn default_debug_mode() -> bool {
    false
}

fn default_log_level() -> LogLevel {
    LogLevel::Debug
}

fn default_word_correction_threshold() -> f64 {
    0.18
}

fn default_theme() -> Theme {
    Theme::Dark
}

/// Accent color presets the UI knows how to render.
pub const ACCENT_COLORS: [&str; 7] = [
    "amber", "blue", "green", "violet", "orange", "graphite", "pink",
];

fn default_accent_color() -> String {
    "amber".to_string()
}

fn default_app_language() -> String {
    "ru".to_string()
}

fn default_show_tray_icon() -> bool {
    true
}

fn default_transcribe_gpu_device() -> Option<String> {
    None // automatic device selection
}

/// Accept the 0.1-era integer registry index long enough for the schema
/// migration to clear it. Device indices are process-local in transcribe.cpp
/// 0.2 and must never be carried across launches.
fn deserialize_transcribe_gpu_device<'de, D>(deserializer: D) -> Result<Option<String>, D::Error>
where
    D: Deserializer<'de>,
{
    match Option::<serde_json::Value>::deserialize(deserializer)? {
        None => Ok(None),
        Some(serde_json::Value::String(value)) => Ok(Some(value)),
        Some(serde_json::Value::Number(_)) => Ok(None),
        Some(_) => Err(de::Error::custom(
            "transcribe GPU device must be a string, integer, or null",
        )),
    }
}

pub const SETTINGS_STORE_PATH: &str = "settings_store.json";

pub fn get_default_settings() -> AppSettings {
    AppSettings {
        settings_schema_version: default_settings_schema_version(),
        start_hidden: default_start_hidden(),
        selected_model: "".to_string(),
        onboarding_completed: false,
        selected_microphone: None,
        meeting_system_device: None,
        selected_channel: None,
        selected_language: default_selected_language(),
        debug_mode: false,
        log_level: default_log_level(),
        custom_words: Vec::new(),
        model_unload_timeout: ModelUnloadTimeout::default(),
        word_correction_threshold: default_word_correction_threshold(),
        app_language: default_app_language(),
        theme: default_theme(),
        accent_color: default_accent_color(),
        experimental_enabled: false,
        show_tray_icon: default_show_tray_icon(),
        filler_word_removal_enabled: default_filler_word_removal_enabled(),
        custom_filler_words: None,
        number_normalization_enabled: default_number_normalization_enabled(),
        chinese_script: default_chinese_script(),
        transcribe_accelerator: TranscribeAcceleratorSetting::default(),
        transcribe_gpu_device: default_transcribe_gpu_device(),
        vad_backend: VadBackend::default(),
        long_form_chunking: default_long_form_chunking(),
        server_url: default_server_url(),
        upload_audio: default_upload_audio(),
        recognition_mode: RecognitionMode::default(),
    }
}

impl Default for AppSettings {
    fn default() -> Self {
        get_default_settings()
    }
}

pub fn get_settings(app: &AppHandle) -> AppSettings {
    let store = app
        .store(crate::portable::store_path(SETTINGS_STORE_PATH))
        .expect("Failed to initialize store");

    // Settings reads also persist one-time migrations. Migration helpers are
    // idempotent, so this converges after the first read of an older store.
    let (settings, dirty) = if let Some(settings_value) = store.get("settings") {
        let (mut settings, mut updated) =
            match serde_json::from_value::<AppSettings>(settings_value.clone()) {
                Ok(settings) => (settings, false),
                Err(e) => {
                    warn!("Failed to parse stored settings ({e}); salvaging valid fields");
                    (salvage_settings(&settings_value), true)
                }
            };

        if apply_settings_migrations(&mut settings, &settings_value) {
            updated = true;
        }

        // Keys of the removed LLM post-processing may still sit in the OS
        // credential store. If it can't be reached now, stay on the old schema
        // version so the next launch tries again (never below 2: that would
        // re-run the GPU device reset).
        let stored_version = stored_schema_version(&settings_value);
        if stored_version < PURGED_POST_PROCESS_KEYS_SCHEMA_VERSION
            && !purge_post_process_api_keys(crate::secrets::global(), &settings_value)
        {
            settings.settings_schema_version = u32::try_from(stored_version)
                .unwrap_or(CURRENT_SETTINGS_SCHEMA_VERSION)
                .max(2);
        }

        (settings, updated)
    } else {
        (get_default_settings(), true)
    };

    if dirty {
        store.set("settings", settings_store_value(&settings));
    }

    settings
}

/// Providers of the removed post-processing; each had an API key in the OS
/// credential store under `post_process_api_key.<provider id>`.
const LEGACY_POST_PROCESS_PROVIDER_IDS: [&str; 8] = [
    "openai",
    "zai",
    "openrouter",
    "anthropic",
    "groq",
    "cerebras",
    "bedrock_mantle",
    "custom",
];

/// Deletes the removed post-processing's API keys from the OS credential
/// store: the built-in providers' and any provider id the old file listed.
/// Returns false if the store could not be reached.
fn purge_post_process_api_keys(secrets: &SecretStore, stored: &serde_json::Value) -> bool {
    let mut provider_ids: Vec<String> = LEGACY_POST_PROCESS_PROVIDER_IDS
        .iter()
        .map(|id| (*id).to_string())
        .collect();
    if let Some(keys) = stored
        .get("post_process_api_keys")
        .and_then(|keys| keys.as_object())
    {
        provider_ids.extend(keys.keys().cloned());
    }
    provider_ids.iter().all(|id| {
        secrets
            .delete(&format!("post_process_api_key.{id}"))
            .is_ok()
    })
}

fn stored_schema_version(stored: &serde_json::Value) -> u64 {
    stored
        .get("settings_schema_version")
        .and_then(|v| v.as_u64())
        .unwrap_or(0)
}

/// The JSON to persist in the settings file.
fn settings_store_value(settings: &AppSettings) -> serde_json::Value {
    serde_json::to_value(settings).expect("settings serialize to JSON")
}

/// Rebuilds settings from a store value that failed to deserialize as a whole.
/// Every stored field that is individually valid is kept; only broken values
/// (e.g. an enum variant written by a newer or older version) fall back to
/// their default. This means one bad field can never reset the rest of the
/// user's configuration (#1619).
fn salvage_settings(stored: &serde_json::Value) -> AppSettings {
    let Some(stored_map) = stored.as_object() else {
        warn!("Stored settings are not a JSON object; falling back to defaults");
        return get_default_settings();
    };

    let mut merged = serde_json::to_value(get_default_settings())
        .expect("default settings serialize to a JSON object");

    for (key, value) in stored_map {
        let previous = merged
            .as_object_mut()
            .expect("merged settings stay an object")
            .insert(key.clone(), value.clone());
        if serde_json::from_value::<AppSettings>(merged.clone()).is_err() {
            // Log only the key: values may hold secrets (e.g. API keys).
            warn!("Dropping invalid settings field '{key}', keeping its default");
            let map = merged
                .as_object_mut()
                .expect("merged settings stay an object");
            match previous {
                Some(previous) => map.insert(key.clone(), previous),
                None => map.remove(key),
            };
        }
    }

    serde_json::from_value(merged).unwrap_or_else(|e| {
        warn!("Failed to reassemble salvaged settings ({e}); falling back to defaults");
        get_default_settings()
    })
}

fn apply_settings_migrations(
    settings: &mut AppSettings,
    settings_value: &serde_json::Value,
) -> bool {
    let mut updated = false;

    // One-time onboarding migration: users with an explicit selected model have
    // already made it through model selection. Users who merely have compatible
    // files on disk should still see onboarding.
    if settings_value.get("onboarding_completed").is_none() {
        settings.onboarding_completed = !settings.selected_model.is_empty();
        updated = true;
    }

    // One-time Chinese script migration: the script used to be chosen through
    // `zh-Hans`/`zh-Hant` language intents. Split those into the recognition
    // language and the script setting; every other upgrading user keeps the
    // unconverted output they had. Only fresh installs get the locale default.
    if settings_value.get("chinese_script").is_none() {
        settings.chinese_script = match settings.selected_language.as_str() {
            "zh-Hans" => ChineseScript::Simplified,
            "zh-Hant" => ChineseScript::Traditional,
            _ => ChineseScript::AsTranscribed,
        };
        if settings.chinese_script != ChineseScript::AsTranscribed {
            settings.selected_language = "zh".to_string();
        }
        updated = true;
    }

    let stored_schema_version = stored_schema_version(settings_value);
    if stored_schema_version < 1 {
        // Before schema 1 this was a UI ordinal. Preserve the original safety
        // migration: a positive selection was ambiguous even in 0.1.
        let had_positive_legacy_selection = settings_value
            .get("transcribe_gpu_device")
            .and_then(|value| value.as_i64())
            .is_some_and(|value| value > 0);
        if had_positive_legacy_selection {
            settings.transcribe_accelerator = TranscribeAcceleratorSetting::Auto;
        }
    }
    if stored_schema_version < 2 {
        // transcribe.cpp 0.2 replaced integer registry indices with opaque
        // process-local handles. Clear every old index once.
        settings.transcribe_gpu_device = default_transcribe_gpu_device();
        updated = true;
    }
    if stored_schema_version < u64::from(CURRENT_SETTINGS_SCHEMA_VERSION) {
        settings.settings_schema_version = CURRENT_SETTINGS_SCHEMA_VERSION;
        updated = true;
    }

    // The generic GPU choice was removed in favor of Auto or an exact device.
    // Normalize settings created by builds that exposed that short-lived option.
    if settings.transcribe_accelerator == TranscribeAcceleratorSetting::Gpu
        && settings.transcribe_gpu_device.is_none()
    {
        settings.transcribe_accelerator = TranscribeAcceleratorSetting::Auto;
        updated = true;
    }

    updated
}

pub fn write_settings(app: &AppHandle, settings: AppSettings) {
    let store = app
        .store(crate::portable::store_path(SETTINGS_STORE_PATH))
        .expect("Failed to initialize store");

    store.set("settings", settings_store_value(&settings));
}

#[cfg(test)]
mod tests {
    use super::*;

    fn default_settings_json() -> serde_json::Value {
        serde_json::to_value(get_default_settings()).unwrap()
    }

    /// Every field must survive a partial store: a missing key must never fail
    /// the whole-settings parse (#1619). `json!({})` is the extreme case.
    #[test]
    fn empty_store_parses_with_defaults() {
        let settings: AppSettings = serde_json::from_value(serde_json::json!({}))
            .expect("all AppSettings fields need serde defaults");
        assert!(settings.filler_word_removal_enabled);
        assert!(settings.long_form_chunking);
    }

    /// Frozen snapshot of a real v0.9.0-era settings store, as written to
    /// disk. This pins backwards compatibility: it must always parse strictly
    /// (no salvage). Schema migrations may then rewrite fields whose native
    /// meaning changed. Its dictation-era keys (post-processing, history,
    /// recording options) no longer exist in `AppSettings`: they must be
    /// ignored on load and gone once the settings are written back.
    ///
    /// If a schema change breaks this test, do NOT just update the fixture —
    /// it stands in for the stores on users' machines. Add a
    /// `#[serde(alias)]`/`#[serde(other)]` or a one-time migration in
    /// `apply_settings_migrations` so old values keep loading, and only extend
    /// the fixture alongside that.
    #[test]
    fn frozen_v0_9_store_parses_strictly_then_migrates_device_index() {
        // Note "log_level": 2 — the legacy numeric format, kept deliberately.
        let stored: serde_json::Value = serde_json::from_str(
            r##"{
            "settings_schema_version": 1,
            "bindings": {
                "transcribe": {
                    "id": "transcribe",
                    "name": "Transcribe",
                    "description": "Converts your speech into text.",
                    "default_binding": "option+space",
                    "current_binding": "f13"
                },
                "transcribe_with_post_process": {
                    "id": "transcribe_with_post_process",
                    "name": "Transcribe with Post-Processing",
                    "description": "Converts your speech into text and applies AI post-processing.",
                    "default_binding": "option+shift+space",
                    "current_binding": "option+shift+space"
                },
                "cancel": {
                    "id": "cancel",
                    "name": "Cancel",
                    "description": "Cancels the current recording.",
                    "default_binding": "escape",
                    "current_binding": "escape"
                }
            },
            "push_to_talk": false,
            "audio_feedback": true,
            "audio_feedback_volume": 0.8,
            "sound_theme": "pop",
            "start_hidden": false,
            "autostart_enabled": true,
            "update_checks_enabled": true,
            "show_whats_new_on_update": true,
            "whats_new_last_seen_version": "0.9.0",
            "selected_model": "whisper-large-v3-turbo",
            "onboarding_completed": true,
            "always_on_microphone": false,
            "selected_microphone": "MacBook Pro Microphone",
            "clamshell_microphone": null,
            "selected_output_device": null,
            "translate_to_english": false,
            "selected_language": "en",
            "overlay_position": "bottom",
            "debug_mode": false,
            "log_level": 2,
            "custom_words": ["Meridian"],
            "model_unload_timeout": "min5",
            "word_correction_threshold": 0.18,
            "history_limit": 5,
            "recording_retention_period": "preserve_limit",
            "paste_method": "ctrl_v",
            "clipboard_handling": "dont_modify",
            "auto_submit": false,
            "auto_submit_key": "enter",
            "post_process_enabled": false,
            "post_process_provider_id": "openai",
            "post_process_providers": [
                {
                    "id": "openai",
                    "label": "OpenAI",
                    "base_url": "https://api.openai.com/v1",
                    "allow_base_url_edit": false,
                    "models_endpoint": null,
                    "supports_structured_output": true
                }
            ],
            "post_process_api_keys": { "openai": "" },
            "post_process_models": { "openai": "gpt-4o-mini" },
            "post_process_prompts": [
                { "id": "default", "name": "Default", "prompt": "Clean up the transcript." }
            ],
            "post_process_selected_prompt_id": null,
            "mute_while_recording": false,
            "append_trailing_space": false,
            "app_language": "en",
            "experimental_enabled": false,
            "lazy_stream_close": false,
            "keyboard_implementation": "handy_keys",
            "show_tray_icon": true,
            "paste_delay_ms": 60,
            "typing_tool": "auto",
            "external_script_path": null,
            "custom_filler_words": null,
            "transcribe_accelerator": "gpu",
            "ort_accelerator": "auto",
            "transcribe_gpu_device": 0,
            "extra_recording_buffer_ms": 0,
            "vad_enabled": true,
            "overlay_style": "live"
        }"##,
        )
        .expect("fixture is valid JSON");

        let mut settings: AppSettings = serde_json::from_value(stored.clone())
            .expect("a stored v0.9.0 settings object must keep parsing strictly");

        assert_eq!(settings.selected_model, "whisper-large-v3-turbo");
        assert_eq!(settings.log_level, LogLevel::Debug);
        assert_eq!(
            settings.theme,
            Theme::Dark,
            "no stored theme: the new default applies"
        );
        assert!(settings.filler_word_removal_enabled);
        assert_eq!(settings.vad_backend, VadBackend::Silero);
        assert!(
            settings.long_form_chunking,
            "chunking is on for settings saved before it existed"
        );

        // The 0.1 integer device index is cleared once for transcribe.cpp 0.2.
        // Without an exact device, the retired generic GPU choice becomes Auto.
        assert!(apply_settings_migrations(&mut settings, &stored));
        assert_eq!(
            settings.settings_schema_version,
            CURRENT_SETTINGS_SCHEMA_VERSION
        );
        assert_eq!(
            settings.transcribe_accelerator,
            TranscribeAcceleratorSetting::Auto
        );
        assert_eq!(settings.transcribe_gpu_device, None);

        // Written back, the removed keys are gone for good (the old
        // post-processing API keys included).
        let rewritten = settings_store_value(&settings);
        for key in [
            "post_process_enabled",
            "post_process_api_keys",
            "post_process_prompts",
            "history_limit",
            "recording_retention_period",
            "mute_while_recording",
            "lazy_stream_close",
            "always_on_microphone",
            "clamshell_microphone",
            "extra_recording_buffer_ms",
            "vad_enabled",
            "voice_commands_enabled",
            "translate_to_english",
            "bindings",
        ] {
            assert!(rewritten.get(key).is_none(), "{key} survived");
        }
    }

    #[test]
    fn salvage_preserves_valid_fields_when_one_value_is_invalid() {
        let mut stored = default_settings_json();
        let map = stored.as_object_mut().unwrap();
        map.insert(
            "selected_model".into(),
            serde_json::json!("parakeet-tdt-0.6b-v3"),
        );
        map.insert("onboarding_completed".into(), serde_json::json!(true));
        // An enum variant this build doesn't know, e.g. written by a newer
        // version before a downgrade.
        map.insert("theme".into(), serde_json::json!("theremin"));
        map.insert("accent_color".into(), serde_json::json!("graphite"));

        // Precondition: this is exactly the whole-store parse failure from
        // #1619 that used to reset everything to defaults.
        assert!(serde_json::from_value::<AppSettings>(stored.clone()).is_err());

        let salvaged = salvage_settings(&stored);
        assert_eq!(salvaged.selected_model, "parakeet-tdt-0.6b-v3");
        assert!(salvaged.onboarding_completed);
        assert_eq!(salvaged.accent_color, "graphite");
        assert_eq!(salvaged.theme, default_theme());
    }

    #[test]
    fn salvage_drops_only_wrong_typed_fields() {
        let mut stored = default_settings_json();
        let map = stored.as_object_mut().unwrap();
        map.insert(
            "word_correction_threshold".into(),
            serde_json::json!("sixty"),
        );
        map.insert("theme".into(), serde_json::json!(42));
        map.insert("custom_words".into(), serde_json::json!(["handy"]));

        assert!(serde_json::from_value::<AppSettings>(stored.clone()).is_err());

        let salvaged = salvage_settings(&stored);
        assert_eq!(
            salvaged.word_correction_threshold,
            default_word_correction_threshold()
        );
        assert_eq!(salvaged.theme, default_theme());
        assert_eq!(salvaged.custom_words, vec!["handy".to_string()]);
    }

    #[test]
    fn salvage_of_poisoned_list_keeps_other_fields() {
        let mut stored = default_settings_json();
        let map = stored.as_object_mut().unwrap();
        // One malformed entry poisons the whole list, but must not take the
        // rest of the settings down with it.
        map.insert("custom_words".into(), serde_json::json!([{ "id": 42 }]));
        map.insert("selected_model".into(), serde_json::json!("whisper-small"));

        assert!(serde_json::from_value::<AppSettings>(stored.clone()).is_err());

        let salvaged = salvage_settings(&stored);
        assert_eq!(salvaged.selected_model, "whisper-small");
        assert!(salvaged.custom_words.is_empty());
    }

    #[test]
    fn salvage_tolerates_unknown_keys() {
        let mut stored = default_settings_json();
        let map = stored.as_object_mut().unwrap();
        map.insert(
            "field_from_the_future".into(),
            serde_json::json!({ "nested": true }),
        );
        map.insert("selected_model".into(), serde_json::json!("kept"));
        map.insert("theme".into(), serde_json::json!("theremin"));

        let salvaged = salvage_settings(&stored);
        assert_eq!(salvaged.selected_model, "kept");
        assert_eq!(salvaged.theme, default_theme());
    }

    #[test]
    fn salvage_of_non_object_store_falls_back_to_defaults() {
        for stored in [
            serde_json::json!("corrupt"),
            serde_json::json!(null),
            serde_json::json!([1, 2, 3]),
        ] {
            let salvaged = salvage_settings(&stored);
            assert_eq!(
                serde_json::to_value(&salvaged).unwrap(),
                default_settings_json()
            );
        }
    }

    #[test]
    fn default_settings_use_the_current_schema_version() {
        let settings = get_default_settings();
        assert_eq!(
            settings.settings_schema_version,
            CURRENT_SETTINGS_SCHEMA_VERSION
        );
    }

    #[test]
    fn chinese_script_migration_only_carries_over_legacy_intents() {
        for (intent, language, script) in [
            ("zh-Hans", "zh", ChineseScript::Simplified),
            ("zh-Hant", "zh", ChineseScript::Traditional),
            ("auto", "auto", ChineseScript::AsTranscribed),
        ] {
            let mut settings = get_default_settings();
            settings.selected_language = intent.to_string();
            settings.chinese_script = ChineseScript::Traditional;
            let raw = serde_json::json!({ "selected_language": intent });

            assert!(apply_settings_migrations(&mut settings, &raw));
            assert_eq!(settings.selected_language, language);
            assert_eq!(settings.chinese_script, script);
        }
    }

    #[test]
    fn gpu_device_migration_resets_legacy_positive_selection_to_auto() {
        let mut settings = get_default_settings();
        settings.transcribe_accelerator = TranscribeAcceleratorSetting::Gpu;

        let raw = serde_json::json!({
            "transcribe_accelerator": "gpu",
            "transcribe_gpu_device": 2
        });

        assert!(apply_settings_migrations(&mut settings, &raw));
        assert_eq!(
            settings.transcribe_accelerator,
            TranscribeAcceleratorSetting::Auto
        );
        assert_eq!(settings.transcribe_gpu_device, None);
        assert_eq!(
            settings.settings_schema_version,
            CURRENT_SETTINGS_SCHEMA_VERSION
        );
    }

    #[test]
    fn gpu_device_migration_maps_v1_automatic_gpu_to_auto() {
        let raw = serde_json::json!({
            "settings_schema_version": 1,
            "transcribe_accelerator": "gpu",
            "transcribe_gpu_device": 2
        });
        let mut settings: AppSettings = serde_json::from_value(raw.clone()).unwrap();

        assert!(apply_settings_migrations(&mut settings, &raw));
        assert_eq!(
            settings.transcribe_accelerator,
            TranscribeAcceleratorSetting::Auto
        );
        assert_eq!(settings.transcribe_gpu_device, None);
    }

    #[test]
    fn gpu_device_migration_maps_current_automatic_gpu_to_auto() {
        let raw = serde_json::json!({
            "settings_schema_version": CURRENT_SETTINGS_SCHEMA_VERSION,
            "onboarding_completed": false,
            "transcribe_accelerator": "gpu",
            "transcribe_gpu_device": null
        });
        let mut settings: AppSettings = serde_json::from_value(raw.clone()).unwrap();

        assert!(apply_settings_migrations(&mut settings, &raw));
        assert_eq!(
            settings.transcribe_accelerator,
            TranscribeAcceleratorSetting::Auto
        );
        assert_eq!(settings.transcribe_gpu_device, None);
    }

    #[test]
    fn gpu_device_migration_keeps_current_stable_selection() {
        let mut settings = get_default_settings();
        settings.transcribe_accelerator = TranscribeAcceleratorSetting::Gpu;
        settings.transcribe_gpu_device = Some("[\"vulkan\",\"id\",\"0000:01:00.0\"]".into());

        let raw = serde_json::json!({
            "settings_schema_version": CURRENT_SETTINGS_SCHEMA_VERSION,
            "onboarding_completed": false,
            "chinese_script": "as_transcribed",
            "transcribe_accelerator": "gpu",
            "transcribe_gpu_device": settings.transcribe_gpu_device
        });

        assert!(!apply_settings_migrations(&mut settings, &raw));
        assert_eq!(
            settings.transcribe_gpu_device.as_deref(),
            Some("[\"vulkan\",\"id\",\"0000:01:00.0\"]")
        );
    }

    #[test]
    fn stale_dictation_keys_are_ignored_on_load() {
        let raw = serde_json::json!({
            "selected_model": "kept",
            "post_process_enabled": true,
            "post_process_providers": [{ "id": 42 }],
            "post_process_api_keys": { "openai": "sk-secret" },
            "history_limit": "sixty",
            "recording_retention_period": "never",
            "vad_enabled": false,
            "voice_commands_enabled": false,
        });

        let settings: AppSettings =
            serde_json::from_value(raw).expect("keys of removed settings must not fail the parse");
        assert_eq!(settings.selected_model, "kept");
        let rewritten = settings_store_value(&settings);
        assert!(!rewritten.to_string().contains("sk-secret"));
    }

    // --- ключи удалённой постобработки в хранилище ОС ---

    use crate::secrets::testing::{store_with, MemoryBackend};
    use std::sync::Arc;

    const KEY_NAME: &str = "post_process_api_key.openai";

    #[test]
    fn purge_removes_legacy_api_keys_from_keyring() {
        let backend = Arc::new(MemoryBackend::default());
        {
            let mut items = backend.items.lock().unwrap();
            items.insert(KEY_NAME.into(), "sk-secret".into());
            items.insert("post_process_api_key.custom".into(), "sk-custom".into());
            // Not a post-processing key: must stay.
            items.insert("device_token".into(), "token".into());
        }
        let secrets = store_with(&backend);

        assert!(purge_post_process_api_keys(
            &secrets,
            &serde_json::json!({ "post_process_api_keys": { "my_provider": "" } })
        ));
        assert_eq!(backend.stored(KEY_NAME), None);
        assert_eq!(backend.stored("post_process_api_key.custom"), None);
        assert_eq!(backend.stored("device_token").as_deref(), Some("token"));
    }

    #[test]
    fn purge_reports_an_unreachable_keyring_so_it_is_retried() {
        let backend = MemoryBackend::failing();
        backend
            .items
            .lock()
            .unwrap()
            .insert(KEY_NAME.into(), "sk-secret".into());
        let secrets = store_with(&backend);

        assert!(!purge_post_process_api_keys(
            &secrets,
            &serde_json::json!({})
        ));
        assert_eq!(backend.stored(KEY_NAME).as_deref(), Some("sk-secret"));
    }

    #[test]
    fn schema_bump_marks_the_store_updated() {
        let mut settings = get_default_settings();
        let raw = serde_json::json!({
            "settings_schema_version": 2,
            "onboarding_completed": true,
            "chinese_script": "as_transcribed",
        });
        settings.settings_schema_version = 2;

        assert!(apply_settings_migrations(&mut settings, &raw));
        assert_eq!(
            settings.settings_schema_version,
            CURRENT_SETTINGS_SCHEMA_VERSION
        );
    }
}
