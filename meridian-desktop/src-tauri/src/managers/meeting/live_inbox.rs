//! What the server says on the live stream, put where it belongs: phrases,
//! translations, speakers and sides go into `meetings.db` and to the UI.

use std::collections::HashMap;
use std::sync::Mutex;

use log::warn;
use tauri_specta::Event;

use super::db_live::ServerSegment;
use super::live_proto::{channel_for_hint, channel_for_side, Committed, ServerEvent};
use super::live_stream::LiveContext;
use super::{now_iso, MeetingPartial, MeetingSegment, Segment};

/// Side hints that came before their phrase are kept this many.
const MAX_PENDING_SIDES: usize = 64;

/// What a server event means for the connection itself.
#[derive(Debug, PartialEq, Eq)]
pub(super) enum Handled {
    Nothing,
    /// The server does not take our audio now.
    Refused(String),
    /// The room's recording state, and the connection that records.
    Recording {
        on: bool,
        source: Option<String>,
    },
    /// Our connection's id in the room.
    Joined(String),
}

/// Stores what the server says and tells the UI.
pub(super) struct Inbox<'a> {
    pub(super) ctx: &'a LiveContext,
    /// Meeting time of the first sample of this connection's audio.
    offset: f64,
    /// The side of a phrase the server named before the phrase itself arrived.
    pending_sides: Mutex<HashMap<String, &'static str>>,
}

impl<'a> Inbox<'a> {
    pub(super) fn new(ctx: &'a LiveContext, offset: f64) -> Self {
        Self {
            ctx,
            offset,
            pending_sides: Mutex::new(HashMap::new()),
        }
    }

    fn meeting_now(&self) -> f64 {
        self.ctx.timeline.seconds()
    }

    /// The phrase being heard now; empty text clears it.
    pub(super) fn partial(&self, text: String) {
        let _ = MeetingPartial {
            meeting_id: self.ctx.meeting.id.clone(),
            text,
        }
        .emit(&self.ctx.app);
    }

    fn announce(&self, segment: Segment) {
        let _ = MeetingSegment { segment }.emit(&self.ctx.app);
    }

    fn take_pending_side(&self, segment_id: &str) -> Option<&'static str> {
        self.pending_sides
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .remove(segment_id)
    }

    fn committed(&self, c: Committed) {
        let now = self.meeting_now();
        // The server counts from the start of this connection's audio.
        let start = (self.offset + c.start_time).clamp(0.0, now);
        let end = (self.offset + c.end_time).clamp(start, now.max(start));
        let channel = self
            .take_pending_side(&c.segment_id)
            .unwrap_or_else(|| channel_for_side(c.side.as_deref(), self.ctx.tap.two_channels()));
        let segment = ServerSegment {
            meeting_id: self.ctx.meeting.id.clone(),
            server_id: c.segment_id,
            channel: channel.to_string(),
            start_time: start,
            end_time: end,
            text: c.text,
            language: c.language.filter(|l| !l.eq_ignore_ascii_case("und")),
            translation: c.translation,
            speaker: c.speaker,
            created_at: now_iso(),
        };
        match self.ctx.db.upsert_server_segment(&segment) {
            Ok(stored) => {
                self.partial(String::new());
                self.announce(stored);
            }
            Err(e) => warn!("Cannot store a live phrase: {e:#}"),
        }
    }

    /// The server's hint of the side comes by the levels of the two sources;
    /// it only means something in a meeting with two channels.
    fn side_hint(&self, segment_id: String, side: &str) {
        if !self.ctx.tap.two_channels() {
            return;
        }
        let channel = channel_for_hint(side);
        match self
            .ctx
            .db
            .set_segment_channel(&self.ctx.meeting.id, &segment_id, channel)
        {
            Ok(Some(segment)) => self.announce(segment),
            // The phrase is not here yet: keep the side for it.
            Ok(None) => {
                let mut pending = self.pending_sides.lock().unwrap_or_else(|e| e.into_inner());
                if pending.len() >= MAX_PENDING_SIDES {
                    pending.clear();
                }
                pending.insert(segment_id, channel);
            }
            Err(e) => warn!("Cannot store a side: {e:#}"),
        }
    }

    pub(super) fn handle(&self, event: ServerEvent) -> Handled {
        let id = &self.ctx.meeting.id;
        match event {
            ServerEvent::Partial { text } => self.partial(text),
            ServerEvent::Committed(c) => self.committed(c),
            ServerEvent::Translation { segment_id, text } => {
                match self.ctx.db.set_segment_translation(id, &segment_id, &text) {
                    Ok(Some(segment)) => self.announce(segment),
                    Ok(None) => {}
                    Err(e) => warn!("Cannot store a translation: {e:#}"),
                }
            }
            ServerEvent::Speaker {
                segment_id,
                speaker,
            } => match self.ctx.db.set_segment_speaker(id, &segment_id, &speaker) {
                Ok(Some(segment)) => self.announce(segment),
                Ok(None) => {}
                Err(e) => warn!("Cannot store a speaker: {e:#}"),
            },
            ServerEvent::SideHint { segment_id, side } => self.side_hint(segment_id, &side),
            ServerEvent::Refused { reason } => return Handled::Refused(reason),
            ServerEvent::Recording { recording, source } => {
                return Handled::Recording {
                    on: recording,
                    source,
                }
            }
            ServerEvent::Joined { connection_id } => return Handled::Joined(connection_id),
            ServerEvent::Error { message } => warn!("Live server error: {message}"),
            ServerEvent::Pong | ServerEvent::Other => {}
        }
        Handled::Nothing
    }
}
