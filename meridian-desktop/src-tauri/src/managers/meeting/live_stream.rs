//! The live link of a meeting to the server: one thread with its own small
//! async runtime opens the socket, sends the mixed audio and the levels of the
//! two sources, takes the phrases back into `meetings.db`, and reconnects with
//! a growing pause when the link drops. The capture never waits for it: the
//! audio goes to disk first, the tap (`live_mix.rs`) only copies it.
//!
//! Without a link the meeting is recorded like a dictaphone. When the link
//! returns, live recognition continues from the present; the audio of the gap
//! is not sent (the refinement after the stop recognizes the whole recording).

use std::future::Future;
use std::sync::{Arc, Mutex};
use std::thread::JoinHandle;
use std::time::{Duration, Instant};

use futures_util::{Sink, StreamExt};
use log::{debug, info, warn};
use tauri::{AppHandle, Manager};
use tokio::sync::watch;
use tokio::time::{interval, sleep, timeout, MissedTickBehavior};
use tokio_tungstenite::tungstenite::Message;

use super::live_conn::{finish, now_ms, send, MAX_FRAME_SAMPLES};
use super::live_inbox::{Handled, Inbox};
use super::live_mix::{LevelsAcc, LiveTap};
use super::live_proto::{self as proto, fatal_close, parse_server_message};
use super::live_proxy;
use super::live_report::{Backoff, Reporter};
use super::live_types::{LinkEvent, LiveState, LiveStatus};
use super::timeline::Timeline;
use super::{MeetingDb, MeetingInfo};
use crate::managers::sync::{prepare_live, AccountStore, ApiError, LiveError};

const TICK: Duration = Duration::from_millis(100);
const LEVELS_EVERY: Duration = Duration::from_millis(150);
const PING_EVERY: Duration = Duration::from_secs(15);
/// No frame from the server for this long: the link is dead.
const SILENCE_LIMIT: Duration = Duration::from_secs(45);
const CONNECT_TIMEOUT: Duration = Duration::from_secs(15);
/// The server must confirm `start_listening` (`recording:true`) within this.
const START_WAIT: Duration = Duration::from_secs(10);
/// A connection that held this long counts as good: the pauses start over.
const STABLE_AFTER: Duration = Duration::from_secs(10);

/// The server refused our audio (another device records, an old server): ask again rarely.
const REFUSED_DELAY: Duration = Duration::from_secs(60);
/// Just after the computer woke up the server may still take our dead old
/// connection for the source of the sound: the first refusals are asked again soon.
const REFUSED_AFTER_WAKE_DELAY: Duration = Duration::from_secs(5);
const REFUSED_AFTER_WAKE_TRIES: u32 = 6;

/// The pause after a refusal; `soon` counts the quick retries that are left.
fn refused_delay(soon: &mut u32) -> Duration {
    if *soon > 0 {
        *soon -= 1;
        REFUSED_AFTER_WAKE_DELAY
    } else {
        REFUSED_DELAY
    }
}

pub(super) struct LiveContext {
    pub(super) app: AppHandle,
    pub(super) db: Arc<MeetingDb>,
    pub(super) meeting: MeetingInfo,
    /// What the channels have recorded: the meeting's time.
    pub(super) timeline: Arc<Timeline>,
    pub(super) tap: Arc<LiveTap>,
    /// Bumped when the connection must be made anew now (the computer woke up).
    pub(super) reset: watch::Receiver<u64>,
}

/// A running live link. `stop` ends it and waits for the thread.
pub(super) struct LiveStream {
    stop: watch::Sender<bool>,
    thread: Option<JoinHandle<()>>,
    status: Arc<Mutex<LiveStatus>>,
}

