//! Audio sources of a meeting. Every channel ends in a [`ChannelPipe`]: the
//! 16 kHz mono audio goes to disk first, then to the channel's phrase cutter.
//!
//! - microphone, and system sound on Linux (a PulseAudio "Monitor of ...")
//!   come from `handy-recorder`;
//! - system sound on Windows is a WASAPI loopback: `handy-cpal` turns an input
//!   stream built on a playback (render) device into a loopback capture, which
//!   `handy-recorder` can't open because it lists capture devices only.

use std::sync::atomic::{AtomicU32, Ordering};
use std::sync::mpsc::{self, RecvTimeoutError, Sender};
use std::sync::{Arc, Mutex};
use std::thread::JoinHandle;
use std::time::{Duration, Instant};

use cpal::traits::{DeviceTrait, HostTrait, StreamTrait};
use cpal::FromSample;
use handy_recorder::{AudioChunk, Channels, ErrorKind, Recorder, RecorderConfig, Sink, StartError};
use log::{debug, error, info, warn};
use serde::Serialize;
use specta::Type;

use super::storage::{PcmWriter, SAMPLE_RATE};
use crate::audio_toolkit::StreamResampler;

/// Frames per chunk handed to the pipe: one Silero frame.
const CHUNK_FRAMES: usize = 512;
/// Loopback delivers nothing while nothing plays; silence is added every tick.
const LOOPBACK_TICK: Duration = Duration::from_millis(250);
/// Audio may lag the wall clock this much before silence is added for it.
const LOOPBACK_TOLERANCE_SECS: f64 = 0.5;

/// A capture device offered to the UI.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Type)]
pub struct CaptureDevice {
    pub id: String,
    pub name: String,
    pub is_default: bool,
}

/// What a channel's capture thread hands to its phrase cutter.
pub enum ChanMsg {
    /// First audio: meeting time (seconds) of its first sample.
    Start {
        offset_secs: f64,
    },
    Samples(Vec<f32>),
}

/// State of one channel that the manager and the UI read.
#[derive(Default)]
pub struct ChannelShared {
    /// Peak level since the last read, as `f32` bits.
    level_bits: AtomicU32,
    error: Mutex<Option<String>>,
}

impl ChannelShared {
    pub fn report_error(&self, message: String) {
        error!("Meeting channel failed: {message}");
        let mut slot = self.error.lock().unwrap_or_else(|e| e.into_inner());
        if slot.is_none() {
            *slot = Some(message);
        }
    }

    /// The first error not yet taken.
    pub fn take_error(&self) -> Option<String> {
        self.error.lock().unwrap_or_else(|e| e.into_inner()).take()
    }

    fn note_level(&self, level: f32) {
        // Only this channel's capture thread writes, so a plain max is safe.
        if level > f32::from_bits(self.level_bits.load(Ordering::Relaxed)) {
            self.level_bits.store(level.to_bits(), Ordering::Relaxed);
        }
    }

    /// Peak level 0..1 since the previous call.
    pub fn take_level(&self) -> f32 {
        f32::from_bits(self.level_bits.swap(0, Ordering::Relaxed))
    }
}

/// Level 0..1 of a block: RMS on a -60..0 dBFS scale.
pub fn level_of(samples: &[f32]) -> f32 {
    if samples.is_empty() {
        return 0.0;
    }
    let rms = (samples.iter().map(|s| s * s).sum::<f32>() / samples.len() as f32).sqrt();
    if rms <= 0.0 {
        return 0.0;
    }
    ((20.0 * rms.log10() + 60.0) / 60.0).clamp(0.0, 1.0)
}

fn to_i16(sample: f32) -> i16 {
    (sample.clamp(-1.0, 1.0) * f32::from(i16::MAX)).round() as i16
}

/// The tail of every capture: disk first, so a crash loses seconds at most,
/// then the phrase cutter.
pub struct ChannelPipe {
    writer: PcmWriter,
    tx: Sender<ChanMsg>,
    shared: Arc<ChannelShared>,
    /// Meeting time (seconds) at which the capture of this session began.
    session_start: Instant,
    base_seconds: f64,
    started: bool,
}

