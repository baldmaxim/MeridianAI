//! Recording session: start/stop a recording from the UI and turn it into text.
//!
//! The frontend drives the whole lifecycle through the `start_recording` /
//! `stop_recording` commands (see `commands::recording`); there is no global
//! hotkey and nothing is pasted into other applications. `stop_recording`
//! returns the recognized text.

use crate::audio_toolkit::VadPolicy;
use crate::managers::audio::{recording_error_type, AudioRecordingManager};
use crate::managers::history::HistoryManager;
use crate::managers::model::ModelManager;
use crate::managers::transcription::policy::{live_decode, LiveDecode, ModelTraits};
use crate::managers::transcription::TranscriptionManager;
use crate::settings::{get_settings, AppSettings};
use crate::tray::{set_tray_state, TrayIconState};
use log::{debug, error, warn};
use std::future::Future;
use std::sync::{Arc, Mutex, MutexGuard};
use std::time::{Duration, Instant};
use tauri::Manager;
use tauri::{AppHandle, Emitter};

const CANCELLATION_POLL_INTERVAL: Duration = Duration::from_millis(25);

/// Binding id the audio manager keys the active recording by.
const RECORDING_BINDING_ID: &str = "transcribe";

#[derive(Clone, serde::Serialize)]
struct RecordingErrorEvent {
    error_type: String,
    detail: Option<String>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Stage {
    Idle,
    Recording,
    Processing,
}

/// Tauri managed state: where the recording pipeline currently is, so that
/// `start_recording` / `stop_recording` can't overlap or run out of order.
pub struct RecordingSession(Mutex<Stage>);

impl RecordingSession {
    pub fn new() -> Self {
        Self(Mutex::new(Stage::Idle))
    }

    fn lock(&self) -> MutexGuard<'_, Stage> {
        self.0.lock().unwrap_or_else(|poisoned| {
            warn!("Recording session mutex was poisoned, recovering");
            poisoned.into_inner()
        })
    }

    /// Move `from` -> `to`; returns the current stage when it isn't `from`.
    fn transition(&self, from: Stage, to: Stage) -> Result<(), Stage> {
        let mut stage = self.lock();
        if *stage == from {
            *stage = to;
            Ok(())
        } else {
            Err(*stage)
        }
    }

    fn set(&self, stage: Stage) {
        *self.lock() = stage;
    }

    /// A cancelled recording returns to idle at once. During processing the
    /// pipeline itself returns to idle when it unwinds.
    pub fn notify_cancel(&self) {
        let mut stage = self.lock();
        if *stage == Stage::Recording {
            *stage = Stage::Idle;
        }
    }
}

impl Default for RecordingSession {
    fn default() -> Self {
        Self::new()
    }
}

/// Drop guard that finishes the pipeline: back to idle, including immediate
/// model unloading on early exits.
struct FinishGuard(AppHandle, Arc<TranscriptionManager>);
impl Drop for FinishGuard {
    fn drop(&mut self) {
        self.1.maybe_unload_immediately("transcription session");
        if let Some(session) = self.0.try_state::<RecordingSession>() {
            session.set(Stage::Idle);
        }
        set_tray_state(&self.0, TrayIconState::Idle);
        // The pipeline just freed its large transient buffers (captured PCM,
        // WAV copy, engine scratch); hand the cached pages back to the OS so
        // they don't sit in malloc arenas until they get swapped out (#1792).
        crate::memory::trim_freed_memory();
    }
}

/// Field name for structured output JSON schema
const TRANSCRIPTION_FIELD: &str = "transcription";

/// Strip invisible Unicode characters that some LLMs may insert
fn strip_invisible_chars(s: &str) -> String {
    s.replace(['\u{200B}', '\u{200C}', '\u{200D}', '\u{FEFF}'], "")
}

/// Strip a leading `<think>...</think>` block. Some endpoints can't disable
/// reasoning, and some local servers put the reasoning text into `content`
/// instead of a separate field — without this the user would get the model's
/// chain of thought pasted along with the cleaned transcription.
fn strip_think_block(s: &str) -> &str {
    if let Some(rest) = s.trim_start().strip_prefix("<think>") {
        if let Some(end) = rest.find("</think>") {
            return rest[end + "</think>".len()..].trim_start();
        }
    }
    s
}

/// Build a system prompt from the user's prompt template.
/// Removes `${output}` placeholder since the transcription is sent as the user message.
fn build_system_prompt(prompt_template: &str) -> String {
    prompt_template.replace("${output}", "").trim().to_string()
}

