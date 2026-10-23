//! The sources calls of `/api/desktop`: upload a file to a meeting, list the
//! meeting's documents, include one into the context or leave it out.

use serde::{Deserialize, Serialize};
use specta::Type;

use super::{send, send_json, ApiClient, ApiError};

#[derive(Serialize)]
pub struct DocumentUploadBody<'a> {
    pub filename: &'a str,
    pub size: u64,
    pub mime_type: &'a str,
    pub meeting_id: i64,
}

#[derive(Deserialize)]
pub struct DocumentUploadResponse {
    pub document_id: i64,
    /// `None`: the file is on the server already.
    #[serde(default)]
    pub upload_url: Option<String>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize, Type)]
pub struct DocumentTag {
    pub key: String,
    pub label: String,
}

/// What the server read out of the document; every part may be missing.
#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize, Type)]
pub struct DocumentMeta {
    #[serde(default)]
    pub number: Option<String>,
    #[serde(default)]
    pub date: Option<String>,
    #[serde(default)]
    pub counterparty_name: Option<String>,
}

/// A document of a meeting as the server describes it. Type and tags are
/// found by the server and only shown here.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Type)]
pub struct ServerDocument {
    pub document_id: i64,
    pub name: Option<String>,
    pub status: Option<String>,
    pub doc_type: Option<String>,
    pub doc_type_label: Option<String>,
    pub doc_tags: Vec<DocumentTag>,
    pub doc_meta: Option<DocumentMeta>,
    /// `meeting`, `customer` or `object`.
    pub source: String,
    pub included: bool,
    pub page_count: Option<i64>,
}

/// The server's item, read loosely: the name may come as `original_name` or
/// `filename`, the id as `document_id` or `id`.
#[derive(Deserialize)]
struct RawDocument {
    #[serde(default)]
    document_id: Option<i64>,
    #[serde(default)]
    id: Option<i64>,
    #[serde(default)]
    original_name: Option<String>,
    #[serde(default)]
    filename: Option<String>,
    #[serde(default)]
    status: Option<String>,
    #[serde(default)]
    doc_type: Option<String>,
    #[serde(default)]
    doc_type_label: Option<String>,
    #[serde(default)]
    doc_tags: Option<Vec<RawTag>>,
    #[serde(default)]
    doc_meta: Option<DocumentMeta>,
    #[serde(default)]
    source: Option<String>,
    #[serde(default)]
    included: Option<bool>,
    #[serde(default)]
    page_count: Option<i64>,
}

#[derive(Deserialize)]
struct RawTag {
    #[serde(default)]
    key: Option<String>,
    #[serde(default)]
    label: Option<String>,
}

impl RawDocument {
    fn into_document(self) -> Option<ServerDocument> {
        // `id` of an inherited item may be negative: only `document_id` is a key.
        let document_id = self.document_id.or(self.id.filter(|id| *id > 0))?;
        let doc_tags = self
            .doc_tags
            .unwrap_or_default()
            .into_iter()
            .filter_map(|tag| {
                let key = tag.key.or_else(|| tag.label.clone())?;
                let label = tag.label.unwrap_or_else(|| key.clone());
                Some(DocumentTag { key, label })
            })
            .collect();
        Some(ServerDocument {
            document_id,
            name: self.original_name.or(self.filename),
            status: self.status,
            doc_type: self.doc_type,
            doc_type_label: self.doc_type_label,
            doc_tags,
            doc_meta: self.doc_meta,
            source: self.source.unwrap_or_else(|| "meeting".to_string()),
            included: self.included.unwrap_or(true),
            page_count: self.page_count,
        })
    }
}

/// The answer is a list, or an object holding it under `documents`/`items`.
pub(crate) fn parse_documents(value: serde_json::Value) -> Vec<ServerDocument> {
    let list = match value {
        serde_json::Value::Array(items) => items,
        serde_json::Value::Object(mut map) => {
            match map.remove("documents").or_else(|| map.remove("items")) {
                Some(serde_json::Value::Array(items)) => items,
                _ => Vec::new(),
            }
        }
        _ => Vec::new(),
    };
    list.into_iter()
        .filter_map(|item| serde_json::from_value::<RawDocument>(item).ok())
        .filter_map(RawDocument::into_document)
        .collect()
}

#[derive(Serialize)]
struct ConfirmBody {
    meeting_id: i64,
}

#[derive(Serialize)]
struct IncludedBody {
    included: bool,
}

impl ApiClient {
    pub async fn document_upload_session(
        &self,
        body: &DocumentUploadBody<'_>,
    ) -> Result<DocumentUploadResponse, ApiError> {
        let url = self.url("documents/upload-session");
        send_json(self.authorized(self.http.post(url).json(body))).await
    }

    /// Attaches the uploaded document to its meeting; the server takes it twice.
    pub async fn document_confirm(
        &self,
        document_id: i64,
        meeting_id: i64,
    ) -> Result<(), ApiError> {
        let url = self.url(&format!("documents/{document_id}/confirm"));
        let body = ConfirmBody { meeting_id };
        send(self.authorized(self.http.post(url).json(&body))).await?;
        Ok(())
    }

    pub async fn get_meeting_documents(
        &self,
        meeting_id: i64,
    ) -> Result<Vec<ServerDocument>, ApiError> {
        let url = self.url(&format!("meetings/{meeting_id}/documents"));
        let value: serde_json::Value = send_json(self.authorized(self.http.get(url))).await?;
        Ok(parse_documents(value))
    }

    pub async fn set_document_included(
        &self,
        meeting_id: i64,
        document_id: i64,
        included: bool,
    ) -> Result<(), ApiError> {
        let url = self.url(&format!("meetings/{meeting_id}/documents/{document_id}"));
        send(self.authorized(self.http.patch(url).json(&IncludedBody { included }))).await?;
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn reads_both_name_fields_and_tolerates_gaps() {
        let docs = parse_documents(serde_json::json!([
            {"document_id": 1, "original_name": "a.pdf", "status": "ready", "doc_type": "letter",
             "doc_type_label": "Письмо", "doc_tags": [{"key": "k", "label": "Метка"}],
             "doc_meta": {"number": "12", "date": null}, "source": "customer",
             "included": false, "page_count": 3},
            {"id": 2, "filename": "b.docx"},
            {"nothing": true}
        ]));
        assert_eq!(docs.len(), 2);
        assert_eq!(docs[0].name.as_deref(), Some("a.pdf"));
        assert_eq!(docs[0].doc_tags[0].label, "Метка");
        assert_eq!(docs[0].source, "customer");
        assert!(!docs[0].included);
        assert_eq!(docs[1].document_id, 2);
        assert_eq!(docs[1].name.as_deref(), Some("b.docx"));
        assert_eq!(docs[1].source, "meeting");
        assert!(docs[1].included);
        assert!(docs[1].doc_tags.is_empty());
    }

    #[test]
    fn accepts_a_wrapped_list() {
        let docs = parse_documents(serde_json::json!({"documents": [{"document_id": 5}]}));
        assert_eq!(docs.len(), 1);
        assert!(parse_documents(serde_json::json!({"x": 1})).is_empty());
    }
}
