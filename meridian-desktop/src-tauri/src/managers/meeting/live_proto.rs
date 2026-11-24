//! The wire protocol of the live stream (`/ws/desktop/meetings/{id}`), the same
//! one the site's client speaks: JSON text frames and binary PCM frames.
//!
//! Client -> server: `start_listening`, `stop_listening`, `ping`,
//! `audio_source_levels`; binary: PCM 16 kHz mono s16le.
//! Server -> client: `transcript` (partial), `committed_transcript`,
//! `segment_translation`, `segment_speaker`, `error`, `pong`, and the
//! refusals; everything else the room says is ignored.

use serde_json::{json, Value};

/// Close codes of the server that end the attempts (the meeting is not
/// ours, is closed, or the token is revoked).
pub(super) const CLOSE_UNAUTHORIZED: u16 = 4401;
pub(super) const CLOSE_NOT_FOUND: u16 = 4404;
pub(super) const CLOSE_MEETING_CLOSED: u16 = 4409;

/// The labels the server gives the two sides of an online meeting.
const SIDE_SELF: &str = "Мы";
const SIDE_OPPONENT: &str = "Оппонент";

#[derive(Clone, Debug, PartialEq)]
pub(super) enum ServerEvent {
    /// The phrase being spoken (not final); empty text clears it.
    Partial {
        text: String,
    },
    Committed(Committed),
    Translation {
        segment_id: String,
        text: String,
    },
    Speaker {
        segment_id: String,
        speaker: String,
    },
    /// The server does not take our audio now (another device records, no
    /// permission, an old server): keep recording, try again later.
    Refused {
        reason: String,
    },
    /// A server error that does not stop the stream.
    Error {
        message: String,
    },
    /// The room's recording state: it turns `true` once `start_listening` is
    /// taken, and `false` when the stop is done (the last phrases are in).
    /// `source` is the connection that records.
    Recording {
        recording: bool,
        source: Option<String>,
    },
    /// Our connection's id in the room (to tell whose recording it is).
    Joined {
        connection_id: String,
    },
    /// The side of a phrase the server worked out from the levels of the two
    /// sources: `self` or `opponent`.
    SideHint {
        segment_id: String,
        side: String,
    },
    /// Who is connected to the room now (one entry per connection).
    Participants(Vec<RoomParticipant>),
    Pong,
    /// Anything else the room sends.
    Other,
}

/// One connection (device) in the room.
#[derive(Clone, Debug, PartialEq, Eq)]
pub(super) struct RoomParticipant {
    pub(super) connection_id: String,
    pub(super) user_id: Option<i64>,
    pub(super) device_role: String,
    pub(super) device_label: Option<String>,
    pub(super) user_label: Option<String>,
    pub(super) is_active_audio_source: bool,
}

#[derive(Clone, Debug, PartialEq)]
pub(super) struct Committed {
    pub(super) segment_id: String,
    pub(super) text: String,
    /// The side label (`Мы`, `Оппонент`, ...).
    pub(super) side: Option<String>,
    /// Seconds from the start of this connection's audio.
    pub(super) start_time: f64,
    pub(super) end_time: f64,
    pub(super) language: Option<String>,
    pub(super) translation: Option<String>,
    pub(super) speaker: Option<String>,
}

fn text_of(value: &Value, key: &str) -> Option<String> {
    value
        .get(key)
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(str::to_string)
}

fn seconds_of(value: &Value, key: &str) -> f64 {
    value
        .get(key)
        .and_then(Value::as_f64)
        .filter(|s| s.is_finite())
        .unwrap_or(0.0)
}

/// One entry of `room_participants`; `None` for a broken one (no connection id).
fn participant_of(value: &Value) -> Option<RoomParticipant> {
    Some(RoomParticipant {
        connection_id: text_of(value, "connection_id")?,
        user_id: value.get("user_id").and_then(Value::as_i64),
        device_role: text_of(value, "device_role").unwrap_or_else(|| "participant".to_string()),
        device_label: text_of(value, "device_label"),
        user_label: text_of(value, "user_label"),
        is_active_audio_source: value
            .get("is_active_audio_source")
            .and_then(Value::as_bool)
            .unwrap_or(false),
    })
}