impl LiveStream {
    pub(super) fn start(ctx: LiveContext) -> Option<Self> {
        let (stop, stop_rx) = watch::channel(false);
        let status = Arc::new(Mutex::new(LiveStatus::default()));
        let reporter = Reporter {
            app: ctx.app.clone(),
            meeting_id: ctx.meeting.id.clone(),
            status: Arc::clone(&status),
        };
        reporter.set(LiveState::Connecting, None);
        let spawned = std::thread::Builder::new()
            .name("meeting-live".into())
            .spawn(move || {
                let runtime = match tokio::runtime::Builder::new_current_thread()
                    .enable_all()
                    .build()
                {
                    Ok(runtime) => runtime,
                    Err(e) => {
                        warn!("Cannot start the live link runtime: {e}");
                        reporter.set(
                            LiveState::Recorder,
                            Some("Не удалось запустить онлайн-распознавание".to_string()),
                        );
                        return;
                    }
                };
                runtime.block_on(run(ctx, reporter, stop_rx));
            });
        match spawned {
            Ok(thread) => Some(Self {
                stop,
                thread: Some(thread),
                status,
            }),
            Err(e) => {
                warn!("Cannot start the live link thread: {e}");
                None
            }
        }
    }

    pub(super) fn status(&self) -> LiveStatus {
        self.status
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .clone()
    }

    /// Sends the audio that is left, asks the server for the last phrases
    /// (a few seconds at most) and closes the socket.
    pub(super) fn stop(mut self) {
        let _ = self.stop.send(true);
        if let Some(thread) = self.thread.take() {
            if thread.join().is_err() {
                warn!("The live link thread panicked");
            }
        }
    }
}

/// Why one connection attempt ended.
#[derive(Debug)]
enum Ended {
    /// The meeting stops.
    Stopped,
    /// No link or it dropped; `held` says the connection was a good one.
    Lost { reason: String, held: bool },
    /// The server does not take our audio now; try again rarely.
    Refused { reason: String },
    /// No attempt can succeed (token revoked, meeting closed): stay a dictaphone.
    Fatal { reason: String },
    /// The computer woke up: the old socket is dead, connect again at once.
    Restart,
}

async fn wait_stop(stop: &mut watch::Receiver<bool>) {
    while !*stop.borrow_and_update() {
        if stop.changed().await.is_err() {
            return;
        }
    }
}

/// `fut`, or `None` when the meeting stops first.
async fn until_stop<T>(
    stop: &mut watch::Receiver<bool>,
    fut: impl Future<Output = T>,
) -> Option<T> {
    tokio::select! {
        biased;
        () = wait_stop(stop) => None,
        value = fut => Some(value),
    }
}

/// Resolves when the connection has to be made anew; never if the sender is gone.
async fn wait_reset(reset: &mut watch::Receiver<u64>) {
    if reset.changed().await.is_err() {
        std::future::pending::<()>().await;
    }
}

async fn run(ctx: LiveContext, reporter: Reporter, mut stop: watch::Receiver<bool>) {
    let mut reset = ctx.reset.clone();
    reset.borrow_and_update();
    let mut backoff = Backoff::default();
    let mut first = true;
    let mut soon = 0u32;
    loop {
        if *stop.borrow() {
            break;
        }
        if !first {
            reporter.link(LinkEvent::Attempt, None);
        }
        first = false;
        let ended = tokio::select! {
            biased;
            ended = attempt(&ctx, &reporter, &mut stop) => ended,
            () = wait_reset(&mut reset) => {
                // The socket is dropped with the attempt; what it carried is gone.
                ctx.tap.set_enabled(false);
                Ended::Restart
            }
        };
        let delay = match ended {
            Ended::Stopped => break,
            Ended::Restart => {
                info!("Live link of {} is made anew", ctx.meeting.id);
                reporter.link(LinkEvent::Lost, Some("Компьютер вышел из сна".to_string()));
                backoff.reset();
                soon = REFUSED_AFTER_WAKE_TRIES;
                Duration::ZERO
            }
            Ended::Lost { reason, held } => {
                if held {
                    backoff.reset();
                }
                reporter.link(LinkEvent::Lost, Some(reason));
                backoff.next_delay()
            }
            Ended::Refused { reason } => {
                reporter.link(LinkEvent::Lost, Some(reason));
                refused_delay(&mut soon)
            }
            Ended::Fatal { reason } => {
                reporter.link(LinkEvent::Lost, Some(reason));
                // Nothing to retry: wait for the end of the meeting.
                wait_stop(&mut stop).await;
                break;
            }
        };
        let waited = until_stop(&mut stop, async {
            tokio::select! {
                () = sleep(delay) => {}
                () = wait_reset(&mut reset) => {}
            }
        })
        .await;
        if waited.is_none() {
            break;
        }
    }
    ctx.tap.set_enabled(false);
    debug!("Live link of {} finished", ctx.meeting.id);
}

