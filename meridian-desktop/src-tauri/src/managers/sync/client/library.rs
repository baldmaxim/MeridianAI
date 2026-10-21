//! The library calls of `/api/desktop`: all meetings of the user, the projects,
//! one meeting for viewing, and "ask about a meeting".

use serde::Serialize;

use super::{send_json, ApiClient, ApiError};
use crate::managers::library::types::{
    AskAnswer, LibraryItem, MeetingView, ProjectCustomer,
};

#[derive(Serialize)]
struct AskBody<'a> {
    question: &'a str,
}

impl ApiClient {
    /// The newest `limit` meetings of the site.
    pub async fn get_library(&self, limit: u32) -> Result<Vec<LibraryItem>, ApiError> {
        let request = self
            .http
            .get(self.url("library"))
            .query(&[("limit", limit)]);
        send_json(self.authorized(request)).await
    }

    pub async fn get_projects(&self) -> Result<Vec<ProjectCustomer>, ApiError> {
        send_json(self.authorized(self.http.get(self.url("projects")))).await
    }

    pub async fn get_meeting_view(&self, meeting_id: i64) -> Result<MeetingView, ApiError> {
        let url = self.url(&format!("meetings/{meeting_id}/view"));
        send_json(self.authorized(self.http.get(url))).await
    }

    pub async fn ask(&self, meeting_id: i64, question: &str) -> Result<AskAnswer, ApiError> {
        let url = self.url(&format!("meetings/{meeting_id}/ask"));
        send_json(self.authorized(self.http.post(url).json(&AskBody { question }))).await
    }
}
