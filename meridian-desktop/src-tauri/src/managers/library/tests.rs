//! The library against a throwaway HTTP server on localhost: the cache, the
//! offline fallbacks, and the upgrade of an existing database.

use std::sync::Arc;

use super::test_support::{item, local_meeting, STARTED};
use super::{library_get, meeting_ask, meeting_view_get};
use crate::managers::meeting::MeetingDb;
use crate::managers::sync::tests::{err, ok, start_mock, Mock, Req, Reply};
use crate::managers::sync::{ApiClient, ApiError};

const TOKEN: &str = "tok-library-1";

const LIBRARY_JSON: &str = r#"[
  {"meeting_id":7,"title":"Встреча по кровле","meeting_topic":"Кровля","started_at":"2026-03-02T09:00:00",
   "ended_at":null,"customer_id":3,"customer_name":"СтройИнвест","object_id":5,"object_name":"Корпус 1",
   "finalization_status":"done","protocol_ready":true,"micro_summary":"Сроки","client_uuid":null,"source":"web"},
  {"meeting_id":8,"title":null,"meeting_topic":null,"started_at":"2026-03-03T09:00:00","ended_at":null,
   "customer_id":null,"customer_name":null,"object_id":null,"object_name":null,
   "finalization_status":"not_started","protocol_ready":false,"micro_summary":null,
   "client_uuid":"uuid-8","source":"desktop"}
]"#;

const PROJECTS_JSON: &str = r#"[{"id":3,"name":"СтройИнвест","objects":[{"id":5,"name":"Корпус 1","address":null}]}]"#;

const VIEW_JSON: &str = r###"{"meeting_id":7,"title":"Встреча по кровле","meeting_topic":"Кровля",
  "started_at":"2026-03-02T09:00:00","ended_at":null,"customer_id":3,"customer_name":"СтройИнвест",
  "object_id":5,"object_name":"Корпус 1","finalization_status":"done","protocol_ready":true,
  "micro_summary":"Сроки","client_uuid":null,"source":"web",
  "protocol_markdown":"## Протокол\nУтеплитель заказан",
  "segments":[{"text":"Привет","speaker_label":null,"start_time":0.0,"end_time":1.5,"wall_clock":"2026-03-02T09:00:00"},
              {"text":"Нужна кровля","speaker_label":"Иван","start_time":null,"end_time":null,"wall_clock":null}],
  "documents":[{"filename":"dogovor.pdf","doc_type":"contract","doc_type_label":"Договор","page_count":4}]}"###;

fn server(request: &Req) -> Reply {
    match (request.method.as_str(), request.path.as_str()) {
        ("GET", "/api/desktop/library?limit=500") => ok(LIBRARY_JSON),
        ("GET", "/api/desktop/projects") => ok(PROJECTS_JSON),
        ("GET", "/api/desktop/meetings/7/view") => ok(VIEW_JSON),
        ("POST", "/api/desktop/meetings/7/ask") => ok(
            r#"{"answer":"Срок — май","sources":[{"kind":"document","title":"Договор","ref":"p. 3"},
                {"kind":"note","title":"Заметка","ref":null}]}"#,
        ),
        _ => err(404, "Встреча не найдена"),
    }
}

/// An address nobody listens on: "no connection".
async fn dead_client() -> ApiClient {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let url = format!("http://{}", listener.local_addr().unwrap());
    drop(listener);
    ApiClient::new(&url, Some(TOKEN))
}

fn client(mock: &Mock) -> ApiClient {
    ApiClient::new(&mock.url, Some(TOKEN))
}

fn memory_db() -> Arc<MeetingDb> {
    Arc::new(MeetingDb::open_in_memory().unwrap())
}

