//! One running meeting: the channels, their threads and the setup/teardown.

use std::sync::atomic::{AtomicU32, Ordering};
use std::sync::mpsc::{self, Receiver, Sender};
use std::sync::{Arc, Mutex};
use std::thread::JoinHandle;
use std::time::{Duration, Instant};

use log::warn;
use tokio::sync::watch;

use super::capture::{self, ChannelShared};
use super::channel::{channel_title, ChannelFactory, ChannelRuntime, Devices};
use super::live_mix::LiveTap;
use super::live_stream::{LiveContext, LiveStream};
use super::live_types::LiveStatus;
use super::recognizer::PhraseQueue;
use super::storage;
use super::supervisor::{Supervisor, SupervisorCtx};
use super::timeline::Timeline;
use super::{
    io_err, meeting_duration, now_iso, system_audio_supported, CaptureDevices, CaptureMode,
    MeetingInfo, MeetingLevels, MeetingManager, MeetingStateKind, MeetingStatus,
    StartMeetingRequest, CHANNEL_MIC, CHANNEL_SYSTEM,
};
use crate::managers::model::ModelManager;
use crate::managers::transcription::TranscriptionManager;
use crate::settings::{get_settings, RecognitionMode};
use tauri::Manager;

/* ------------------------------ session ------------------------------ */

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
    /// Shared with the supervisor, which reopens a channel that failed.
    pub(super) channels: Arc<Mutex<Vec<ChannelRuntime>>>,
    /// What the channels have recorded: the meeting's time.
    pub(super) timeline: Arc<Timeline>,
    pub(super) supervisor: Option<Supervisor>,
    /// Bumped to make the live connection anew (the computer woke up).
    pub(super) live_reset: Arc<watch::Sender<u64>>,
    pub(super) queue: Arc<PhraseQueue>,
    pub(super) levels: Arc<LastLevels>,
    pub(super) recognizer_done: Receiver<()>,
    pub(super) ticker_stop: Sender<()>,
    pub(super) ticker: JoinHandle<()>,
    /// The copy of the audio for the server; `None`: local recognition.
    pub(super) tap: Option<Arc<LiveTap>>,
    /// The live link to the server, running once the meeting is stored.
    pub(super) live: Option<LiveStream>,
}

impl Session {
    pub(super) fn live_status(&self) -> LiveStatus {
        self.live
            .as_ref()
            .map(LiveStream::status)
            .unwrap_or_default()
    }
}

/// The channels of a session whose supervisor has stopped.
fn take_channels(channels: &Mutex<Vec<ChannelRuntime>>) -> Vec<ChannelRuntime> {
    std::mem::take(&mut *channels.lock().unwrap_or_else(|e| e.into_inner()))
}

pub(super) enum Slot {
    Idle,
    /// A meeting is being set up or torn down.
    Busy,
    Active(Box<Session>),
}

impl MeetingManager {
    /* -------------------------- devices -------------------------- */