/// Returns `true` when a transcription has no meaningful content to
/// post-process (empty or whitespace-only). Used to skip the post-processing
/// LLM call when nothing was actually transcribed, which would otherwise make
/// the model reply with an error message such as "you need to provide the
/// transcription".
fn is_blank_transcription(transcription: &str) -> bool {
    transcription.trim().is_empty()
}

async fn complete_unless_cancelled<F, C>(operation: F, is_cancelled: C) -> Option<F::Output>
where
    F: Future,
    C: Fn() -> bool,
{
    tokio::pin!(operation);

    loop {
        if is_cancelled() {
            return None;
        }

        if let Ok(result) =
            tokio::time::timeout(CANCELLATION_POLL_INTERVAL, operation.as_mut()).await
        {
            return Some(result);
        }
    }
}

async fn post_process_transcription(settings: &AppSettings, transcription: &str) -> Option<String> {
    if is_blank_transcription(transcription) {
        debug!("Post-processing skipped because the transcription is empty");
        return None;
    }

    let provider = match settings.active_post_process_provider().cloned() {
        Some(provider) => provider,
        None => {
            debug!("Post-processing enabled but no provider is selected");
            return None;
        }
    };

    let model = settings
        .post_process_models
        .get(&provider.id)
        .cloned()
        .unwrap_or_default();

    if model.trim().is_empty() {
        debug!(
            "Post-processing skipped because provider '{}' has no model configured",
            provider.id
        );
        return None;
    }

    let selected_prompt_id = match &settings.post_process_selected_prompt_id {
        Some(id) => id.clone(),
        None => {
            debug!("Post-processing skipped because no prompt is selected");
            return None;
        }
    };

    let prompt = match settings
        .post_process_prompts
        .iter()
        .find(|prompt| prompt.id == selected_prompt_id)
    {
        Some(prompt) => prompt.prompt.clone(),
        None => {
            debug!(
                "Post-processing skipped because prompt '{}' was not found",
                selected_prompt_id
            );
            return None;
        }
    };

    if prompt.trim().is_empty() {
        debug!("Post-processing skipped because the selected prompt is empty");
        return None;
    }

    debug!(
        "Starting LLM post-processing with provider '{}' (model: {})",
        provider.id, model
    );

    let api_key = settings
        .post_process_api_keys
        .get(&provider.id)
        .cloned()
        .unwrap_or_default();

    // Ask these providers to skip reasoning/thinking — post-processing rarely
    // benefits from it and it adds seconds of latency. llm_client picks the
    // field the endpoint understands and retries without it if rejected.
    let disable_reasoning = matches!(provider.id.as_str(), "custom" | "openrouter");

    if provider.supports_structured_output {
        debug!("Using structured outputs for provider '{}'", provider.id);

        let system_prompt = build_system_prompt(&prompt);
        let user_content = transcription.to_string();

        // Define JSON schema for transcription output
        let json_schema = serde_json::json!({
            "type": "object",
            "properties": {
                (TRANSCRIPTION_FIELD): {
                    "type": "string",
                    "description": "The cleaned and processed transcription text"
                }
            },
            "required": [TRANSCRIPTION_FIELD],
            "additionalProperties": false
        });

        match crate::llm_client::send_chat_completion_with_schema(
            &provider,
            api_key.clone(),
            &model,
            user_content,
            Some(system_prompt),
            Some(json_schema),
            disable_reasoning,
        )
        .await
        {
            Ok(Some(content)) => {
                // Parse the JSON response to extract the transcription field
                let content = strip_think_block(&content);
                match serde_json::from_str::<serde_json::Value>(content) {
                    Ok(json) => {
                        if let Some(transcription_value) =
                            json.get(TRANSCRIPTION_FIELD).and_then(|t| t.as_str())
                        {
                            let result = strip_invisible_chars(transcription_value);
                            debug!(
                                "Structured output post-processing succeeded for provider '{}'. Output length: {} chars",
                                provider.id,
                                result.len()
                            );
                            return Some(result);
                        } else {
                            error!("Structured output response missing 'transcription' field");
                            return Some(strip_invisible_chars(content));
                        }
                    }
                    Err(e) => {
                        error!(
                            "Failed to parse structured output JSON: {}. Returning raw content.",
                            e
                        );
                        return Some(strip_invisible_chars(content));
                    }
                }
            }
            Ok(None) => {
                error!("LLM API response has no content");
                return None;
            }
            Err(e) => {
                warn!(
                    "Structured output failed for provider '{}': {}. Falling back to legacy mode.",
                    provider.id, e
                );
                // Fall through to legacy mode below
            }
        }
    }

    // Legacy mode: Replace ${output} variable in the prompt with the actual text
    let processed_prompt = prompt.replace("${output}", transcription);
    debug!("Processed prompt length: {} chars", processed_prompt.len());

    match crate::llm_client::send_chat_completion(
        &provider,
        api_key,
        &model,
        processed_prompt,
        disable_reasoning,
    )
    .await
    {
        Ok(Some(content)) => {
            let content = strip_invisible_chars(strip_think_block(&content));
            debug!(
                "LLM post-processing succeeded for provider '{}'. Output length: {} chars",
                provider.id,
                content.len()
            );
            Some(content)
        }
        Ok(None) => {
            error!("LLM API response has no content");
            None
        }
        Err(e) => {
            error!(
                "LLM post-processing failed for provider '{}': {}. Falling back to original transcription.",
                provider.id,
                e
            );
            None
        }
    }
}