/// Reads a text frame. `None`: not JSON or no `type` (ignored by the caller).
pub(super) fn parse_server_message(raw: &str) -> Option<ServerEvent> {
    let value: Value = serde_json::from_str(raw).ok()?;
    let kind = value.get("type")?.as_str()?;
    Some(match kind {
        "transcript" => {
            if value.get("is_partial").and_then(Value::as_bool) == Some(true) {
                ServerEvent::Partial {
                    text: text_of(&value, "text").unwrap_or_default(),
                }
            } else {
                // The final phrase comes as `committed_transcript`.
                ServerEvent::Other
            }
        }
        "committed_transcript" => match (text_of(&value, "segment_id"), text_of(&value, "text")) {
            (Some(segment_id), Some(text)) => ServerEvent::Committed(Committed {
                segment_id,
                text,
                side: text_of(&value, "speaker"),
                start_time: seconds_of(&value, "start_time"),
                end_time: seconds_of(&value, "end_time"),
                language: text_of(&value, "language"),
                translation: text_of(&value, "translation"),
                speaker: text_of(&value, "diarized_speaker"),
            }),
            _ => ServerEvent::Other,
        },
        "segment_translation" => match (text_of(&value, "segment_id"), text_of(&value, "text")) {
            (Some(segment_id), Some(text)) => ServerEvent::Translation { segment_id, text },
            _ => ServerEvent::Other,
        },
        "segment_speaker" => match (text_of(&value, "segment_id"), text_of(&value, "speaker")) {
            (Some(segment_id), Some(speaker)) => ServerEvent::Speaker {
                segment_id,
                speaker,
            },
            _ => ServerEvent::Other,
        },
        "audio_source_busy" => ServerEvent::Refused {
            reason: "Звук уже пишет другое устройство".to_string(),
        },
        "record_permission_denied" => ServerEvent::Refused {
            reason: text_of(&value, "message")
                .unwrap_or_else(|| "Нет права записи в этой встрече".to_string()),
        },
        "error" => {
            let code = text_of(&value, "code");
            let message = text_of(&value, "message").unwrap_or_default();
            if code.as_deref() == Some("audio_not_supported") {
                ServerEvent::Refused {
                    reason: "Сервер пока не принимает звук приложения".to_string(),
                }
            } else {
                ServerEvent::Error { message }
            }
        }
        "recording_status" => match value.get("recording").and_then(Value::as_bool) {
            Some(recording) => ServerEvent::Recording {
                recording,
                source: text_of(&value, "active_audio_source"),
            },
            None => ServerEvent::Other,
        },
        "room_joined" => match text_of(&value, "connection_id") {
            Some(connection_id) => ServerEvent::Joined { connection_id },
            None => ServerEvent::Other,
        },
        "segment_side_hint" => match (
            text_of(&value, "segment_key").or_else(|| text_of(&value, "segment_id")),
            text_of(&value, "side"),
        ) {
            (Some(segment_id), Some(side)) if side == "self" || side == "opponent" => {
                ServerEvent::SideHint { segment_id, side }
            }
            _ => ServerEvent::Other,
        },
        "room_participants" => match value.get("participants").and_then(Value::as_array) {
            Some(items) => {
                ServerEvent::Participants(items.iter().filter_map(participant_of).collect())
            }
            None => ServerEvent::Other,
        },
        "pong" => ServerEvent::Pong,
        _ => ServerEvent::Other,
    })
}

/// The channel of a hinted side (`self` is the microphone).
pub(super) fn channel_for_hint(side: &str) -> &'static str {
    if side == "self" {
        "mic"
    } else {
        "system"
    }
}

/// `mic`, `system` or `mixed` for the side label of a phrase. An in-person
/// meeting has one microphone for everybody.
pub(super) fn channel_for_side(side: Option<&str>, two_channels: bool) -> &'static str {
    if !two_channels {
        return "mixed";
    }
    match side {
        Some(SIDE_SELF) => "mic",
        Some(SIDE_OPPONENT) => "system",
        _ => "mixed",
    }
}

pub(super) fn start_listening() -> String {
    json!({ "type": "start_listening" }).to_string()
}

pub(super) fn stop_listening() -> String {
    json!({ "type": "stop_listening" }).to_string()
}

pub(super) fn ping(ts_ms: u64) -> String {
    json!({ "type": "ping", "ts": ts_ms }).to_string()
}

/// Levels of the two sources, as linear amplitudes 0..1.
#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub(super) struct SourceLevels {
    pub(super) mic_rms: f32,
    pub(super) mic_peak: f32,
    pub(super) system_rms: f32,
    pub(super) system_peak: f32,
}

pub(super) fn audio_source_levels(levels: SourceLevels, seq: u64, ts_ms: u64) -> String {
    json!({
        "type": "audio_source_levels",
        "mic_rms": levels.mic_rms,
        "mic_peak": levels.mic_peak,
        "system_rms": levels.system_rms,
        "system_peak": levels.system_peak,
        "system_active": true,
        "seq": seq,
        "client_ts_ms": ts_ms,
    })
    .to_string()
}

