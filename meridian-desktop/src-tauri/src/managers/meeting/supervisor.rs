//! Keeps the channels of a running meeting alive. One thread per session:
//!
//! - the computer slept (the thread found a gap between two of its looks):
//!   the gap is written down as a pause of the meeting, every capture is
//!   opened anew (a loopback that died in the sleep cannot be told from
//!   silence), and the live connection is made anew. No silence is added for
//!   the sleep, to any channel;
//! - a capture failed (the device went away, the stream broke), or the
//!   microphone stopped delivering, or the system's default device changed:
//!   that channel is closed and opened again, with a growing pause between
//!   attempts, first on the chosen device and then on the default one. The
//!   channel is levelled with the other by silence for the time it was away.
//!   The user sees an error only when this does not work for 30 seconds.
//!
//! Nothing here is done under the manager's lock: opening a device can take
//! seconds.

use std::sync::mpsc::{self, RecvTimeoutError, Sender};
use std::sync::{Arc, Mutex};
use std::thread::JoinHandle;
use std::time::{Duration, Instant, SystemTime};

use chrono::{DateTime, SecondsFormat, Utc};
use log::{info, warn};
use tokio::sync::watch;

use super::capture::ChannelShared;
use super::channel::{
    channel_title, default_device_id, source_of, ChannelFactory, ChannelRuntime, Devices,
};
use super::db_pauses::Pause;
use super::sleep::{Gap, GapDetector};
use super::timeline::Timeline;
use super::{MeetingDb, CHANNEL_MIC};

const LOOK_EVERY: Duration = Duration::from_millis(250);
/// The microphone delivered nothing for this long while it did before: it is stuck.
const STALE_AFTER: Duration = Duration::from_secs(6);
/// The default device is looked up this often.
const DEFAULT_CHECK_EVERY: Duration = Duration::from_secs(4);
/// The user is told when the channel could not be reopened for this long.
const GIVE_UP_AFTER: Duration = Duration::from_secs(30);
/// After giving up, a new attempt this often (the device may come back).
const SLOW_RETRY: Duration = Duration::from_secs(10);

/// Pause before attempt number `attempt` (0, 1, 2 ...): 1, 2, 4, 8 s, then 8 s.
fn retry_delay(attempt: u32) -> Duration {
    Duration::from_secs(1 << attempt.min(3))
}

/// The devices to try on attempt number `attempt`: the chosen ones, and every
/// other time the system's defaults (the chosen device may be gone for good).
fn devices_for_attempt(chosen: &Devices, attempt: u32) -> Devices {
    if attempt % 2 == 1 {
        Devices::defaults()
    } else {
        chosen.clone()
    }
}

pub(super) struct SupervisorCtx {
    pub(super) factory: Arc<ChannelFactory>,
    pub(super) channels: Arc<Mutex<Vec<ChannelRuntime>>>,
    pub(super) devices: Devices,
    pub(super) db: Arc<MeetingDb>,
    pub(super) meeting_id: String,
    pub(super) timeline: Arc<Timeline>,
    /// Bumped to make the live connection anew.
    pub(super) live_reset: Arc<watch::Sender<u64>>,
}

pub(super) struct Supervisor {
    stop: Sender<()>,
    thread: Option<JoinHandle<()>>,
}

impl Supervisor {
    pub(super) fn start(ctx: SupervisorCtx) -> Option<Self> {
        let (stop, rx) = mpsc::channel();
        let thread = std::thread::Builder::new()
            .name("meeting-supervisor".into())
            .spawn(move || Runner::new(ctx).run(&rx))
            .map_err(|e| warn!("Cannot start the meeting supervisor: {e}"))
            .ok()?;
        Some(Self {
            stop,
            thread: Some(thread),
        })
    }

    /// Ends the thread; waits for a reopening that is under way.
    pub(super) fn stop(mut self) {
        let _ = self.stop.send(());
        if let Some(thread) = self.thread.take() {
            if thread.join().is_err() {
                warn!("The meeting supervisor panicked");
            }
        }
    }
}

/// A channel that is not running now.
struct Down {
    since: Instant,
    attempt: u32,
    next_try: Instant,
    told: bool,
}

