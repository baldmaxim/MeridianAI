//! Audio sources of a meeting. Every channel ends in a [`ChannelPipe`]: the
//! 16 kHz mono audio goes to disk first, then to the channel's phrase cutter.
//!
//! - microphone, and system sound on Linux (a PulseAudio "Monitor of ...")
//!   come from `handy-recorder`;
//! - system sound on Windows (WASAPI) and macOS 14.6+ (Core Audio tap) is a
//!   loopback, see `loopback.rs`.

use std::sync::atomic::{AtomicBool, AtomicU32, AtomicU64, Ordering};
use std::sync::mpsc::Sender;
use std::sync::{Arc, Mutex};
use std::time::Instant;

use handy_recorder::{AudioChunk, Channels, ErrorKind, Recorder, RecorderConfig, Sink, StartError};
use log::{error, warn};
use serde::Serialize;
use specta::Type;

use super::live_mix::{LiveTap, Source};
use super::storage::{PcmWriter, SAMPLE_RATE};
use super::timeline::Timeline;

/// Frames per chunk handed to the pipe: one Silero frame.
const CHUNK_FRAMES: usize = 512;

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
    /// Which capture of the channel is current: a restart starts a new one,
    /// and the failure reports of the old one are ignored.
    generation: AtomicU64,
    /// The current capture failed (the device went away, the stream broke):
    /// the supervisor reopens it.
    failed: AtomicBool,
    failure: Mutex<Option<String>>,
}

impl ChannelShared {
    pub fn report_error(&self, message: String) {
        error!("Meeting channel failed: {message}");
        let mut slot = self.error.lock().unwrap_or_else(|e| e.into_inner());
        if slot.is_none() {
            *slot = Some(message);
        }
    }

    /// A new capture of the channel begins: returns its number, and clears
    /// the failure of the one before.
    pub(super) fn next_generation(&self) -> u64 {
        self.failed.store(false, Ordering::SeqCst);
        self.generation.fetch_add(1, Ordering::SeqCst) + 1
    }

    pub(super) fn generation(&self) -> u64 {
        self.generation.load(Ordering::SeqCst)
    }

    /// The capture numbered `generation` failed. Not shown to the user: the
    /// supervisor tries to reopen it first (and shows the error if it cannot).
    pub(super) fn report_failure(&self, generation: u64, message: String) {
        if generation != self.generation() {
            return;
        }
        warn!("Meeting capture failed, it will be reopened: {message}");
        *self.failure.lock().unwrap_or_else(|e| e.into_inner()) = Some(message);
        self.failed.store(true, Ordering::SeqCst);
    }