pub(crate) struct ProcessedTranscription {
    pub final_text: String,
    pub post_processed_text: Option<String>,
    pub post_process_prompt: Option<String>,
}

pub(crate) async fn process_transcription_output(
    app: &AppHandle,
    transcription: &str,
    post_process: bool,
) -> ProcessedTranscription {
    let settings = get_settings(app);
    let mut final_text = transcription.to_string();
    let mut post_processed_text: Option<String> = None;
    let mut post_process_prompt: Option<String> = None;

    if post_process {
        if let Some(processed_text) = post_process_transcription(&settings, &final_text).await {
            post_processed_text = Some(processed_text.clone());
            final_text = processed_text;

            if let Some(prompt_id) = &settings.post_process_selected_prompt_id {
                if let Some(prompt) = settings
                    .post_process_prompts
                    .iter()
                    .find(|prompt| &prompt.id == prompt_id)
                {
                    post_process_prompt = Some(prompt.prompt.clone());
                }
            }
        }
    }

    ProcessedTranscription {
        final_text,
        post_processed_text,
        post_process_prompt,
    }
}

/// Start recording from the microphone.
pub fn start(app: &AppHandle) -> Result<(), String> {
    let start_time = Instant::now();
    let session = app.state::<RecordingSession>();
    session
        .transition(Stage::Idle, Stage::Recording)
        .map_err(|stage| match stage {
            Stage::Recording => "Recording is already in progress".to_string(),
            _ => "The previous recording is still being processed".to_string(),
        })?;

    let result = start_inner(app);
    if result.is_err() {
        session.set(Stage::Idle);
    }
    debug!("start_recording finished in {:?}", start_time.elapsed());
    result
}

fn start_inner(app: &AppHandle) -> Result<(), String> {
    // Load model in the background
    let tm = app.state::<Arc<TranscriptionManager>>();
    let rm = app.state::<Arc<AudioRecordingManager>>();

    // Load ASR model and VAD model in parallel
    tm.initiate_model_load();
    let rm_clone = Arc::clone(&rm);
    std::thread::spawn(move || {
        if let Err(e) = rm_clone.preload_vad() {
            debug!("VAD pre-load failed: {}", e);
        }
    });

    let settings = get_settings(app);

    // Don't open the mic if nothing can transcribe the recording; the load
    // kicked off above fails and reports why.
    if !tm.is_model_loaded() {
        if let Err(e) = app
            .state::<Arc<ModelManager>>()
            .get_model_path(&settings.selected_model)
        {
            warn!("Not starting recording: no model can transcribe it ({})", e);
            return Err(format!("No model can transcribe the recording: {e}"));
        }
    }

    set_tray_state(app, TrayIconState::Recording);

    let selected_model_info = app
        .state::<Arc<ModelManager>>()
        .get_model_info(&settings.selected_model);

    // Use the app-facing model capability as the single pre-recording source
    // for live streaming decisions. Unknown support is represented as false
    // until the model registry is updated by discovery or runtime load.
    let model_supports_streaming = selected_model_info
        .as_ref()
        .map(|m| m.supports_streaming)
        .unwrap_or(false);
    let vad_policy = if !settings.vad_enabled {
        VadPolicy::Disabled
    } else if model_supports_streaming {
        VadPolicy::Streaming
    } else {
        VadPolicy::Offline
    };
    // Before the model loads, whether it keeps its accuracy on long audio
    // is unknown, so assume not: the worker decides again with the loaded
    // model, and a wrong guess costs only an idle worker.
    let expected_model = ModelTraits {
        streaming: model_supports_streaming,
        long_form: false,
    };
    if live_decode(expected_model, settings.long_form_chunking) != LiveDecode::None {
        tm.start_stream();
    }

    match rm.try_start_recording(RECORDING_BINDING_ID, vad_policy) {
        Ok(readiness) => {
            let generation = readiness.generation();
            let rm_clone = Arc::clone(&rm);
            std::thread::spawn(move || {
                if !readiness.wait() {
                    debug!("Microphone readiness wait ended without receiving samples");
                    return;
                }
                if rm_clone.is_recording_readiness_current(generation) {
                    debug!("Microphone is receiving samples; recording is ready");
                    rm_clone.apply_mute();
                }
            });
            Ok(())
        }
        Err(e) => {
            // Starting failed (for example due to blocked microphone permissions).
            debug!("Failed to start recording: {}", e);
            tm.cancel_stream();
            set_tray_state(app, TrayIconState::Idle);
            let _ = app.emit(
                "recording-error",
                RecordingErrorEvent {
                    error_type: recording_error_type(&e).to_string(),
                    detail: Some(format!("{e:#}")),
                },
            );
            Err(format!("{e:#}"))
        }
    }
}