/// What the supervisor knows about one channel.
struct Watched {
    audio_name: &'static str,
    shared: Arc<ChannelShared>,
    down: Option<Down>,
    /// The channel's samples at the last look, and when they last changed.
    samples: u64,
    changed_at: Instant,
    /// Samples came since the capture was opened (so silence is a fault).
    delivered: bool,
    default_id: Option<String>,
    default_checked: Instant,
}

impl Watched {
    fn new(audio_name: &'static str, shared: Arc<ChannelShared>, timeline: &Timeline) -> Self {
        Self {
            audio_name,
            shared,
            down: None,
            samples: timeline.samples(source_of(audio_name)),
            changed_at: Instant::now(),
            delivered: false,
            default_id: default_device_id(audio_name),
            default_checked: Instant::now(),
        }
    }

    /// A capture was just opened: wait for its first audio before judging it.
    fn fresh(&mut self, timeline: &Timeline) {
        self.samples = timeline.samples(source_of(self.audio_name));
        self.changed_at = Instant::now();
        self.delivered = false;
        self.default_id = default_device_id(self.audio_name);
        self.default_checked = Instant::now();
    }
}

struct Runner {
    ctx: SupervisorCtx,
    watched: Vec<Watched>,
}

impl Runner {
    fn new(ctx: SupervisorCtx) -> Self {
        let watched = ctx
            .channels
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .iter()
            .map(|c| Watched::new(c.audio_name, Arc::clone(&c.shared), &ctx.timeline))
            .collect();
        Self { ctx, watched }
    }

    fn run(&mut self, stop: &mpsc::Receiver<()>) {
        let mut gap = GapDetector::new();
        loop {
            match stop.recv_timeout(LOOK_EVERY) {
                Err(RecvTimeoutError::Timeout) => {}
                _ => return,
            }
            let slept = gap.look();
            if let Some(slept) = slept {
                self.on_sleep(slept);
            }
            for index in 0..self.watched.len() {
                if let Some(reason) = self.check(index, slept.is_some()) {
                    self.close(index, &reason);
                }
                if !self.try_reopen(index, stop) {
                    return;
                }
            }
            // Reopening takes long on purpose: it is no sleep.
            gap.touch();
        }
    }

    /// The computer slept: write the pause down, reopen the captures and the
    /// live connection.
    fn on_sleep(&self, gap: Gap) {
        info!(
            "The computer was away for {:?}: the meeting's channels are reopened",
            gap.length
        );
        let iso = |time: SystemTime| {
            DateTime::<Utc>::from(time).to_rfc3339_opts(SecondsFormat::Millis, true)
        };
        let pause = Pause {
            at_seconds: self.ctx.timeline.seconds(),
            paused_at: iso(gap.from),
            resumed_at: iso(gap.to),
            kind: "sleep".to_string(),
        };
        if let Err(e) = self.ctx.db.add_pause(&self.ctx.meeting_id, &pause) {
            warn!("Cannot write down a pause of the meeting: {e:#}");
        }
        self.ctx.live_reset.send_modify(|n| *n += 1);
    }

    /// Why the channel has to be opened again, if it does.
    fn check(&mut self, index: usize, slept: bool) -> Option<String> {
        let timeline = Arc::clone(&self.ctx.timeline);
        let explicit = match self.watched[index].audio_name {
            CHANNEL_MIC => self.ctx.devices.mic.is_some(),
            _ => self.ctx.devices.system.is_some(),
        };
        let w = &mut self.watched[index];
        if w.down.is_some() {
            return None;
        }
        if slept {
            return Some("the computer woke up".to_string());
        }
        if let Some(failure) = w.shared.take_failure() {
            return Some(failure);
        }
        // Only the microphone delivers all the time; a loopback is silent
        // when nothing plays and is told apart only by its own error.
        if w.audio_name == CHANNEL_MIC {
            let now = timeline.samples(source_of(w.audio_name));
            if now != w.samples {
                w.samples = now;
                w.changed_at = Instant::now();
                w.delivered = true;
            } else if w.delivered && w.changed_at.elapsed() >= STALE_AFTER {
                return Some("the microphone stopped delivering".to_string());
            }
        }
        if !explicit && w.default_checked.elapsed() >= DEFAULT_CHECK_EVERY {
            w.default_checked = Instant::now();
            let now = default_device_id(w.audio_name);
            if now.is_some() && w.default_id.is_some() && now != w.default_id {
                return Some("the default device changed".to_string());
            }
        }
        None
    }