/// s16le bytes of the samples, as the binary frames carry them.
pub(super) fn pcm_bytes(samples: &[i16]) -> Vec<u8> {
    samples.iter().flat_map(|s| s.to_le_bytes()).collect()
}

/// A close code that no reconnection can fix, with the words for the user.
pub(super) fn fatal_close(code: u16) -> Option<&'static str> {
    match code {
        CLOSE_UNAUTHORIZED => Some("Сессия на сервере завершена: войдите заново"),
        CLOSE_NOT_FOUND => Some("Встреча не найдена на сервере"),
        CLOSE_MEETING_CLOSED => Some("Встреча уже закрыта на сервере"),
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn partial_and_committed_phrases_are_read() {
        assert_eq!(
            parse_server_message(
                r#"{"type":"transcript","speaker":"Мы","text":" добрый ","timestamp":"10:00:00","is_partial":true}"#
            ),
            Some(ServerEvent::Partial {
                text: "добрый".to_string()
            })
        );
        // A final `transcript` is the committed one's duplicate.
        assert_eq!(
            parse_server_message(r#"{"type":"transcript","text":"x","is_partial":false}"#),
            Some(ServerEvent::Other)
        );
        let committed = parse_server_message(
            r#"{"type":"committed_transcript","segment_id":"a1","segment_key":"a1",
                "speaker":"Оппонент","text":"Merhaba","words":[],"start_time":1.5,"end_time":3,
                "language":"tr","translation":"Здравствуйте","diarized_speaker":"s1_speaker_1",
                "confidence":null}"#,
        );
        assert_eq!(
            committed,
            Some(ServerEvent::Committed(Committed {
                segment_id: "a1".to_string(),
                text: "Merhaba".to_string(),
                side: Some("Оппонент".to_string()),
                start_time: 1.5,
                end_time: 3.0,
                language: Some("tr".to_string()),
                translation: Some("Здравствуйте".to_string()),
                speaker: Some("s1_speaker_1".to_string()),
            }))
        );
    }

    #[test]
    fn a_committed_phrase_without_language_or_speaker_is_still_read() {
        let Some(ServerEvent::Committed(c)) = parse_server_message(
            r#"{"type":"committed_transcript","segment_id":"b","text":"да","language":null}"#,
        ) else {
            panic!("committed expected");
        };
        assert_eq!(c.language, None);
        assert_eq!(c.speaker, None);
        assert_eq!(c.start_time, 0.0);
    }

    #[test]
    fn translation_and_speaker_updates_are_read() {
        assert_eq!(
            parse_server_message(r#"{"type":"segment_translation","segment_id":"a1","text":"Да"}"#),
            Some(ServerEvent::Translation {
                segment_id: "a1".to_string(),
                text: "Да".to_string()
            })
        );
        assert_eq!(
            parse_server_message(
                r#"{"type":"segment_speaker","segment_id":"a1","speaker":"s1_speaker_0"}"#
            ),
            Some(ServerEvent::Speaker {
                segment_id: "a1".to_string(),
                speaker: "s1_speaker_0".to_string()
            })
        );
        // Without an id nothing can be updated.
        assert_eq!(
            parse_server_message(r#"{"type":"segment_translation","text":"Да"}"#),
            Some(ServerEvent::Other)
        );
    }

    #[test]
    fn refusals_pong_errors_and_noise() {
        assert!(matches!(
            parse_server_message(r#"{"type":"error","code":"audio_not_supported","message":"x"}"#),
            Some(ServerEvent::Refused { .. })
        ));
        assert!(matches!(
            parse_server_message(r#"{"type":"audio_source_busy","active_audio_source":"c"}"#),
            Some(ServerEvent::Refused { .. })
        ));
        assert!(matches!(
            parse_server_message(r#"{"type":"record_permission_denied","message":"нельзя"}"#),
            Some(ServerEvent::Refused { reason }) if reason == "нельзя"
        ));
        assert_eq!(
            parse_server_message(r#"{"type":"error","message":"STT ошибка"}"#),
            Some(ServerEvent::Error {
                message: "STT ошибка".to_string()
            })
        );
        assert_eq!(
            parse_server_message(
                r#"{"type":"recording_status","recording":true,"active_audio_source":"c"}"#
            ),
            Some(ServerEvent::Recording {
                recording: true,
                source: Some("c".to_string())
            })
        );
        assert_eq!(
            parse_server_message(r#"{"type":"room_joined","connection_id":"c1","meeting_id":3}"#),
            Some(ServerEvent::Joined {
                connection_id: "c1".to_string()
            })
        );
        assert_eq!(
            parse_server_message(
                r#"{"type":"segment_side_hint","segment_key":"a1","side":"opponent","confidence":0.9}"#
            ),
            Some(ServerEvent::SideHint {
                segment_id: "a1".to_string(),
                side: "opponent".to_string()
            })
        );
        // No confident side: nothing to apply.
        assert_eq!(
            parse_server_message(r#"{"type":"segment_side_hint","segment_key":"a1","side":null}"#),
            Some(ServerEvent::Other)
        );
        assert_eq!(
            parse_server_message(r#"{"type":"recording_status","recording":false}"#),
            Some(ServerEvent::Recording {
                recording: false,
                source: None
            })
        );
        assert_eq!(
            parse_server_message(r#"{"type":"pong","ts":1}"#),
            Some(ServerEvent::Pong)
        );
        assert_eq!(
            parse_server_message(r#"{"type":"room_participants","participants":[]}"#),
            Some(ServerEvent::Participants(vec![]))
        );
        // Without the list there is nothing to show.
        assert_eq!(
            parse_server_message(r#"{"type":"room_participants"}"#),
            Some(ServerEvent::Other)
        );
        assert_eq!(parse_server_message("not json"), None);
        assert_eq!(parse_server_message(r#"{"no":"type"}"#), None);
    }

    #[test]
    fn room_participants_are_read_and_broken_ones_skipped() {
        let raw = r#"{"type":"room_participants","meeting_id":3,"active_audio_source":"c1",
            "participants":[
              {"connection_id":"c1","user_id":7,"device_role":"desktop","device_label":"Windows · App",
               "user_label":"Иван","can_send_audio":true,"is_active_audio_source":true,"is_helper":false},
              {"connection_id":"c2","user_id":null,"device_role":"phone","device_label":null,"user_label":null},
              {"user_id":8,"device_role":"desktop"},
              {"connection_id":"  ","device_role":"desktop"},
              "junk",
              42,
              {"connection_id":"c3","user_id":"x","device_role":5}
            ]}"#;
        let Some(ServerEvent::Participants(list)) = parse_server_message(raw) else {
            panic!("not a participants event");
        };
        assert_eq!(list.len(), 3);
        assert_eq!(
            list[0],
            RoomParticipant {
                connection_id: "c1".to_string(),
                user_id: Some(7),
                device_role: "desktop".to_string(),
                device_label: Some("Windows · App".to_string()),
                user_label: Some("Иван".to_string()),
                is_active_audio_source: true,
            }
        );
        assert_eq!(list[1].user_id, None);
        assert_eq!(list[1].device_label, None);
        assert!(!list[1].is_active_audio_source);
        // Wrong types fall back to the defaults instead of dropping the entry.
        assert_eq!(list[2].user_id, None);
        assert_eq!(list[2].device_role, "participant");
        // The list itself of the wrong type: nothing to show.
        assert_eq!(
            parse_server_message(r#"{"type":"room_participants","participants":"x"}"#),
            Some(ServerEvent::Other)
        );
    }

    #[test]
    fn side_labels_map_to_channels() {
        assert_eq!(channel_for_side(Some("Мы"), true), "mic");
        assert_eq!(channel_for_side(Some("Оппонент"), true), "system");
        assert_eq!(channel_for_side(Some("Спикер 1"), true), "mixed");
        assert_eq!(channel_for_side(None, true), "mixed");
        assert_eq!(channel_for_side(Some("Мы"), false), "mixed");
    }

    #[test]
    fn client_frames_have_the_sites_shape() {
        let levels: Value = serde_json::from_str(&audio_source_levels(
            SourceLevels {
                mic_rms: 0.25,
                mic_peak: 0.5,
                system_rms: 0.0,
                system_peak: 0.0,
            },
            7,
            1000,
        ))
        .unwrap();
        assert_eq!(levels["type"], "audio_source_levels");
        assert_eq!(levels["mic_rms"], 0.25);
        assert_eq!(levels["system_active"], true);
        assert_eq!(levels["seq"], 7);
        assert_eq!(levels["client_ts_ms"], 1000);
        assert_eq!(start_listening(), r#"{"type":"start_listening"}"#);
        assert_eq!(stop_listening(), r#"{"type":"stop_listening"}"#);
        assert_eq!(pcm_bytes(&[1, -2]), vec![1, 0, 0xFE, 0xFF]);
    }

    #[test]
    fn only_final_close_codes_stop_the_attempts() {
        assert!(fatal_close(CLOSE_UNAUTHORIZED).is_some());
        assert!(fatal_close(CLOSE_NOT_FOUND).is_some());
        assert!(fatal_close(CLOSE_MEETING_CLOSED).is_some());
        assert!(fatal_close(1006).is_none());
        assert!(fatal_close(1000).is_none());
    }
}