/// Stop the active recording, recognize it and return the text.
pub async fn stop(app: &AppHandle) -> Result<String, String> {
    let stop_time = Instant::now();
    app.state::<RecordingSession>()
        .transition(Stage::Recording, Stage::Processing)
        .map_err(|_| "No recording is in progress".to_string())?;
    // From here on the pipeline owns the Processing stage and returns to idle
    // however it ends.
    let _guard = FinishGuard(
        app.clone(),
        Arc::clone(&app.state::<Arc<TranscriptionManager>>()),
    );

    let rm = Arc::clone(&app.state::<Arc<AudioRecordingManager>>());
    let tm = Arc::clone(&app.state::<Arc<TranscriptionManager>>());
    let hm = Arc::clone(&app.state::<Arc<HistoryManager>>());

    // Prevent a slow microphone from signalling readiness after stop.
    rm.invalidate_recording_readiness();
    set_tray_state(app, TrayIconState::Transcribing);
    rm.remove_mute();

    let cancel_generation = rm.cancel_generation();
    let rm_for_stop = Arc::clone(&rm);
    let samples = tauri::async_runtime::spawn_blocking(move || {
        rm_for_stop.stop_recording(RECORDING_BINDING_ID, cancel_generation)
    })
    .await
    .map_err(|e| format!("Recording stop task failed: {e}"))?;

    let Some(samples) = samples else {
        debug!("No samples retrieved from recording stop");
        // Tear down any streaming worker so its channel doesn't leak.
        tm.cancel_stream();
        return Err("Recording was cancelled".to_string());
    };

    if rm.was_cancelled_since(cancel_generation) {
        debug!("Transcription operation cancelled after recording stop");
        tm.cancel_stream();
        return Err("Recording was cancelled".to_string());
    }

    if samples.is_empty() {
        debug!("Recording produced no audio samples; skipping persistence");
        tm.cancel_stream();
        return Ok(String::new());
    }

    // Save WAV concurrently with transcription
    let sample_count = samples.len();
    let file_name = format!("meridian-{}.wav", chrono::Utc::now().timestamp());
    let wav_path = hm.recordings_dir().join(&file_name);
    let wav_path_for_verify = wav_path.clone();
    let samples_for_wav = samples.clone();
    let wav_handle = tauri::async_runtime::spawn_blocking(move || {
        crate::audio_toolkit::save_wav_file(&wav_path, &samples_for_wav)
    });

    // Transcribe concurrently with WAV save: the live decode's result when it
    // has one (all audio was already fed to it), otherwise a batch run of the
    // samples. A cancel is surfaced as an error, so it never starts a batch run.
    let transcription_time = Instant::now();
    let tm_for_run = Arc::clone(&tm);
    let transcription_result =
        tauri::async_runtime::spawn_blocking(move || tm_for_run.transcribe_recording(samples))
            .await
            .map_err(|e| format!("Transcription task failed: {e}"))?;

    // Await WAV save and verify
    let wav_saved = match wav_handle.await {
        Ok(Ok(())) => {
            match crate::audio_toolkit::verify_wav_file(&wav_path_for_verify, sample_count) {
                Ok(()) => true,
                Err(e) => {
                    error!("WAV verification failed: {}", e);
                    false
                }
            }
        }
        Ok(Err(e)) => {
            error!("Failed to save WAV file: {}", e);
            false
        }
        Err(e) => {
            error!("WAV save task panicked: {}", e);
            false
        }
    };

    if rm.was_cancelled_since(cancel_generation) {
        debug!("Transcription operation cancelled before output handling");
        return Err("Recording was cancelled".to_string());
    }

    let post_process = get_settings(app).post_process_enabled;

    match transcription_result {
        Ok(transcription) => {
            debug!(
                "Transcription completed in {:?}: '{}'",
                transcription_time.elapsed(),
                crate::utils::redact_text(&transcription)
            );

            let Some(processed) = complete_unless_cancelled(
                process_transcription_output(app, &transcription, post_process),
                || rm.was_cancelled_since(cancel_generation),
            )
            .await
            else {
                debug!("Transcription operation cancelled during output handling");
                return Err("Recording was cancelled".to_string());
            };

            // Save to history if WAV was saved
            if wav_saved {
                if let Err(err) = hm.save_entry(
                    file_name,
                    transcription,
                    post_process,
                    processed.post_processed_text.clone(),
                    processed.post_process_prompt.clone(),
                ) {
                    error!("Failed to save history entry: {}", err);
                }
            }

            debug!("stop_recording finished in {:?}", stop_time.elapsed());
            Ok(processed.final_text)
        }
        Err(err) => {
            if rm.was_cancelled_since(cancel_generation) {
                debug!("Transcription operation cancelled after transcription error");
                return Err("Recording was cancelled".to_string());
            }

            error!("Transcription failed: {}", err);
            // Surface the failure to the UI (toast). The full message is also
            // in the log file via the line above.
            let _ = app.emit("transcription-error", err.to_string());
            // Save entry with empty text so user can retry
            if wav_saved {
                if let Err(save_err) =
                    hm.save_entry(file_name, String::new(), post_process, None, None)
                {
                    error!("Failed to save failed history entry: {}", save_err);
                }
            }
            Err(err.to_string())
        }
    }
}