    /// Closes the channel (its tail goes to the disk) and marks it down.
    fn close(&mut self, index: usize, reason: &str) {
        let w = &mut self.watched[index];
        info!("Meeting channel '{}' is reopened: {reason}", w.audio_name);
        // The old capture's late reports are not about the next one.
        w.shared.next_generation();
        let runtime = {
            let mut channels = self.ctx.channels.lock().unwrap_or_else(|e| e.into_inner());
            channels
                .iter()
                .position(|c| c.audio_name == w.audio_name)
                .map(|at| channels.remove(at))
        };
        if let Some(runtime) = runtime {
            runtime.close();
        }
        let now = Instant::now();
        w.down = Some(Down {
            since: now,
            attempt: 0,
            next_try: now,
            told: false,
        });
    }

    /// One attempt to open a channel that is down, when it is due. `false`:
    /// the meeting stops.
    fn try_reopen(&mut self, index: usize, stop: &mpsc::Receiver<()>) -> bool {
        let (audio_name, shared, attempt) = {
            let w = &self.watched[index];
            match &w.down {
                Some(down) if Instant::now() >= down.next_try => {
                    (w.audio_name, Arc::clone(&w.shared), down.attempt)
                }
                _ => return true,
            }
        };
        let devices = devices_for_attempt(&self.ctx.devices, attempt);
        match self.ctx.factory.open(audio_name, &devices, shared) {
            Ok(runtime) => {
                info!(
                    "Meeting channel '{audio_name}' is back (attempt {})",
                    attempt + 1
                );
                self.put_back(runtime);
                let w = &mut self.watched[index];
                w.down = None;
                w.fresh(&self.ctx.timeline);
            }
            Err(message) => {
                let w = &mut self.watched[index];
                let Some(down) = w.down.as_mut() else {
                    return true;
                };
                warn!(
                    "Reopening '{audio_name}' failed (attempt {}): {message}",
                    attempt + 1
                );
                down.attempt += 1;
                down.next_try = Instant::now()
                    + if down.told {
                        SLOW_RETRY
                    } else {
                        retry_delay(attempt)
                    };
                if !down.told && down.since.elapsed() >= GIVE_UP_AFTER {
                    down.told = true;
                    w.shared.report_error(format!(
                        "{}: не удалось переподключить устройство ({message}). Запись другого канала идёт; попытки продолжаются",
                        channel_title(audio_name)
                    ));
                }
            }
        }
        // Waiting for the next attempt is waiting for the next look.
        !matches!(
            stop.try_recv(),
            Ok(()) | Err(mpsc::TryRecvError::Disconnected)
        )
    }

    /// The reopened channel goes back to its place (the microphone first).
    fn put_back(&self, runtime: ChannelRuntime) {
        let mut channels = self.ctx.channels.lock().unwrap_or_else(|e| e.into_inner());
        let at = if runtime.audio_name == CHANNEL_MIC {
            0
        } else {
            channels.len()
        };
        channels.insert(at, runtime);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn pauses_between_attempts_grow_to_eight_seconds() {
        let secs: Vec<u64> = (0..6).map(|n| retry_delay(n).as_secs()).collect();
        assert_eq!(secs, [1, 2, 4, 8, 8, 8]);
    }

    #[test]
    fn every_other_attempt_goes_to_the_default_devices() {
        let chosen = Devices {
            mic: Some("usb-mic".into()),
            mic_channel: Some(1),
            system: Some("hdmi".into()),
        };
        assert_eq!(
            devices_for_attempt(&chosen, 0).mic.as_deref(),
            Some("usb-mic")
        );
        let fallback = devices_for_attempt(&chosen, 1);
        assert!(fallback.mic.is_none() && fallback.system.is_none());
        assert_eq!(
            devices_for_attempt(&chosen, 2).system.as_deref(),
            Some("hdmi")
        );
    }
}
