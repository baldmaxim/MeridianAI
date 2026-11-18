//! One audio channel of a running meeting: opening it, closing it, and
//! opening it again after a failure (see `supervisor.rs`).

use std::path::PathBuf;
use std::sync::mpsc;
use std::sync::Arc;
use std::thread::JoinHandle;
use std::time::Instant;

use log::error;
use tauri::AppHandle;

use super::capture::{ChannelPipe, ChannelShared, RecorderCapture};
use super::live_mix::{LiveTap, Source};
use super::loopback::LoopbackCapture;
use super::recognizer::PhraseQueue;
use super::storage::{self, PCM_PIECE_SECONDS, SAMPLE_RATE};
use super::timeline::Timeline;
use super::workers::cut_phrases;
use super::{io_err, CHANNEL_MIXED, CHANNEL_SYSTEM};
use crate::audio_toolkit::vad::create_detector;
use crate::settings::VadBackend;

#[cfg_attr(not(any(windows, target_os = "macos")), allow(dead_code))]
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
    /// `None`: no local recognition (the server recognizes).
    pub(super) cutter: Option<JoinHandle<()>>,
}

impl ChannelRuntime {
    /// Stops the capture, closes the audio file (its tail goes to the disk)
    /// and waits for the phrase cutter to hand over its last phrase.
    pub(super) fn close(self) {
        if let Some(pipe) = self.capture.stop() {
            // Closing the pipe closes the channel to its cutter.
            pipe.finish();
        }
        if let Some(cutter) = self.cutter {
            if cutter.join().is_err() {
                error!("A meeting phrase cutter panicked");
            }
        }
    }
}

/// Devices a session captures from.
#[derive(Clone)]
pub(super) struct Devices {
    pub(super) mic: Option<String>,
    pub(super) mic_channel: Option<u16>,
    pub(super) system: Option<String>,
}

impl Devices {
    /// The system's choice for everything: what is left when a device is gone.
    pub(super) fn defaults() -> Self {
        Self {
            mic: None,
            mic_channel: None,
            system: None,
        }
    }
}

/// The source of a channel by its file name.
pub(super) fn source_of(audio_name: &str) -> Source {
    if audio_name == CHANNEL_SYSTEM {
        Source::System
    } else {
        Source::Mic
    }
}

pub(super) fn channel_title(audio_name: &str) -> &'static str {
    if audio_name == CHANNEL_SYSTEM {
        "Звук системы"
    } else {
        "Микрофон"
    }
}

/// What opening a channel needs, kept for the whole session: the supervisor
/// opens the channels again with it.
pub(super) struct ChannelFactory {
    pub(super) app: AppHandle,
    pub(super) audio_dir: PathBuf,
    /// An online meeting: two channels.
    pub(super) wants_system: bool,
    pub(super) started: Instant,
    pub(super) base_seconds: f64,
    pub(super) queue: Arc<PhraseQueue>,
    pub(super) backend: VadBackend,
    /// `None`: local recognition.
    pub(super) tap: Option<Arc<LiveTap>>,
    pub(super) timeline: Arc<Timeline>,
}

impl ChannelFactory {
    /// Opens the capture of `audio_name`. The channel starts level with the
    /// other: what it is behind (it opened later, it is shorter in a resumed
    /// meeting, it was away after a failure) is filled with silence first, so
    /// the files and the times of the phrases agree. Nothing is left running
    /// on error.
    pub(super) fn open(
        &self,
        audio_name: &'static str,
        devices: &Devices,
        shared: Arc<ChannelShared>,
    ) -> Result<ChannelRuntime, String> {
        let writer = storage::PcmWriter::new(
            &self.audio_dir,
            audio_name,
            PCM_PIECE_SECONDS * SAMPLE_RATE as usize,
        )
        .map_err(|e| format!("{e:#}"))?;
        let source = source_of(audio_name);
        let (pipe, cutter) = match &self.tap {
            // The server recognizes: the audio goes to disk and to the tap only.
            Some(_) => (
                ChannelPipe::disk_only(
                    writer,
                    Arc::clone(&shared),
                    self.started,
                    self.base_seconds,
                ),
                None,
            ),
            None => {
                let label = if self.wants_system {
                    audio_name
                } else {
                    CHANNEL_MIXED
                }
                .to_string();
                let scorer =
                    create_detector(self.backend, &self.app).map_err(|e| format!("{e:#}"))?;
                let (tx, rx) = mpsc::channel();
                let pipe = ChannelPipe::new(
                    writer,
                    tx,
                    Arc::clone(&shared),
                    self.started,
                    self.base_seconds,
                );
                let queue = Arc::clone(&self.queue);
                let cutter = std::thread::Builder::new()
                    .name(format!("meeting-cut-{audio_name}"))
                    .spawn(move || cut_phrases(rx, scorer, &queue, &label))
                    .map_err(io_err)?;
                (pipe, Some(cutter))
            }
        };
        let mut pipe = pipe.with_timeline(Arc::clone(&self.timeline), source);
        if let Some(tap) = &self.tap {
            pipe = pipe.with_tap(Arc::clone(tap), source);
        }
        pipe.pad_silence(self.timeline.lag(source));

        let capture = if audio_name == CHANNEL_SYSTEM {
            open_system(devices, pipe)
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
                if let Some(cutter) = cutter {
                    let _ = cutter.join();
                }
                Err(message)
            }
        }
    }
}

/// Windows (WASAPI) and macOS (Core Audio tap): an input stream on a playback device.
#[cfg(any(windows, target_os = "macos"))]
fn open_system(devices: &Devices, pipe: ChannelPipe) -> Result<CaptureHandle, String> {
    LoopbackCapture::start(devices.system.clone(), pipe).map(CaptureHandle::Loopback)
}

#[cfg(not(any(windows, target_os = "macos")))]
fn open_system(devices: &Devices, pipe: ChannelPipe) -> Result<CaptureHandle, String> {
    let source = match devices.system.clone() {
        Some(id) => id,
        None => super::capture::list_monitor_sources()
            .into_iter()
            .next()
            .map(|d| d.id)
            .ok_or_else(|| "не найден источник звука системы (Monitor of ...)".to_string())?,
    };
    RecorderCapture::start(Some(source), None, pipe).map(|c| CaptureHandle::Recorder(Box::new(c)))
}

/// The id of the device the system uses by default for `audio_name`, to notice
/// that it changed (headphones unplugged). `None`: not told on this OS.
pub(super) fn default_device_id(audio_name: &str) -> Option<String> {
    if audio_name == CHANNEL_SYSTEM {
        return default_render_id();
    }
    handy_recorder::list_input_devices()
        .ok()?
        .into_iter()
        .find(|d| d.is_default && !d.is_monitor)
        .map(|d| d.id)
}

#[cfg(any(windows, target_os = "macos"))]
fn default_render_id() -> Option<String> {
    use cpal::traits::{DeviceTrait, HostTrait};
    cpal::default_host()
        .default_output_device()?
        .id()
        .ok()
        .map(|id| id.to_string())
}

/// Linux: the monitor is bound to a playback device, which the Recorder
/// reports when it breaks.
#[cfg(not(any(windows, target_os = "macos")))]
fn default_render_id() -> Option<String> {
    None
}