#[cfg(test)]
mod tests {
    use super::{complete_unless_cancelled, is_blank_transcription, strip_think_block};
    use std::future;
    use std::sync::atomic::{AtomicBool, Ordering};
    use std::sync::Arc;
    use std::thread;
    use std::time::Duration;

    #[test]
    fn blank_transcription_is_detected() {
        assert!(is_blank_transcription(""));
        assert!(is_blank_transcription("   "));
        assert!(is_blank_transcription("\t\n  \r\n"));
    }

    #[test]
    fn non_blank_transcription_is_kept() {
        assert!(!is_blank_transcription("hello"));
        assert!(!is_blank_transcription("  hello  "));
    }

    #[test]
    fn completed_operation_returns_its_output() {
        let result = tauri::async_runtime::block_on(complete_unless_cancelled(
            future::ready("done"),
            || false,
        ));

        assert_eq!(result, Some("done"));
    }

    #[test]
    fn pending_operation_stops_after_cancellation() {
        let cancelled = Arc::new(AtomicBool::new(false));
        let cancelled_for_thread = Arc::clone(&cancelled);
        let cancel_thread = thread::spawn(move || {
            thread::sleep(Duration::from_millis(10));
            cancelled_for_thread.store(true, Ordering::Release);
        });

        let result = tauri::async_runtime::block_on(complete_unless_cancelled(
            future::pending::<()>(),
            || cancelled.load(Ordering::Acquire),
        ));

        cancel_thread.join().unwrap();
        assert_eq!(result, None);
    }

    #[test]
    fn leading_think_block_is_stripped() {
        assert_eq!(
            strip_think_block("<think>pondering...</think>Cleaned text."),
            "Cleaned text."
        );
        assert_eq!(
            strip_think_block("  \n<think>multi\nline</think>\n  Cleaned text."),
            "Cleaned text."
        );
    }

    #[test]
    fn content_without_think_block_is_unchanged() {
        assert_eq!(strip_think_block("Cleaned text."), "Cleaned text.");
        assert_eq!(
            strip_think_block("Mentions <think> mid-sentence."),
            "Mentions <think> mid-sentence."
        );
        // Unclosed block: leave untouched rather than guess
        assert_eq!(
            strip_think_block("<think>never closed"),
            "<think>never closed"
        );
    }
}
