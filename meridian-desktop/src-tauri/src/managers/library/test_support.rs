//! Fixtures of the library tests.

use super::types::{LibraryItem, LibrarySource, MeetingView, ViewSegment};
use crate::managers::meeting::{
    CaptureMode, MeetingDb, MeetingInfo, MeetingStatus, Note, Segment,
};

pub const STARTED: &str = "2026-03-01T10:00:00.000Z";

pub fn local_meeting(db: &MeetingDb, id: &str, title: &str, texts: &[&str], notes: &[&str]) {
    db.insert_meeting(&MeetingInfo {
        id: id.to_string(),
        title: title.to_string(),
        capture_mode: CaptureMode::Online,
        started_at: STARTED.to_string(),
        ended_at: Some("2026-03-01T11:00:00.000Z".to_string()),
        status: MeetingStatus::Stopped,
        duration_seconds: 3600.0,
        server_meeting_id: None,
        sync_state: "pending".to_string(),
        sync_error: None,
        synced_at: None,
        customer_id: None,
        object_id: None,
        customer_name: None,
        object_name: None,
        audio_state: "pending".to_string(),
        negotiation_type: None,
        key_terms: None,
        opponent_weaknesses: None,
        web_url: None,
    })
    .unwrap();
    for (n, text) in texts.iter().enumerate() {
        db.insert_segment(&Segment {
            id: format!("{id}-s{n}"),
            meeting_id: id.to_string(),
            channel: "mic".to_string(),
            start_time: n as f64,
            end_time: n as f64 + 1.0,
            text: text.to_string(),
            created_at: STARTED.to_string(),
            synced: false,
            voice: None,
        })
        .unwrap();
    }
    for (n, text) in notes.iter().enumerate() {
        db.upsert_note(&Note {
            id: format!("{id}-n{n}"),
            meeting_id: id.to_string(),
            at_seconds: n as f64,
            text: text.to_string(),
            updated_at: STARTED.to_string(),
        })
        .unwrap();
    }
}

pub fn item(meeting_id: i64, title: &str, client_uuid: Option<&str>) -> LibraryItem {
    LibraryItem {
        meeting_id,
        title: Some(title.to_string()),
        meeting_topic: None,
        started_at: Some(format!("2026-03-0{}T10:00:00", meeting_id % 9)),
        ended_at: None,
        customer_id: None,
        customer_name: None,
        object_id: None,
        object_name: None,
        finalization_status: "done".to_string(),
        protocol_ready: true,
        micro_summary: None,
        client_uuid: client_uuid.map(str::to_string),
        source: if client_uuid.is_some() {
            LibrarySource::Desktop
        } else {
            LibrarySource::Web
        },
    }
}

pub fn view(item: LibraryItem, protocol: &str, texts: &[&str]) -> MeetingView {
    MeetingView {
        item,
        protocol_markdown: Some(protocol.to_string()),
        negotiation_type: None,
        key_terms: None,
        opponent_weaknesses: None,
        app_notes: None,
        segments: texts
            .iter()
            .map(|text| ViewSegment {
                text: text.to_string(),
                speaker_label: None,
                start_time: Some(0.0),
                end_time: Some(1.0),
                wall_clock: None,
            })
            .collect(),
        documents: Vec::new(),
    }
}