#[tokio::test]
async fn refresh_fills_the_cache_and_the_index() {
    let mock = start_mock(server).await;
    let db = memory_db();

    let snapshot = library_get(&db, Some(&client(&mock)), true).await.unwrap();
    assert!(snapshot.signed_in && !snapshot.offline);
    // Newest first.
    let ids: Vec<i64> = snapshot.items.iter().map(|i| i.meeting_id).collect();
    assert_eq!(ids, [8, 7]);
    assert_eq!(snapshot.items[1].customer_name.as_deref(), Some("СтройИнвест"));
    assert_eq!(snapshot.items[0].title, None);
    assert_eq!(snapshot.projects[0].objects[0].name, "Корпус 1");
    assert!(snapshot.fetched_at.is_some());

    let requests = mock.all();
    assert_eq!(requests.len(), 2);
    let bearer = format!("Bearer {TOKEN}");
    assert!(requests
        .iter()
        .all(|r| r.headers.get("authorization") == Some(&bearer)));

    // The summary is searchable.
    assert_eq!(db.search_meetings("корпус", None).unwrap()[0].id, "7");
}

#[tokio::test]
async fn offline_refresh_returns_the_cache() {
    let mock = start_mock(server).await;
    let db = memory_db();
    library_get(&db, Some(&client(&mock)), true).await.unwrap();

    let snapshot = library_get(&db, Some(&dead_client().await), true)
        .await
        .unwrap();
    assert!(snapshot.offline && snapshot.signed_in);
    assert_eq!(snapshot.items.len(), 2);
    assert_eq!(snapshot.projects.len(), 1);

    // Without a refresh the cache is returned as it is, and the server is not asked.
    let before = mock.count();
    let snapshot = library_get(&db, Some(&client(&mock)), false).await.unwrap();
    assert!(!snapshot.offline);
    assert_eq!(snapshot.items.len(), 2);
    assert_eq!(mock.count(), before);
}

#[tokio::test]
async fn offline_with_an_empty_cache_is_empty_not_an_error() {
    let db = memory_db();
    let snapshot = library_get(&db, Some(&dead_client().await), true)
        .await
        .unwrap();
    assert!(snapshot.offline && snapshot.signed_in);
    assert!(snapshot.items.is_empty() && snapshot.projects.is_empty());
    assert!(snapshot.fetched_at.is_none());
}

#[tokio::test]
async fn not_signed_in_is_empty_without_an_error() {
    let mock = start_mock(server).await;
    let db = memory_db();
    library_get(&db, Some(&client(&mock)), true).await.unwrap();

    let snapshot = library_get(&db, None, true).await.unwrap();
    assert!(!snapshot.signed_in && !snapshot.offline);
    assert!(snapshot.items.is_empty() && snapshot.projects.is_empty());
}

#[tokio::test]
async fn a_refused_token_is_an_error_to_sign_out_on() {
    let mock = start_mock(|_| err(401, "Недействительный токен")).await;
    let db = memory_db();
    let result = library_get(&db, Some(&client(&mock)), true).await;
    assert_eq!(result.unwrap_err(), ApiError::Unauthorized);
}

#[tokio::test]
async fn partial_failure_keeps_what_arrived() {
    let mock = start_mock(|r| match r.path.as_str() {
        "/api/desktop/projects" => err(500, "сбой"),
        _ => server(r),
    })
    .await;
    let db = memory_db();
    let snapshot = library_get(&db, Some(&client(&mock)), true).await.unwrap();
    assert!(snapshot.offline);
    assert_eq!(snapshot.items.len(), 2);
    assert!(snapshot.projects.is_empty());
}

#[tokio::test]
async fn view_is_cached_and_served_offline() {
    let mock = start_mock(server).await;
    let db = memory_db();

    let fresh = meeting_view_get(&db, Some(&client(&mock)), 7).await.unwrap();
    assert!(!fresh.from_cache);
    assert_eq!(fresh.view.segments.len(), 2);
    assert_eq!(fresh.view.segments[1].start_time, None);
    assert_eq!(fresh.view.documents[0].doc_type_label.as_deref(), Some("Договор"));
    assert_eq!(fresh.view.item.customer_name.as_deref(), Some("СтройИнвест"));

    let cached = meeting_view_get(&db, Some(&dead_client().await), 7)
        .await
        .unwrap();
    assert!(cached.from_cache);
    assert_eq!(cached.view, fresh.view);

    // The protocol text of an opened meeting is searchable.
    assert_eq!(db.search_meetings("утеплитель", None).unwrap()[0].id, "7");
}

