//! One running meeting: the channels, their threads and the setup/teardown.

use std::path::Path;
use std::sync::atomic::{AtomicU32, Ordering};
use std::sync::mpsc::{self, Receiver, Sender};
use std::sync::Arc;
use std::thread::JoinHandle;
use std::time::Instant;

use log::{error, warn};

use super::capture::{self, ChannelPipe, ChannelShared, LoopbackCapture, RecorderCapture};
use super::recognizer::PhraseQueue;
use super::storage::{self, PCM_PIECE_SECONDS, SAMPLE_RATE};
use super::workers::cut_phrases;
use super::{
    io_err, meeting_duration, now_iso, CaptureDevices, CaptureMode, MeetingInfo, MeetingLevels,
    MeetingManager, MeetingStateKind, MeetingStatus, StartMeetingRequest, CHANNEL_MIC,
    CHANNEL_MIXED, CHANNEL_SYSTEM, DRAIN_TIMEOUT, SYSTEM_AUDIO_SUPPORTED,
};
use crate::managers::audio::create_detector;
use crate::managers::model::ModelManager;
use crate::managers::transcription::TranscriptionManager;
use crate::settings::get_settings;
use tauri::Manager;

/* ------------------------------ session ------------------------------ */

#[cfg_attr(not(windows), allow(dead_code))]
pub(super) enum CaptureHandle {
    Recorder(Box<RecorderCapture>),
    Loopback(LoopbackCapture),
}

impl CaptureHandle {
    fn stop(self) -> Option<ChannelPipe> {
        match self {
            Self::Recorder(capture) => capture.stop(),
            Self::Loopback(capture) => capture.stop(),
        }
    }
}

pub(super) struct ChannelRuntime {
    pub(super) audio_name: &'static str,
    pub(super) shared: Arc<ChannelShared>,
    pub(super) capture: CaptureHandle,
    pub(super) cutter: JoinHandle<()>,
}

/// Last levels the ticker read, for `get_active_meeting`.
#[derive(Default)]
pub(super) struct LastLevels {
    mic: AtomicU32,
    system: AtomicU32,
}

impl LastLevels {
    pub(super) fn store(&self, levels: MeetingLevels) {
        self.mic.store(levels.mic.to_bits(), Ordering::Relaxed);
        self.system
            .store(levels.system.to_bits(), Ordering::Relaxed);
    }

    pub(super) fn load(&self) -> MeetingLevels {
        MeetingLevels {
            mic: f32::from_bits(self.mic.load(Ordering::Relaxed)),
            system: f32::from_bits(self.system.load(Ordering::Relaxed)),
        }
    }
}

pub(super) struct Session {
    pub(super) meeting_id: String,
    /// Seconds already recorded before this session (a resumed meeting).
    pub(super) base_seconds: f64,
    pub(super) started: Instant,
    pub(super) channels: Vec<ChannelRuntime>,
    pub(super) queue: Arc<PhraseQueue>,
    pub(super) levels: Arc<LastLevels>,
    pub(super) recognizer_done: Receiver<()>,
    pub(super) ticker_stop: Sender<()>,
    pub(super) ticker: JoinHandle<()>,
}

pub(super) enum Slot {
    Idle,
    /// A meeting is being set up or torn down.
    Busy,
    Active(Box<Session>),
}

/// Devices a session captures from.
pub(super) struct Devices {
    pub(super) mic: Option<String>,
    pub(super) mic_channel: Option<u16>,
    pub(super) system: Option<String>,
}

impl MeetingManager {
    /* -------------------------- devices -------------------------- */

    pub fn list_capture_devices(&self) -> CaptureDevices {
        let inputs = capture::list_microphones();
        #[cfg(windows)]
        let system_sources = capture::list_render_devices();
        #[cfg(target_os = "macos")]
        let system_sources = Vec::new();
        #[cfg(not(any(windows, target_os = "macos")))]
        let system_sources = capture::list_monitor_sources();
        CaptureDevices {
            inputs,
            system_sources,
            system_supported: SYSTEM_AUDIO_SUPPORTED,
        }
    }

    /// The microphone chosen in settings, as a device ID and channel.
    pub(super) fn settings_microphone(&self) -> (Option<String>, Option<u16>) {
        let settings = get_settings(&self.app);
        let Some(name) = settings.selected_microphone else {
            return (None, None);
        };
        let id = handy_recorder::list_input_devices()
            .ok()
            .and_then(|devices| devices.into_iter().find(|d| d.name == name))
            .map(|d| d.id);
        match id {
            Some(id) => (Some(id), settings.selected_channel),
            // Gone: the system default is better than not recording.
            None => (None, None),
        }
    }

