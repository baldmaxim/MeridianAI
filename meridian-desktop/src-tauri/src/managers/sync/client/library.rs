//! The library calls of `/api/desktop`: all meetings of the user, the projects,
//! one meeting for viewing, and "ask about a meeting".

use serde::{Deserialize, Serialize};

use super::{send, send_json, ApiClient, ApiError};
use crate::managers::library::types::{
    AskAnswer, AskMode, LibraryItem, MeetingView, OfferSubmission, ProjectCustomer,
};

#[derive(Serialize)]
struct AskBody<'a> {
    question: &'a str,
    mode: AskMode,
}

/// The answer of an audio request. The URL is a secret (a signed link): it is
/// never logged or stored, so the type has no `Debug`.
#[derive(Deserialize)]
struct AudioLink {
    url: String,
}

impl ApiClient {
    /// The link to the recording behind `path` (`meetings/{id}/audio`, ...);
    /// `None`: the server has no audio (404, or an old server without the call).
    pub(super) async fn get_audio_url(&self, path: &str) -> Result<Option<String>, ApiError> {
        match send_json::<AudioLink>(self.authorized(self.http.get(self.url(path)))).await {
            Ok(link) => Ok(Some(link.url).filter(|url| !url.trim().is_empty())),
            Err(ApiError::Rejected { status: 404, .. }) => Ok(None),
            Err(e) => Err(e),
        }
    }

    /// The link to the recording of a meeting.
    pub async fn get_meeting_audio_url(&self, meeting_id: i64) -> Result<Option<String>, ApiError> {
        self.get_audio_url(&format!("meetings/{meeting_id}/audio"))
            .await
    }

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

    /// The submissions of commercial offers of an object (newest first).
    pub async fn get_offer_submissions(
        &self,
        object_id: i64,
    ) -> Result<Vec<OfferSubmission>, ApiError> {
        let url = self.url(&format!("objects/{object_id}/offer-submissions"));
        send_json(self.authorized(self.http.get(url))).await
    }

    /// Which submission the meeting talks about: a value, or `None` for all
    /// documents of the object. Sent alone and with an explicit `null`: the
    /// other patches of the meeting must not touch the choice.
    pub async fn set_offer_submission(
        &self,
        meeting_id: i64,
        offer_submission: Option<&str>,
    ) -> Result<(), ApiError> {
        let url = self.url(&format!("meetings/{meeting_id}"));
        let body = serde_json::json!({ "offer_submission": offer_submission });
        send(self.authorized(self.http.patch(url).json(&body))).await?;
        Ok(())
    }

    pub async fn ask(
        &self,
        meeting_id: i64,
        question: &str,
        mode: AskMode,
    ) -> Result<AskAnswer, ApiError> {
        let url = self.url(&format!("meetings/{meeting_id}/ask"));
        send_json(self.authorized(self.http.post(url).json(&AskBody { question, mode }))).await
    }
}
