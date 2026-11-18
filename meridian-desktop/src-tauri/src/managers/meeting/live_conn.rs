//! The small pieces of a live connection that carry no decision: sending with
//! a time limit, and the orderly end of a meeting's stream.

use std::time::{Duration, Instant};

use futures_util::{Sink, SinkExt, StreamExt};
use log::warn;
use tokio::time::timeout;
use tokio_tungstenite::tungstenite::Message;

use super::live_inbox::{Handled, Inbox};
use super::live_proto::{self as proto, parse_server_message};

const SEND_TIMEOUT: Duration = Duration::from_secs(5);
/// After `stop_listening` the server sends the last phrases and then
/// `recording_status{recording:false}`; wait for it this long.
const STOP_WAIT: Duration = Duration::from_secs(5);
/// Longest audio frame (1 s); more waiting audio goes in several frames.
pub(super) const MAX_FRAME_SAMPLES: usize = 16_000;

pub(super) async fn send<S>(sink: &mut S, message: Message) -> Result<(), String>
where
    S: Sink<Message> + Unpin,
{
    match timeout(SEND_TIMEOUT, sink.send(message)).await {
        Ok(Ok(())) => Ok(()),
        Ok(Err(_)) => Err("Связь с сервером прервана".to_string()),
        Err(_) => Err("Сервер не принимает звук".to_string()),
    }
}

pub(super) fn now_ms() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_or(0, |d| d.as_millis() as u64)
}

/// The meeting stops: the last audio, `stop_listening`, the phrases that are
/// still on their way, and a polite close.
pub(super) async fn finish<W, R>(inbox: &Inbox<'_>, write: &mut W, read: &mut R, recording: bool)
where
    W: Sink<Message> + Unpin,
    R: futures_util::Stream<Item = Result<Message, tokio_tungstenite::tungstenite::Error>> + Unpin,
{
    if recording {
        let drained = inbox.ctx.tap.drain();
        for part in drained.pcm.chunks(MAX_FRAME_SAMPLES) {
            if send(write, Message::binary(proto::pcm_bytes(part)))
                .await
                .is_err()
            {
                return;
            }
        }
    }
    if send(write, Message::text(proto::stop_listening()))
        .await
        .is_err()
    {
        return;
    }
    // The socket stays open until the server confirms the stop: closing earlier
    // loses the last phrases, and the refinement would then duplicate them.
    let deadline = Instant::now() + STOP_WAIT;
    loop {
        let left = deadline.saturating_duration_since(Instant::now());
        if left.is_zero() {
            warn!("The server did not confirm the stop in time");
            break;
        }
        match timeout(left, read.next()).await {
            Ok(Some(Ok(Message::Text(text)))) => {
                if let Some(event) = parse_server_message(text.as_str()) {
                    if matches!(inbox.handle(event), Handled::Recording { on: false, .. }) {
                        break;
                    }
                }
            }
            Ok(Some(Ok(Message::Close(_)))) | Ok(None) | Ok(Some(Err(_))) | Err(_) => break,
            Ok(Some(Ok(_))) => {}
        }
    }
    let _ = timeout(Duration::from_secs(2), write.close()).await;
}