fn api_reason(e: &ApiError) -> String {
    match e {
        ApiError::Retry { message, .. } => message.clone(),
        other => other.to_string(),
    }
}

/// One connection: prepares the meeting on the server, opens the socket and
/// streams until it ends.
async fn attempt(
    ctx: &LiveContext,
    reporter: &Reporter,
    stop: &mut watch::Receiver<bool>,
) -> Ended {
    let accounts = ctx.app.state::<Arc<AccountStore>>();
    let prepared = until_stop(stop, prepare_live(&accounts, &ctx.db, &ctx.meeting.id)).await;
    let endpoint = match prepared {
        None => return Ended::Stopped,
        Some(Ok(endpoint)) => endpoint,
        Some(Err(LiveError::NoAccount)) => {
            return Ended::Lost {
                reason: "Войдите в аккаунт, чтобы текст шёл сразу".to_string(),
                held: false,
            }
        }
        Some(Err(LiveError::Api(e))) => {
            let reason = api_reason(&e);
            return match e {
                ApiError::Retry { .. } => Ended::Lost {
                    reason,
                    held: false,
                },
                _ => Ended::Fatal { reason },
            };
        }
    };

    let connecting = timeout(CONNECT_TIMEOUT, live_proxy::connect(endpoint.ws_url()));
    let socket = match until_stop(stop, connecting).await {
        None => return Ended::Stopped,
        Some(Ok(Ok((socket, _)))) => socket,
        Some(Ok(Err(e))) => {
            // The address carries the token: only the kind of failure is logged.
            debug!("Live socket did not open: {}", error_kind(&e));
            return Ended::Lost {
                reason: "Нет связи с сервером".to_string(),
                held: false,
            };
        }
        Some(Err(_)) => {
            return Ended::Lost {
                reason: "Сервер не ответил вовремя".to_string(),
                held: false,
            }
        }
    };
    stream(ctx, reporter, stop, socket).await
}

fn error_kind(e: &tokio_tungstenite::tungstenite::Error) -> &'static str {
    use tokio_tungstenite::tungstenite::Error;
    match e {
        Error::Io(_) => "io",
        Error::Tls(_) => "tls",
        Error::Http(_) => "http",
        Error::Url(_) => "url",
        Error::ConnectionClosed | Error::AlreadyClosed => "closed",
        _ => "protocol",
    }
}

/// What a frame from the server means for the connection.
enum Frame {
    Continue,
    Recording { on: bool, source: Option<String> },
    Joined(String),
    Ended(Ended),
}

fn read_frame(inbox: &Inbox<'_>, message: Message, connected_at: Instant) -> Frame {
    match message {
        Message::Text(text) => match parse_server_message(text.as_str()).map(|e| inbox.handle(e)) {
            Some(Handled::Refused(reason)) => Frame::Ended(Ended::Refused { reason }),
            Some(Handled::Recording { on, source }) => Frame::Recording { on, source },
            Some(Handled::Joined(id)) => Frame::Joined(id),
            _ => Frame::Continue,
        },
        Message::Close(frame) => {
            let code = frame.map_or(1005, |f| u16::from(f.code));
            Frame::Ended(match fatal_close(code) {
                Some(reason) => Ended::Fatal {
                    reason: reason.to_string(),
                },
                None => Ended::Lost {
                    reason: "Связь с сервером прервана".to_string(),
                    held: connected_at.elapsed() >= STABLE_AFTER,
                },
            })
        }
        _ => Frame::Continue,
    }
}