impl ChannelPipe {
    pub fn new(
        writer: PcmWriter,
        tx: Sender<ChanMsg>,
        shared: Arc<ChannelShared>,
        session_start: Instant,
        base_seconds: f64,
    ) -> Self {
        Self {
            writer,
            tx,
            shared,
            session_start,
            base_seconds,
            started: false,
        }
    }

    pub fn push(&mut self, samples: &[f32]) {
        if samples.is_empty() {
            return;
        }
        if !self.started {
            self.started = true;
            // The stream may take a while to deliver (Bluetooth), so the
            // channel's own clock starts when its first audio arrives.
            let lag = samples.len() as f64 / f64::from(SAMPLE_RATE);
            let offset_secs =
                self.base_seconds + (self.session_start.elapsed().as_secs_f64() - lag).max(0.0);
            let _ = self.tx.send(ChanMsg::Start { offset_secs });
        }
        self.shared.note_level(level_of(samples));

        let pcm: Vec<i16> = samples.iter().copied().map(to_i16).collect();
        if let Err(e) = self
            .writer
            .write(&pcm)
            .and_then(|()| self.writer.flush_if_due())
        {
            self.shared.report_error(format!("disk write failed: {e}"));
        }
        let _ = self.tx.send(ChanMsg::Samples(samples.to_vec()));
    }

    /// Writes out what is buffered and closes the file. Dropping the pipe also
    /// closes the channel to the phrase cutter.
    pub fn finish(self) {
        if let Err(e) = self.writer.finish() {
            error!("Closing meeting audio file failed: {e}");
        }
    }
}

/// Zero samples to add so the channel keeps up with the wall clock: loopback
/// sends no packets while nothing plays. `incoming` samples are about to be
/// pushed and are the newest audio.
fn silence_to_add(pushed: u64, elapsed_secs: f64, incoming: usize, tolerance_secs: f64) -> usize {
    let expected =
        ((elapsed_secs - tolerance_secs) * f64::from(SAMPLE_RATE)) as i64 - incoming as i64;
    (expected - pushed as i64).max(0) as usize
}

/* ---------------- handy-recorder: microphone, Linux monitor ---------------- */

struct RecorderSink(ChannelPipe);

impl Sink for RecorderSink {
    fn process_chunk(&mut self, chunk: AudioChunk<'_>) {
        self.0.push(&chunk.samples[..chunk.valid_frames]);
    }
}

pub struct RecorderCapture {
    recorder: Recorder<RecorderSink>,
}

fn recorder_config(device: Option<String>, channel: Option<u16>) -> RecorderConfig {
    RecorderConfig {
        device,
        channels: channel.map_or(Channels::MixToMono, Channels::Only),
        frames_per_chunk: Some(CHUNK_FRAMES),
        ..RecorderConfig::speech()
    }
}

fn open_recorder(
    device: Option<String>,
    channel: Option<u16>,
    shared: &Arc<ChannelShared>,
) -> Result<Recorder<RecorderSink>, handy_recorder::Error> {
    let open = |channel: Option<u16>| {
        let shared = Arc::clone(shared);
        Recorder::open_with_failure_handler(recorder_config(device.clone(), channel), move |e| {
            shared.report_error(format!("audio device failed: {e}"));
        })
    };
    match open(channel) {
        // The device lacks the chosen channel (another microphone): average all.
        Err(e) if e.kind() == ErrorKind::InvalidChannel => {
            warn!("{e}; averaging all input channels instead");
            open(None)
        }
        result => result,
    }
}

impl RecorderCapture {
    pub fn start(
        device: Option<String>,
        channel: Option<u16>,
        pipe: ChannelPipe,
    ) -> Result<Self, String> {
        let shared = Arc::clone(&pipe.shared);
        let recorder = open_recorder(device, channel, &shared).map_err(|e| e.to_string())?;
        match recorder.start(RecorderSink(pipe)) {
            Ok(()) => Ok(Self { recorder }),
            Err(StartError { error, .. }) => Err(error.to_string()),
        }
    }