    pub fn list_capture_devices(&self) -> CaptureDevices {
        let inputs = capture::list_microphones();
        #[cfg(any(windows, target_os = "macos"))]
        let system_sources = if system_audio_supported() {
            super::loopback::list_render_devices()
        } else {
            Vec::new()
        };
        #[cfg(not(any(windows, target_os = "macos")))]
        let system_sources = capture::list_monitor_sources();
        CaptureDevices {
            inputs,
            system_sources,
            system_supported: system_audio_supported(),
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

    /// Whether this meeting is recognized on this computer (the setting).
    pub(super) fn recognizes_locally(&self) -> bool {
        get_settings(&self.app).recognition_mode == RecognitionMode::Local
    }

    /// The model must be loaded before a locally recognized meeting starts:
    /// phrases are recognized as they come, and a meeting without recognition
    /// would only pile up a queue. Online (the server recognizes) needs no model.
    pub(super) fn require_model(&self) -> Result<(), String> {
        if !self.recognizes_locally() {
            return Ok(());
        }
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
        if wants_system && !system_audio_supported() {
            return Err(if cfg!(target_os = "macos") {
                "Звук компьютера на Mac работает с macOS 14.6: обновите систему или выберите режим «очная встреча»"
            } else {
                "Звук системы на этой ОС не поддерживается: выберите режим «очная встреча»"
            }
            .to_string());
        }
        let audio_dir = storage::audio_dir(&self.root, &meeting.id);
        let started = Instant::now();
        let queue = Arc::new(PhraseQueue::default());
        let local = self.recognizes_locally();
        let tap = (!local).then(|| Arc::new(LiveTap::new(wants_system)));
        // A resumed meeting carries on from the audio it has.
        let timeline = Arc::new(Timeline::new(
            storage::channel_samples(&audio_dir, CHANNEL_MIC),
            storage::channel_samples(&audio_dir, CHANNEL_SYSTEM),
        ));
        let factory = Arc::new(ChannelFactory {
            app: self.app.clone(),
            audio_dir,
            wants_system,
            started,
            base_seconds,
            queue: Arc::clone(&queue),
            backend: get_settings(&self.app).vad_backend,
            tap: tap.clone(),
            timeline: Arc::clone(&timeline),
        });

        let mut specs = vec![CHANNEL_MIC];
        if wants_system {
            specs.push(CHANNEL_SYSTEM);
        }
        let mut channels: Vec<ChannelRuntime> = Vec::new();
        for audio_name in specs {
            let shared = Arc::new(ChannelShared::default());
            match factory.open(audio_name, devices, shared) {
                Ok(channel) => channels.push(channel),
                Err(message) => {
                    Self::close_channels(channels);
                    return Err(format!("{}: {message}", channel_title(audio_name)));
                }
            }
        }

        let (recognizer_done_tx, recognizer_done) = mpsc::channel();
        if local {
            self.spawn_recognizer(&meeting.id, &queue, recognizer_done_tx);
        } else {
            // Nothing to wait for at the stop: the server recognizes.
            let _ = recognizer_done_tx.send(());
        }
        let levels = Arc::new(LastLevels::default());
        let (ticker_stop, ticker_rx) = mpsc::channel();
        let ticker = self.spawn_ticker(&meeting.id, &channels, &queue, &levels, ticker_rx);
        let channels = Arc::new(Mutex::new(channels));
        let (live_reset, _) = watch::channel(0u64);
        let live_reset = Arc::new(live_reset);
        let supervisor = Supervisor::start(SupervisorCtx {
            factory,
            channels: Arc::clone(&channels),
            devices: devices.clone(),
            db: Arc::clone(&self.db),
            meeting_id: meeting.id.clone(),
            timeline: Arc::clone(&timeline),
            live_reset: Arc::clone(&live_reset),
        });
        Ok(Session {
            meeting_id: meeting.id.clone(),
            channels,
            timeline,
            supervisor,
            live_reset,
            queue,
            levels,
            recognizer_done,
            ticker_stop,
            ticker,
            tap,
            live: None,
        })
    }

    /// Opens the live link to the server for a session of the online
    /// recognition. Called once the meeting is in the database (the link
    /// makes it on the server). The capture does not wait for the link.
    pub(super) fn start_live(&self, session: &mut Session, meeting: &MeetingInfo) {
        let Some(tap) = session.tap.clone() else {
            return;
        };
        session.live = LiveStream::start(LiveContext {
            app: self.app.clone(),
            db: Arc::clone(&self.db),
            meeting: meeting.clone(),
            timeline: Arc::clone(&session.timeline),
            tap,
            reset: session.live_reset.subscribe(),
        });
    }

    /// `drain`: how long the recognizer may take to finish the queue.
    pub(super) fn finish_session(
        &self,
        mut session: Session,
        drain: Duration,
    ) -> Result<MeetingInfo, String> {
        let id = session.meeting_id.clone();
        self.emit_state(
            MeetingStateKind::Stopping,
            &id,
            session.queue.len(),
            None,
            None,
        );

        // No reopening of a channel from here on; then the channels close.
        if let Some(supervisor) = session.supervisor.take() {
            supervisor.stop();
        }
        Self::close_channels(take_channels(&session.channels));
        // The last audio is in the tap now: it goes to the server, and the
        // phrases still on their way are taken before the meeting counts as stopped.
        if let Some(live) = session.live.take() {
            live.stop();
        }
        session.queue.close();
        if session.recognizer_done.recv_timeout(drain).is_err() {
            warn!("Recognition did not finish within {drain:?}; dropping the rest of the queue");
            session.queue.abort();
        }
        let _ = session.ticker_stop.send(());
        let _ = session.ticker.join();

        // The queue is drained: every phrase is in the database. The voices are
        // settled before the meeting counts as stopped and goes to the server.
        self.recluster_voices(&id);

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
        for channel in channels {
            channel.close();
        }
    }

    /// A session that never became active (the database refused the meeting).
    pub(super) fn discard_session(&self, mut session: Session) {
        if let Some(supervisor) = session.supervisor.take() {
            supervisor.stop();
        }
        Self::close_channels(take_channels(&session.channels));
        if let Some(live) = session.live.take() {
            live.stop();
        }
        session.queue.abort();
        let _ = session.ticker_stop.send(());
        let _ = session.ticker.join();
    }
}
