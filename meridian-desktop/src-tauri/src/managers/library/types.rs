//! Types of the server's library API (`/api/desktop/library`, `/projects`,
//! `/meetings/{id}/view`, `/meetings/{id}/ask`). They are read from the
//! server's JSON, stored as JSON in the offline cache and handed to the UI.

use serde::{Deserialize, Serialize};
use specta::Type;

/// Where the meeting came from: any link with this app, or the site itself.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize, Type)]
#[serde(rename_all = "lowercase")]
pub enum LibrarySource {
    Desktop,
    Web,
}

/// A meeting of the signed-in user, from the site (including the ones recorded here).
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize, Type)]
pub struct LibraryItem {
    pub meeting_id: i64,
    pub title: Option<String>,
    pub meeting_topic: Option<String>,
    pub started_at: Option<String>,
    pub ended_at: Option<String>,
    pub customer_id: Option<i64>,
    pub customer_name: Option<String>,
    pub object_id: Option<i64>,
    pub object_name: Option<String>,
    pub finalization_status: String,
    pub protocol_ready: bool,
    pub micro_summary: Option<String>,
    /// The local meeting's id when it was recorded in this app (by this user).
    pub client_uuid: Option<String>,
    pub source: LibrarySource,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize, Type)]
pub struct ViewSegment {
    pub text: String,
    pub speaker_label: Option<String>,
    pub start_time: Option<f64>,
    pub end_time: Option<f64>,
    pub wall_clock: Option<String>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize, Type)]
pub struct ViewDocument {
    pub filename: Option<String>,
    pub doc_type: Option<String>,
    pub doc_type_label: Option<String>,
    pub page_count: Option<i64>,
}

/// A meeting of the site as a whole: the item, the protocol, the phrases, the documents.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize, Type)]
pub struct MeetingView {
    #[serde(flatten)]
    pub item: LibraryItem,
    pub protocol_markdown: Option<String>,
    pub segments: Vec<ViewSegment>,
    pub documents: Vec<ViewDocument>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize, Type)]
pub struct ProjectObject {
    pub id: i64,
    pub name: String,
    pub address: Option<String>,
}

/// A customer with its objects (the site's reference book).
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize, Type)]
pub struct ProjectCustomer {
    pub id: i64,
    pub name: String,
    pub objects: Vec<ProjectObject>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize, Type)]
pub struct AskSource {
    /// `document`, `meeting`, `transcript`, `note` or `knowledge`.
    pub kind: String,
    pub title: String,
    #[serde(rename = "ref")]
    pub reference: Option<String>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize, Type)]
pub struct AskAnswer {
    pub answer: String,
    pub sources: Vec<AskSource>,
}

/// What the library screen shows: the cache, refreshed from the server when asked.
#[derive(Clone, Debug, Serialize, Type)]
pub struct LibrarySnapshot {
    pub items: Vec<LibraryItem>,
    pub projects: Vec<ProjectCustomer>,
    pub fetched_at: Option<String>,
    /// A refresh was asked for and the server was not reached: this is the cache.
    pub offline: bool,
    pub signed_in: bool,
}

/// A meeting of the site; `from_cache`: the server was not reached.
#[derive(Clone, Debug, Serialize, Type)]
pub struct MeetingViewResult {
    pub view: MeetingView,
    pub from_cache: bool,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Type)]
#[serde(rename_all = "snake_case")]
pub enum SearchKind {
    Local,
    Server,
}

#[derive(Clone, Debug, PartialEq, Serialize, Type)]
pub struct SearchHit {
    pub kind: SearchKind,
    /// The local meeting's uuid, or the server's meeting id as a string.
    pub id: String,
    pub title: String,
    /// The matched text; the found words are in `[` `]`.
    pub snippet: String,
    pub started_at: Option<String>,
}