    /// Stops the capture and returns the pipe, to be finished by the caller.
    pub fn stop(self) -> Option<ChannelPipe> {
        let pipe = match self.recorder.stop() {
            Ok(stopped) => {
                if !stopped.is_complete() {
                    warn!(
                        "Meeting capture ended with {:?}, {} frames dropped",
                        stopped.end_reason, stopped.dropped_frames
                    );
                }
                Some(stopped.sink.0)
            }
            Err(e) => {
                error!("Stopping meeting capture failed: {e}");
                None
            }
        };
        if let Err(e) = self.recorder.close() {
            warn!("Closing meeting capture failed: {e}");
        }
        pipe
    }
}

/// Linux: input devices that are not PulseAudio monitors; elsewhere all inputs.
pub fn list_microphones() -> Vec<CaptureDevice> {
    match handy_recorder::list_input_devices() {
        Ok(devices) => devices
            .into_iter()
            .filter(|d| !d.is_monitor)
            .map(|d| CaptureDevice {
                id: d.id,
                name: d.name,
                is_default: d.is_default,
            })
            .collect(),
        Err(e) => {
            warn!("Listing input devices failed: {e}");
            Vec::new()
        }
    }
}

/// Input devices that carry what the computer plays: PulseAudio monitors.
#[cfg(not(any(windows, target_os = "macos")))]
pub fn list_monitor_sources() -> Vec<CaptureDevice> {
    match handy_recorder::list_input_devices() {
        Ok(devices) => devices
            .into_iter()
            .filter(|d| d.is_monitor)
            .map(|d| CaptureDevice {
                id: d.id,
                name: d.name,
                is_default: d.is_default,
            })
            .collect(),
        Err(e) => {
            warn!("Listing monitor sources failed: {e}");
            Vec::new()
        }
    }
}

/* ---------------- handy-cpal: WASAPI loopback of a render device ---------------- */

struct LoopbackState {
    pipe: ChannelPipe,
    resampler: StreamResampler,
    started: Instant,
    pushed: u64,
}

impl LoopbackState {
    /// Adds the silence the wall clock calls for before `incoming` new samples.
    fn pad(&mut self, incoming: usize, tolerance_secs: f64) {
        let mut missing = silence_to_add(
            self.pushed,
            self.started.elapsed().as_secs_f64(),
            incoming,
            tolerance_secs,
        );
        while missing > 0 {
            let part = missing.min(SAMPLE_RATE as usize);
            self.pipe.push(&vec![0.0; part]);
            self.pushed += part as u64;
            missing -= part;
        }
    }

    fn feed(&mut self, mono_native: &[f32], scratch: &mut Vec<f32>) {
        scratch.clear();
        self.resampler.push(mono_native, scratch);
        // The resampler holds back a few samples, so count what it produced
        // plus what it will produce: small enough for the tolerance.
        self.pad(scratch.len(), LOOPBACK_TOLERANCE_SECS);
        self.pipe.push(scratch);
        self.pushed += scratch.len() as u64;
    }
}

/// Interleaved device samples of any format, averaged to mono f32.
fn mix_to_mono<T>(samples: &[T], channels: usize, out: &mut Vec<f32>)
where
    T: cpal::SizedSample + Copy,
    f32: FromSample<T>,
{
    out.clear();
    out.extend(
        samples.chunks_exact(channels).map(|frame| {
            frame.iter().map(|&s| f32::from_sample_(s)).sum::<f32>() / channels as f32
        }),
    );
}

fn data_to_mono(data: &cpal::Data, channels: usize, out: &mut Vec<f32>) -> bool {
    use cpal::SampleFormat as F;
    match data.sample_format() {
        F::F32 => data
            .as_slice::<f32>()
            .map(|s| mix_to_mono(s, channels, out)),
        F::F64 => data
            .as_slice::<f64>()
            .map(|s| mix_to_mono(s, channels, out)),
        F::I16 => data
            .as_slice::<i16>()
            .map(|s| mix_to_mono(s, channels, out)),
        F::I32 => data
            .as_slice::<i32>()
            .map(|s| mix_to_mono(s, channels, out)),
        F::U16 => data
            .as_slice::<u16>()
            .map(|s| mix_to_mono(s, channels, out)),
        F::I8 => data.as_slice::<i8>().map(|s| mix_to_mono(s, channels, out)),
        _ => None,
    }
    .is_some()
}

