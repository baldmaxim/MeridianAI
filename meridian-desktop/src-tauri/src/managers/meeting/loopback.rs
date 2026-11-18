//! System sound as a loopback of a playback device: WASAPI on Windows, a Core
//! Audio tap on macOS 14.6+. `handy-cpal` turns an input stream built on a
//! render device into a loopback capture, which `handy-recorder` can't open
//! because it lists capture devices only.

use std::sync::mpsc::{self, RecvTimeoutError, Sender};
use std::sync::{Arc, Mutex};
use std::thread::JoinHandle;
use std::time::{Duration, Instant, SystemTime};

use cpal::traits::{DeviceTrait, HostTrait, StreamTrait};
use cpal::FromSample;
use log::{debug, error, info};

use super::capture::{CaptureDevice, ChannelPipe};
use super::sleep::GapDetector;
use super::storage::SAMPLE_RATE;
use crate::audio_toolkit::StreamResampler;

/// Loopback delivers nothing while nothing plays; silence is added every tick.
const LOOPBACK_TICK: Duration = Duration::from_millis(250);
/// Audio may lag the wall clock this much before silence is added for it.
const LOOPBACK_TOLERANCE_SECS: f64 = 0.5;

/// Zero samples to add so the channel keeps up with the wall clock: loopback
/// sends no packets while nothing plays. `incoming` samples are about to be
/// pushed and are the newest audio.
fn silence_to_add(pushed: u64, elapsed_secs: f64, incoming: usize, tolerance_secs: f64) -> usize {
    let expected =
        ((elapsed_secs - tolerance_secs) * f64::from(SAMPLE_RATE)) as i64 - incoming as i64;
    (expected - pushed as i64).max(0) as usize
}

struct LoopbackState {
    pipe: ChannelPipe,
    resampler: StreamResampler,
    started: Instant,
    pushed: u64,
    /// Looks at the clocks at every padding: a gap is a sleep.
    gap: GapDetector,
}

impl LoopbackState {
    fn new(pipe: ChannelPipe, resampler: StreamResampler) -> Self {
        Self {
            pipe,
            resampler,
            started: Instant::now(),
            pushed: 0,
            gap: GapDetector::new(),
        }
    }

    /// How much silence the clocks call for before `incoming` new samples,
    /// seen at `wall`/`mono`. After a sleep it is none: nothing was played
    /// while the computer slept, the other channel got no silence for it
    /// either, and `Instant` may or may not have run through it (it does on
    /// Windows). The clock is set back to the audio, so the padding goes on
    /// from there.
    fn missing_at(
        &mut self,
        incoming: usize,
        tolerance_secs: f64,
        wall: SystemTime,
        mono: Instant,
    ) -> usize {
        if let Some(gap) = self.gap.observe(wall, mono) {
            info!("System sound: the computer was away for {:?}", gap.length);
            let audio = Duration::from_secs_f64(self.pushed as f64 / f64::from(SAMPLE_RATE));
            self.started = mono.checked_sub(audio).unwrap_or(mono);
            return 0;
        }
        silence_to_add(
            self.pushed,
            mono.saturating_duration_since(self.started).as_secs_f64(),
            incoming,
            tolerance_secs,
        )
    }

    /// Adds the silence the wall clock calls for before `incoming` new samples.
    fn pad(&mut self, incoming: usize, tolerance_secs: f64) {
        let missing = self.missing_at(incoming, tolerance_secs, SystemTime::now(), Instant::now());
        self.pipe.pad_silence(missing);
        self.pushed += missing as u64;
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

#[cfg_attr(not(any(windows, target_os = "macos")), allow(dead_code))]
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

/// Playback devices, the sources of system sound on Windows and macOS.
#[cfg_attr(not(any(windows, target_os = "macos")), allow(dead_code))]
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

#[cfg_attr(not(any(windows, target_os = "macos")), allow(dead_code))]
impl LoopbackCapture {
    /// Opens the stream on its own thread (some hosts' streams are not
    /// `Send`) and waits until it plays or fails. On failure the pipe is gone.
    pub fn start(device_id: Option<String>, pipe: ChannelPipe) -> Result<Self, String> {
        let shared = Arc::clone(&pipe.shared);
        let generation = shared.generation();
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
        let state = Arc::new(Mutex::new(Some(LoopbackState::new(pipe, resampler))));
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
                    move |e| {
                        shared.report_failure(
                            generation,
                            format!("system sound capture failed: {e}"),
                        );
                    },
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
    use crate::managers::meeting::capture::ChannelShared;

    /// A loopback state at `pushed` samples of audio, started at `started`.
    fn state(dir: &std::path::Path, pushed: u64, started: Instant) -> LoopbackState {
        let writer = super::super::storage::PcmWriter::new(dir, "system", 16_000).unwrap();
        let pipe = ChannelPipe::disk_only(writer, Arc::new(ChannelShared::default()), started, 0.0);
        let mut state =
            LoopbackState::new(pipe, StreamResampler::new(48_000, SAMPLE_RATE).unwrap());
        state.started = started;
        state.pushed = pushed;
        state
    }

    #[test]
    fn a_sleep_adds_no_silence_whichever_clock_ran_through_it() {
        let dir = tempfile::tempdir().unwrap();
        let night = Duration::from_secs(8 * 3600);
        let quarter = Duration::from_millis(250);
        for monotonic_runs_through_sleep in [true, false] {
            let (wall0, mono0) = (SystemTime::now(), Instant::now());
            let ten = 10 * u64::from(SAMPLE_RATE);
            let mut s = state(dir.path(), ten, mono0 - Duration::from_secs(10));
            s.gap = GapDetector::new();
            // Ordinary ticks: the audio keeps up, nothing to add.
            assert_eq!(s.missing_at(0, 0.5, wall0 + quarter, mono0 + quarter), 0);
            // The computer sleeps all night.
            let mono_after = if monotonic_runs_through_sleep {
                mono0 + night
            } else {
                mono0 + quarter * 2
            };
            assert_eq!(s.missing_at(0, 0.5, wall0 + night, mono_after), 0);
            // The clock is set back to the audio: two quiet seconds are padded
            // as ever, not eight hours.
            let wall_next = wall0 + night + Duration::from_secs(2);
            let mono_next = mono_after + Duration::from_secs(2);
            let missing = s.missing_at(0, 0.5, wall_next, mono_next);
            assert!(
                (23_900..=24_100).contains(&missing),
                "{monotonic_runs_through_sleep}: {missing}"
            );
        }
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
}