    /// The computer-sound device chosen in settings, if it is still there.
    fn settings_system_device(&self) -> Option<String> {
        let saved = get_settings(&self.app).meeting_system_device?;
        // Gone: the default is better than not recording.
        self.list_capture_devices()
            .system_sources
            .iter()
            .any(|d| d.id == saved)
            .then_some(saved)
    }

    pub(super) fn devices_for(&self, request: Option<&StartMeetingRequest>) -> Devices {
        let system = request
            .and_then(|r| r.system_device_id.clone())
            .or_else(|| self.settings_system_device());
        match request.and_then(|r| r.mic_device_id.clone()) {
            Some(id) => Devices {
                mic: Some(id),
                mic_channel: None,
                system,
            },
            None => {
                let (mic, mic_channel) = self.settings_microphone();
                Devices {
                    mic,
                    mic_channel,
                    system,
                }
            }
        }
    }

    /// The model must be loaded before recording starts: phrases are
    /// recognized as they come, and a meeting without recognition would only
    /// pile up a queue.
    pub(super) fn require_model(&self) -> Result<(), String> {
        let tm = self.app.state::<Arc<TranscriptionManager>>();
        if tm.is_model_loaded() {
            return Ok(());
        }
        let model_id = get_settings(&self.app).selected_model;
        self.app
            .state::<Arc<ModelManager>>()
            .get_model_path(&model_id)
            .map_err(|e| format!("Модель распознавания не готова: {e}"))?;
        tm.load_model(&model_id)
            .map_err(|e| format!("Не удалось загрузить модель распознавания: {e}"))
    }

    /// Opens the channels and starts all threads. Nothing is left running on error.
    pub(super) fn launch(
        &self,
        meeting: &MeetingInfo,
        base_seconds: f64,
        devices: &Devices,
    ) -> Result<Session, String> {
        let wants_system = meeting.capture_mode == CaptureMode::Online;
        if wants_system && !SYSTEM_AUDIO_SUPPORTED {
            return Err(
                "Звук системы на этой ОС не поддерживается: выберите режим «очная встреча»"
                    .to_string(),
            );
        }
        let audio_dir = storage::audio_dir(&self.root, &meeting.id);
        let started = Instant::now();
        let queue = Arc::new(PhraseQueue::default());
        let backend = get_settings(&self.app).vad_backend;

        let mut specs = vec![CHANNEL_MIC];
        if wants_system {
            specs.push(CHANNEL_SYSTEM);
        }
        let mut channels: Vec<ChannelRuntime> = Vec::new();
        for audio_name in specs {
            let label = if wants_system {
                audio_name
            } else {
                CHANNEL_MIXED
            };
            match self.open_channel(
                &audio_dir,
                audio_name,
                label,
                started,
                base_seconds,
                devices,
                &queue,
                backend,
            ) {
                Ok(channel) => channels.push(channel),
                Err(message) => {
                    Self::close_channels(channels);
                    return Err(format!("{}: {message}", Self::channel_title(audio_name)));
                }
            }
        }

        let (recognizer_done_tx, recognizer_done) = mpsc::channel();
        self.spawn_recognizer(&meeting.id, &queue, recognizer_done_tx);
        let levels = Arc::new(LastLevels::default());
        let (ticker_stop, ticker_rx) = mpsc::channel();
        let ticker = self.spawn_ticker(&meeting.id, &channels, &queue, &levels, ticker_rx);
        Ok(Session {
            meeting_id: meeting.id.clone(),
            base_seconds,
            started,
            channels,
            queue,
            levels,
            recognizer_done,
            ticker_stop,
            ticker,
        })
    }