#[cfg_attr(not(windows), allow(dead_code))]
pub struct LoopbackCapture {
    stop_tx: Sender<()>,
    join: Option<JoinHandle<()>>,
    state: Arc<Mutex<Option<LoopbackState>>>,
}

fn find_render_device(id: Option<&str>) -> Result<cpal::Device, String> {
    let host = cpal::default_host();
    match id {
        Some(id) => host
            .output_devices()
            .map_err(|e| e.to_string())?
            .find(|d| d.id().is_ok_and(|device_id| device_id.to_string() == id))
            .ok_or_else(|| format!("no playback device with ID {id:?}")),
        None => host
            .default_output_device()
            .ok_or_else(|| "no default playback device".to_string()),
    }
}

/// Playback devices, the sources of system sound on Windows.
#[cfg_attr(not(windows), allow(dead_code))]
pub fn list_render_devices() -> Vec<CaptureDevice> {
    let host = cpal::default_host();
    let default_id = host.default_output_device().and_then(|d| d.id().ok());
    let Ok(devices) = host.output_devices() else {
        return Vec::new();
    };
    devices
        .filter_map(|device| {
            let id = device.id().ok()?;
            let name = device
                .description()
                .map(|d| d.name().to_owned())
                .unwrap_or_else(|_| id.to_string());
            Some(CaptureDevice {
                is_default: default_id.as_ref() == Some(&id),
                id: id.to_string(),
                name,
            })
        })
        .collect()
}

#[cfg_attr(not(windows), allow(dead_code))]
impl LoopbackCapture {
    /// Opens the stream on its own thread (some hosts' streams are not
    /// `Send`) and waits until it plays or fails. On failure the pipe is gone.
    pub fn start(device_id: Option<String>, pipe: ChannelPipe) -> Result<Self, String> {
        let shared = Arc::clone(&pipe.shared);
        let device = find_render_device(device_id.as_deref())?;
        let config = device.default_output_config().map_err(|e| e.to_string())?;
        let resampler =
            StreamResampler::new(config.sample_rate(), SAMPLE_RATE).map_err(|e| e.to_string())?;
        info!(
            "System sound loopback: {} Hz, {} ch, {:?}",
            config.sample_rate(),
            config.channels(),
            config.sample_format()
        );
        let state = Arc::new(Mutex::new(Some(LoopbackState {
            pipe,
            resampler,
            started: Instant::now(),
            pushed: 0,
        })));
        let (stop_tx, stop_rx) = mpsc::channel::<()>();
        let (ready_tx, ready_rx) = mpsc::channel::<Result<(), String>>();

        let thread_state = Arc::clone(&state);
        let join = std::thread::Builder::new()
            .name("meeting-loopback".into())
            .spawn(move || {
                let channels = usize::from(config.channels().max(1));
                let callback_state = Arc::clone(&thread_state);
                let mut mono = Vec::new();
                let mut scratch = Vec::new();
                let stream = device.build_input_stream_raw(
                    config.config(),
                    config.sample_format(),
                    move |data, _| {
                        if !data_to_mono(data, channels, &mut mono) {
                            return;
                        }
                        let mut guard = callback_state.lock().unwrap_or_else(|e| e.into_inner());
                        if let Some(state) = guard.as_mut() {
                            state.feed(&mono, &mut scratch);
                        }
                    },
                    move |e| shared.report_error(format!("system sound capture failed: {e}")),
                    None,
                );
                let stream = match stream.and_then(|stream| stream.play().map(|()| stream)) {
                    Ok(stream) => stream,
                    Err(e) => {
                        let _ = ready_tx.send(Err(e.to_string()));
                        return;
                    }
                };
                let _ = ready_tx.send(Ok(()));
                // Ends on a stop request, or when the capture handle is gone.
                while let Err(RecvTimeoutError::Timeout) = stop_rx.recv_timeout(LOOPBACK_TICK) {
                    let mut guard = thread_state.lock().unwrap_or_else(|e| e.into_inner());
                    if let Some(state) = guard.as_mut() {
                        state.pad(0, LOOPBACK_TOLERANCE_SECS);
                    }
                }
                drop(stream);
            })
            .map_err(|e| format!("cannot start capture thread: {e}"))?;

        match ready_rx.recv_timeout(Duration::from_secs(10)) {
            Ok(Ok(())) => Ok(Self {
                stop_tx,
                join: Some(join),
                state,
            }),
            outcome => {
                let _ = stop_tx.send(());
                let _ = join.join();
                Err(match outcome {
                    Ok(Err(e)) => e,
                    _ => "system sound capture did not start in time".to_string(),
                })
            }
        }
    }