    /// The failure of the current capture, once (`None`: it runs).
    pub(super) fn take_failure(&self) -> Option<String> {
        if !self.failed.swap(false, Ordering::SeqCst) {
            return None;
        }
        Some(
            self.failure
                .lock()
                .unwrap_or_else(|e| e.into_inner())
                .take()
                .unwrap_or_else(|| "audio device failed".to_string()),
        )
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
    /// `None`: no local recognition (the server recognizes), only the disk.
    tx: Option<Sender<ChanMsg>>,
    /// The copy of the audio for the live stream to the server.
    tap: Option<(Arc<LiveTap>, Source)>,
    /// What the channel has recorded, for the meeting's time.
    timeline: Option<(Arc<Timeline>, Source)>,
    pub(super) shared: Arc<ChannelShared>,
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
            tx: Some(tx),
            tap: None,
            timeline: None,
            shared,
            session_start,
            base_seconds,
            started: false,
        }
    }

    /// A pipe without a phrase cutter: the audio goes to disk (and the tap).
    pub fn disk_only(
        writer: PcmWriter,
        shared: Arc<ChannelShared>,
        session_start: Instant,
        base_seconds: f64,
    ) -> Self {
        Self {
            writer,
            tx: None,
            tap: None,
            timeline: None,
            shared,
            session_start,
            base_seconds,
            started: false,
        }
    }

    /// Also copies the audio to the live stream's tap.
    pub(super) fn with_tap(mut self, tap: Arc<LiveTap>, source: Source) -> Self {
        self.tap = Some((tap, source));
        self
    }

    /// Also counts what the channel records into the meeting's timeline.
    pub(super) fn with_timeline(mut self, timeline: Arc<Timeline>, source: Source) -> Self {
        self.timeline = Some((timeline, source));
        self
    }

    /// Records `samples` of silence: a channel that came back after a failure
    /// (or a shorter one of a resumed meeting) is brought level with the other.
    pub(super) fn pad_silence(&mut self, mut samples: usize) {
        const PART: usize = SAMPLE_RATE as usize;
        while samples > 0 {
            let part = samples.min(PART);
            self.push(&vec![0.0; part]);
            samples -= part;
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
            // With the timeline it is the place in the channel's own audio:
            // right across a sleep and a reopened channel. Without it (a
            // test) the session's clock stands in.
            let offset_secs = match &self.timeline {
                Some((timeline, source)) => {
                    timeline.samples(*source) as f64 / f64::from(SAMPLE_RATE)
                }
                None => {
                    let lag = samples.len() as f64 / f64::from(SAMPLE_RATE);
                    self.base_seconds + (self.session_start.elapsed().as_secs_f64() - lag).max(0.0)
                }
            };
            if let Some(tx) = &self.tx {
                let _ = tx.send(ChanMsg::Start { offset_secs });
            }
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
        if let Some((timeline, source)) = &self.timeline {
            timeline.add(*source, pcm.len());
        }
        if let Some((tap, source)) = &self.tap {
            tap.push(*source, samples);
        }
        if let Some(tx) = &self.tx {
            let _ = tx.send(ChanMsg::Samples(samples.to_vec()));
        }
    }

    /// Writes out what is buffered and closes the file. Dropping the pipe also
    /// closes the channel to the phrase cutter.
    pub fn finish(self) {
        if let Err(e) = self.writer.finish() {
            error!("Closing meeting audio file failed: {e}");
        }
    }
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
    let generation = shared.generation();
    let open = |channel: Option<u16>| {
        let shared = Arc::clone(shared);
        Recorder::open_with_failure_handler(recorder_config(device.clone(), channel), move |e| {
            shared.report_failure(generation, format!("audio device failed: {e}"));
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

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::mpsc;

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
    fn a_reopened_channel_is_levelled_with_the_other_by_silence() {
        use super::super::storage::channel_samples;
        let mic_dir = tempfile::tempdir().unwrap();
        let sys_dir = tempfile::tempdir().unwrap();
        let timeline = Arc::new(Timeline::new(0, 0));
        let pipe = |dir: &std::path::Path, name: &str, source| {
            let writer = PcmWriter::new(dir, name, 16_000 * 60).unwrap();
            ChannelPipe::disk_only(
                writer,
                Arc::new(ChannelShared::default()),
                Instant::now(),
                0.0,
            )
            .with_timeline(Arc::clone(&timeline), source)
        };
        let mut mic = pipe(mic_dir.path(), "mic", Source::Mic);
        let mut system = pipe(sys_dir.path(), "system", Source::System);
        mic.push(&[0.1; 16_000]);
        system.push(&[0.1; 16_000]);
        // The system channel fails for three seconds while the microphone runs.
        for _ in 0..3 {
            mic.push(&[0.1; 16_000]);
        }
        system.finish();
        // It comes back: a new pipe on the same files is padded to the microphone.
        let mut system = pipe(sys_dir.path(), "system", Source::System);
        system.pad_silence(timeline.lag(Source::System));
        system.push(&[0.1; 16_000]);
        mic.push(&[0.1; 16_000]);
        mic.finish();
        system.finish();
        assert_eq!(channel_samples(mic_dir.path(), "mic"), 5 * 16_000);
        assert_eq!(channel_samples(sys_dir.path(), "system"), 5 * 16_000);
        assert_eq!(timeline.lag(Source::System), 0);
    }

    #[test]
    fn the_first_audio_starts_the_cutter_at_the_channels_own_position() {
        let dir = tempfile::tempdir().unwrap();
        let (tx, rx) = mpsc::channel();
        let writer = PcmWriter::new(dir.path(), "mic", 16_000).unwrap();
        // A resumed meeting: 7 s are on disk already.
        let timeline = Arc::new(Timeline::new(7 * 16_000, 0));
        let mut pipe = ChannelPipe::new(
            writer,
            tx,
            Arc::new(ChannelShared::default()),
            Instant::now(),
            0.0,
        )
        .with_timeline(timeline, Source::Mic);
        pipe.push(&[0.5; 512]);
        match rx.recv().unwrap() {
            ChanMsg::Start { offset_secs } => assert_eq!(offset_secs, 7.0),
            ChanMsg::Samples(_) => panic!("start comes first"),
        }
        pipe.finish();
    }

    #[test]
    fn a_channel_that_opens_late_keeps_the_times_of_its_phrases() {
        // The microphone has 2 s; the system channel opens now. It is levelled
        // with silence first, so the cutter sees its audio 2 s in, not at 0.
        let dir = tempfile::tempdir().unwrap();
        let (tx, rx) = mpsc::channel();
        let timeline = Arc::new(Timeline::new(2 * 16_000, 0));
        let writer = PcmWriter::new(dir.path(), "system", 16_000 * 60).unwrap();
        let mut pipe = ChannelPipe::new(
            writer,
            tx,
            Arc::new(ChannelShared::default()),
            Instant::now(),
            0.0,
        )
        .with_timeline(Arc::clone(&timeline), Source::System);
        pipe.pad_silence(timeline.lag(Source::System));
        pipe.push(&[0.5; 512]);
        pipe.finish();

        let mut offset = None;
        let mut before_audio = 0usize;
        for message in rx {
            match message {
                ChanMsg::Start { offset_secs } => offset = Some(offset_secs),
                ChanMsg::Samples(s) if s.iter().all(|v| *v == 0.0) => before_audio += s.len(),
                ChanMsg::Samples(_) => break,
            }
        }
        // The cutter's own clock starts at the channel's first sample (0) and
        // counts the silence, so the audio lands at 2 s.
        assert_eq!(offset, Some(0.0));
        assert_eq!(before_audio, 2 * 16_000);
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