    fn channel_title(audio_name: &str) -> &'static str {
        if audio_name == CHANNEL_SYSTEM {
            "Звук системы"
        } else {
            "Микрофон"
        }
    }
    #[allow(clippy::too_many_arguments)]
    fn open_channel(
        &self,
        audio_dir: &Path,
        audio_name: &'static str,
        label: &str,
        started: Instant,
        base_seconds: f64,
        devices: &Devices,
        queue: &Arc<PhraseQueue>,
        backend: crate::settings::VadBackend,
    ) -> Result<ChannelRuntime, String> {
        let scorer = create_detector(backend, &self.app).map_err(|e| format!("{e:#}"))?;
        let writer = storage::PcmWriter::new(
            audio_dir,
            audio_name,
            PCM_PIECE_SECONDS * SAMPLE_RATE as usize,
        )
        .map_err(|e| format!("{e:#}"))?;
        let (tx, rx) = mpsc::channel();
        let shared = Arc::new(ChannelShared::default());
        let pipe = ChannelPipe::new(writer, tx, Arc::clone(&shared), started, base_seconds);

        let cutter = {
            let queue = Arc::clone(queue);
            let label = label.to_string();
            std::thread::Builder::new()
                .name(format!("meeting-cut-{audio_name}"))
                .spawn(move || cut_phrases(rx, scorer, &queue, &label))
                .map_err(io_err)?
        };

        let capture = if audio_name == CHANNEL_SYSTEM {
            Self::open_system(devices, pipe)
        } else {
            RecorderCapture::start(devices.mic.clone(), devices.mic_channel, pipe)
                .map(|c| CaptureHandle::Recorder(Box::new(c)))
        };
        match capture {
            Ok(capture) => Ok(ChannelRuntime {
                audio_name,
                shared,
                capture,
                cutter,
            }),
            Err(message) => {
                // The pipe went down with the failed start, which ends the cutter.
                let _ = cutter.join();
                Err(message)
            }
        }
    }

    #[cfg(windows)]
    fn open_system(devices: &Devices, pipe: ChannelPipe) -> Result<CaptureHandle, String> {
        LoopbackCapture::start(devices.system.clone(), pipe).map(CaptureHandle::Loopback)
    }

    #[cfg(not(windows))]
    fn open_system(devices: &Devices, pipe: ChannelPipe) -> Result<CaptureHandle, String> {
        #[cfg(not(target_os = "macos"))]
        {
            let source = match devices.system.clone() {
                Some(id) => id,
                None => capture::list_monitor_sources()
                    .into_iter()
                    .next()
                    .map(|d| d.id)
                    .ok_or_else(|| {
                        "не найден источник звука системы (Monitor of ...)".to_string()
                    })?,
            };
            RecorderCapture::start(Some(source), None, pipe)
                .map(|c| CaptureHandle::Recorder(Box::new(c)))
        }
        #[cfg(target_os = "macos")]
        {
            let _ = (devices, pipe);
            Err("не поддерживается".to_string())
        }
    }
    pub(super) fn finish_session(&self, session: Session) -> Result<MeetingInfo, String> {
        let id = session.meeting_id.clone();
        self.emit_state(
            MeetingStateKind::Stopping,
            &id,
            session.queue.len(),
            None,
            None,
        );

        Self::close_channels(session.channels);
        session.queue.close();
        if session.recognizer_done.recv_timeout(DRAIN_TIMEOUT).is_err() {
            warn!("Recognition did not finish within {DRAIN_TIMEOUT:?}; dropping the rest of the queue");
            session.queue.abort();
        }
        let _ = session.ticker_stop.send(());
        let _ = session.ticker.join();

        let duration = meeting_duration(&self.root, &id).max(0.0);
        self.db
            .finish_meeting(&id, MeetingStatus::Stopped, &now_iso(), duration)
            .map_err(io_err)?;
        self.emit_state(MeetingStateKind::Stopped, &id, 0, None, None);
        self.db
            .get_meeting(&id)
            .map_err(io_err)?
            .ok_or_else(|| "Встреча не найдена".to_string())
    }

    /// Stops the captures, closes the audio files, and waits for the cutters
    /// to hand their last phrases to the queue.
    pub(super) fn close_channels(channels: Vec<ChannelRuntime>) {
        let mut cutters = Vec::new();
        for channel in channels {
            if let Some(pipe) = channel.capture.stop() {
                // Closing the pipe closes the channel to its cutter.
                pipe.finish();
            }
            cutters.push(channel.cutter);
        }
        for cutter in cutters {
            if cutter.join().is_err() {
                error!("A meeting phrase cutter panicked");
            }
        }
    }

    /// A session that never became active (the database refused the meeting).
    pub(super) fn discard_session(&self, session: Session) {
        Self::close_channels(session.channels);
        session.queue.abort();
        let _ = session.ticker_stop.send(());
        let _ = session.ticker.join();
    }
}