async fn stream<S>(
    ctx: &LiveContext,
    reporter: &Reporter,
    stop: &mut watch::Receiver<bool>,
    socket: S,
) -> Ended
where
    S: futures_util::Stream<Item = Result<Message, tokio_tungstenite::tungstenite::Error>>
        + Sink<Message>
        + Unpin,
{
    let (mut write, mut read) = socket.split();
    let connected_at = Instant::now();
    let lost = |reason: &str| Ended::Lost {
        reason: reason.to_string(),
        held: connected_at.elapsed() >= STABLE_AFTER,
    };

    // Audio starts from the present: the tap keeps nothing from before.
    ctx.tap.set_enabled(true);
    let inbox = Inbox::new(ctx, ctx.timeline.seconds());
    if let Err(reason) = send(&mut write, Message::text(proto::start_listening())).await {
        ctx.tap.set_enabled(false);
        return lost(&reason);
    }
    // The first `recording_status` (false) comes on joining; the audio goes
    // only after the server says `recording: true`.
    let mut recording = false;
    // Our connection's id (`room_joined`): the recording counts only if it is ours.
    let mut my_id: Option<String> = None;

    let mut tick = interval(TICK);
    tick.set_missed_tick_behavior(MissedTickBehavior::Skip);
    let mut ping = interval(PING_EVERY);
    ping.set_missed_tick_behavior(MissedTickBehavior::Skip);
    let mut last_rx = Instant::now();
    let mut levels_sent = Instant::now();
    let mut levels = LevelsAcc::default();
    let mut seq = 0u64;
    let mut reported_drops = 0u64;
    let started_at = Instant::now();

    let ended = loop {
        tokio::select! {
            biased;
            () = wait_stop(stop) => {
                finish(&inbox, &mut write, &mut read, recording).await;
                break Ended::Stopped;
            }
            frame = read.next() => match frame {
                None => break lost("Связь с сервером прервана"),
                Some(Err(_)) => break lost("Связь с сервером прервана"),
                Some(Ok(message)) => {
                    last_rx = Instant::now();
                    match read_frame(&inbox, message, connected_at) {
                        Frame::Ended(ended) => break ended,
                        Frame::Joined(id) => my_id = Some(id),
                        Frame::Recording { on: true, source }
                            if !recording
                                && my_id.as_deref().is_none_or(|id| source.as_deref() == Some(id)) =>
                        {
                            recording = true;
                            reporter.link(LinkEvent::Connected, None);
                            info!("Live link of {} is online", ctx.meeting.id);
                        }
                        Frame::Recording { on: false, .. } if recording => {
                            // Another device took the recording over, or the server stopped it.
                            break lost("Сервер остановил приём звука");
                        }
                        _ => {}
                    }
                }
            },
            _ = tick.tick() => {
                if !recording {
                    if started_at.elapsed() > START_WAIT {
                        break lost("Сервер не начал приём звука");
                    }
                    continue;
                }
                let drained = ctx.tap.drain();
                levels.mic.merge(drained.mic);
                levels.system.merge(drained.system);
                for part in drained.pcm.chunks(MAX_FRAME_SAMPLES) {
                    if let Err(reason) = send(&mut write, Message::binary(proto::pcm_bytes(part))).await {
                        ctx.tap.set_enabled(false);
                        return lost(&reason);
                    }
                }
                if ctx.tap.two_channels() && levels_sent.elapsed() >= LEVELS_EVERY {
                    levels_sent = Instant::now();
                    seq += 1;
                    let text = proto::audio_source_levels(levels.take(), seq, now_ms());
                    if let Err(reason) = send(&mut write, Message::text(text)).await {
                        ctx.tap.set_enabled(false);
                        return lost(&reason);
                    }
                }
                let dropped = ctx.tap.dropped();
                if dropped != reported_drops {
                    reported_drops = dropped;
                    warn!("Live link is slow: {dropped} samples dropped so far");
                }
            },
            _ = ping.tick() => {
                if last_rx.elapsed() > SILENCE_LIMIT {
                    break lost("Сервер не отвечает");
                }
                if let Err(reason) = send(&mut write, Message::text(proto::ping(now_ms()))).await {
                    ctx.tap.set_enabled(false);
                    return lost(&reason);
                }
            },
        }
    };
    ctx.tap.set_enabled(false);
    // A phrase that was being heard is not going to be finished.
    inbox.partial(String::new());
    ended
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_first_refusals_after_a_wake_are_asked_again_soon() {
        let mut soon = REFUSED_AFTER_WAKE_TRIES;
        for _ in 0..REFUSED_AFTER_WAKE_TRIES {
            assert_eq!(refused_delay(&mut soon), REFUSED_AFTER_WAKE_DELAY);
        }
        assert_eq!(refused_delay(&mut soon), REFUSED_DELAY);
        // Without a wake the pause is the long one from the start.
        assert_eq!(refused_delay(&mut 0), REFUSED_DELAY);
    }
}