#[tokio::test]
async fn view_errors_are_explained() {
    let mock = start_mock(server).await;
    let db = memory_db();

    let never_opened = meeting_view_get(&db, Some(&dead_client().await), 7)
        .await
        .unwrap_err();
    assert_eq!(
        never_opened.to_string(),
        "Нет сети, встреча ещё не открывалась на этом компьютере"
    );

    // The server answered "no": that is not a reason to show an old copy.
    meeting_view_get(&db, Some(&client(&mock)), 7).await.unwrap();
    let missing = meeting_view_get(&db, Some(&client(&mock)), 99)
        .await
        .unwrap_err();
    assert!(matches!(missing, ApiError::Rejected { status: 404, .. }), "{missing:?}");

    assert!(meeting_view_get(&db, None, 7).await.is_err());
}

#[tokio::test]
async fn ask_returns_answer_and_sources() {
    let mock = start_mock(server).await;
    let answer = meeting_ask(Some(&client(&mock)), 7, "  Какой срок?  ")
        .await
        .unwrap();
    assert_eq!(answer.answer, "Срок — май");
    assert_eq!(answer.sources.len(), 2);
    assert_eq!(answer.sources[0].reference.as_deref(), Some("p. 3"));
    assert_eq!(answer.sources[1].reference, None);
    assert_eq!(mock.all()[0].json()["question"], "Какой срок?");
}

#[tokio::test]
async fn ask_needs_a_connection() {
    let offline = meeting_ask(Some(&dead_client().await), 7, "Что решили?")
        .await
        .unwrap_err();
    assert_eq!(
        offline.to_string(),
        "Спросить можно только при подключении к сети"
    );
    assert!(meeting_ask(None, 7, "Что решили?").await.is_err());
    let mock = start_mock(server).await;
    assert!(meeting_ask(Some(&client(&mock)), 7, "   ").await.is_err());
    assert_eq!(mock.count(), 0);

    let refused = start_mock(|_| err(401, "x")).await;
    assert_eq!(
        meeting_ask(Some(&client(&refused)), 7, "Вопрос").await.unwrap_err(),
        ApiError::Unauthorized
    );
}

#[test]
fn cache_roundtrip_and_clear() {
    let db = memory_db();
    local_meeting(&db, "mine", "Моя встреча", &["про кровлю"], &[]);
    db.index_local_meeting("mine").unwrap();
    db.put_library(&[item(1, "А", None), item(2, "Б", Some("mine"))])
        .unwrap();
    db.put_projects(&[]).unwrap();
    let (items, at) = db.get_library().unwrap();
    assert_eq!(items.len(), 2);
    assert!(at.is_some());
    assert!(db.get_projects().unwrap().1.is_some());

    db.clear_server_cache().unwrap();
    assert!(db.get_library().unwrap().0.is_empty());
    assert!(db.get_projects().unwrap().1.is_none());
    // The local meetings stay in the search.
    assert_eq!(db.search_meetings("кровлю", None).unwrap()[0].id, "mine");
}