    pub fn stop(mut self) -> Option<ChannelPipe> {
        let _ = self.stop_tx.send(());
        if let Some(join) = self.join.take() {
            if join.join().is_err() {
                error!("System sound capture thread panicked");
            }
        }
        debug!("System sound loopback stopped");
        self.state
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .take()
            .map(|s| s.pipe)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn level_scale_is_logarithmic_and_clamped() {
        assert_eq!(level_of(&[]), 0.0);
        assert_eq!(level_of(&[0.0; 100]), 0.0);
        assert!((level_of(&[1.0; 100]) - 1.0).abs() < 1e-6);
        // -30 dBFS is the middle of the scale.
        let half = 10f32.powf(-30.0 / 20.0);
        assert!((level_of(&[half; 100]) - 0.5).abs() < 1e-3);
        assert_eq!(level_of(&[1e-6; 100]), 0.0);
    }

    #[test]
    fn samples_convert_to_i16_with_clamping() {
        assert_eq!(to_i16(0.0), 0);
        assert_eq!(to_i16(1.0), i16::MAX);
        assert_eq!(to_i16(2.5), i16::MAX);
        assert_eq!(to_i16(-3.0), -i16::MAX);
        assert_eq!(to_i16(0.5), 16384);
    }

    #[test]
    fn silence_fills_only_what_the_clock_demands() {
        // Audio keeps up: nothing to add.
        assert_eq!(silence_to_add(16_000 * 10, 10.2, 0, 0.5), 0);
        // Two idle seconds beyond the tolerance.
        assert_eq!(silence_to_add(16_000 * 10, 12.5, 0, 0.5), 32_000);
        // New audio is the newest part of the timeline, so less is padded.
        assert_eq!(silence_to_add(16_000 * 10, 12.5, 8_000, 0.5), 24_000);
        // Never negative.
        assert_eq!(silence_to_add(16_000 * 10, 1.0, 0, 0.5), 0);
    }

    #[test]
    fn mixes_interleaved_samples_to_mono() {
        let mut out = Vec::new();
        mix_to_mono(&[1.0f32, 0.0, 0.5, 0.5], 2, &mut out);
        assert_eq!(out, vec![0.5, 0.5]);
        mix_to_mono(&[i16::MAX, i16::MAX], 2, &mut out);
        assert!((out[0] - 1.0).abs() < 1e-3);
    }

    #[test]
    fn pipe_writes_disk_and_reports_start_and_samples() {
        let dir = tempfile::tempdir().unwrap();
        let (tx, rx) = mpsc::channel();
        let shared = Arc::new(ChannelShared::default());
        let writer = PcmWriter::new(dir.path(), "mic", 16_000).unwrap();
        let mut pipe = ChannelPipe::new(writer, tx, Arc::clone(&shared), Instant::now(), 100.0);
        pipe.push(&[0.5; 512]);
        pipe.finish();

        match rx.recv().unwrap() {
            ChanMsg::Start { offset_secs } => assert!(offset_secs >= 100.0 && offset_secs < 101.0),
            ChanMsg::Samples(_) => panic!("start comes first"),
        }
        assert!(matches!(rx.recv().unwrap(), ChanMsg::Samples(s) if s.len() == 512));
        assert!(rx.recv().is_err(), "channel closes with the pipe");
        assert!(shared.take_level() > 0.85);
        assert_eq!(shared.take_level(), 0.0);
        assert_eq!(
            super::super::storage::channel_duration_seconds(dir.path(), "mic"),
            512.0 / 16_000.0
        );
    }
}