#[test]
fn old_database_is_upgraded_in_place() {
    // A database of the previous version (2): meetings with their segments and no library tables.
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("meetings.db");
    {
        let conn = rusqlite::Connection::open(&path).unwrap();
        conn.execute_batch(&format!(
            "CREATE TABLE meetings (
                id TEXT PRIMARY KEY, title TEXT NOT NULL, capture_mode TEXT NOT NULL,
                started_at TEXT NOT NULL, ended_at TEXT, status TEXT NOT NULL,
                duration_seconds REAL NOT NULL DEFAULT 0, server_meeting_id INTEGER,
                sync_state TEXT NOT NULL DEFAULT 'pending', sync_error TEXT, synced_at TEXT,
                customer_id INTEGER, object_id INTEGER,
                audio_state TEXT NOT NULL DEFAULT 'pending', audio_done TEXT NOT NULL DEFAULT '');
             CREATE TABLE segments (
                id TEXT PRIMARY KEY,
                meeting_id TEXT NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
                channel TEXT NOT NULL, start_time REAL NOT NULL, end_time REAL NOT NULL,
                text TEXT NOT NULL, created_at TEXT NOT NULL, synced INTEGER NOT NULL DEFAULT 0);
             CREATE INDEX idx_segments_meeting ON segments(meeting_id, start_time);
             CREATE TABLE notes (
                id TEXT PRIMARY KEY,
                meeting_id TEXT NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
                at_seconds REAL NOT NULL, text TEXT NOT NULL, updated_at TEXT NOT NULL);
             CREATE INDEX idx_notes_meeting ON notes(meeting_id, at_seconds);
             INSERT INTO meetings (id, title, capture_mode, started_at, status, customer_id)
                VALUES ('old', 'Старая встреча', 'online', '{STARTED}', 'stopped', 4);
             INSERT INTO segments (id, meeting_id, channel, start_time, end_time, text, created_at)
                VALUES ('s1', 'old', 'mic', 0, 1, 'Залили фундамент', '{STARTED}');
             PRAGMA user_version = 2;"
        ))
        .unwrap();
    }
    let db = MeetingDb::open(&path).unwrap();
    let old = db.get_meeting("old").unwrap().unwrap();
    assert_eq!(old.customer_id, Some(4));
    assert_eq!((old.customer_name, old.object_name), (None, None));
    assert_eq!(db.list_segments("old").unwrap().len(), 1);
    let version: i32 = db
        .conn()
        .pragma_query_value(None, "user_version", |row| row.get(0))
        .unwrap();
    assert_eq!(version, 4);

    // The old meeting enters the index once.
    assert!(db.search_meetings("фундамент", None).unwrap().is_empty());
    assert_eq!(db.index_missing_local().unwrap(), 1);
    assert_eq!(db.search_meetings("фундамент", None).unwrap()[0].id, "old");

    // The project can be set and read back.
    assert!(db
        .set_meeting_project("old", Some(1), Some("Заказчик"), Some(2), Some("Объект"))
        .unwrap());
    let old = db.get_meeting("old").unwrap().unwrap();
    assert_eq!(old.customer_name.as_deref(), Some("Заказчик"));
    assert_eq!(old.object_id, Some(2));
    assert!(!db
        .set_meeting_project("nope", None, None, None, None)
        .unwrap());
    drop(db);

    // A second open changes nothing.
    let db = MeetingDb::open(&path).unwrap();
    assert_eq!(db.index_missing_local().unwrap(), 0);
}

#[test]
fn view_cached_by_an_older_version_reads_without_the_context() {
    let view: super::types::MeetingView = serde_json::from_str(VIEW_JSON).unwrap();
    assert!(view.negotiation_type.is_none());
    assert!(view.key_terms.is_none());
    assert!(view.opponent_weaknesses.is_none());
    assert!(view.app_notes.is_none());

    let mut json: serde_json::Value = serde_json::from_str(VIEW_JSON).unwrap();
    json["negotiation_type"] = "price".into();
    json["key_terms"] = "срок".into();
    json["opponent_weaknesses"] = serde_json::Value::Null;
    json["app_notes"] = "заметка".into();
    let view: super::types::MeetingView = serde_json::from_value(json).unwrap();
    assert_eq!(view.negotiation_type.as_deref(), Some("price"));
    assert_eq!(view.key_terms.as_deref(), Some("срок"));
    assert!(view.opponent_weaknesses.is_none());
    assert_eq!(view.app_notes.as_deref(), Some("заметка"));
}
