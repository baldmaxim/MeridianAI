//! The full-text search: FTS5 in the bundled SQLite, Russian words, escaping,
//! keeping the index in step, and local/server de-duplication.

use super::test_support::{item, local_meeting, view};
use super::types::SearchKind;
use crate::managers::meeting::MeetingDb;

fn ids(db: &MeetingDb, query: &str) -> Vec<String> {
    db.search_meetings(query, None)
        .unwrap()
        .into_iter()
        .map(|hit| hit.id)
        .collect()
}

fn indexed_db() -> MeetingDb {
    let db = MeetingDb::open_in_memory().unwrap();
    local_meeting(
        &db,
        "a",
        "Совещание по ФУНДАМЕНТУ",
        &["Бетонирование плиты М300 перенесли", "Ёмкость для воды"],
        &["Согласовать смету"],
    );
    local_meeting(&db, "b", "Планёрка", &["Сказал \"готово\" вчера"], &[]);
    db.index_local_meeting("a").unwrap();
    db.index_local_meeting("b").unwrap();
    db
}

#[test]
fn fts5_is_compiled_in_and_russian_case_does_not_matter() {
    let db = indexed_db();
    assert_eq!(ids(&db, "фундамент"), ["a"]);
    assert_eq!(ids(&db, "ФУНДАМЕНТ"), ["a"]);
    assert_eq!(ids(&db, "бетонирование ПЛИТЫ"), ["a"]);
    assert_eq!(ids(&db, "СМЕТУ"), ["a"]);
    assert_eq!(ids(&db, "планёрка"), ["b"]);
    assert!(ids(&db, "кирпич").is_empty());
}

#[test]
fn prefix_search_and_snippet_markers() {
    let db = indexed_db();
    assert_eq!(ids(&db, "бетон"), ["a"]);
    let hits = db.search_meetings("бетон", None).unwrap();
    assert_eq!(hits[0].kind, SearchKind::Local);
    assert!(hits[0].snippet.contains("[Бетонирование]"), "{}", hits[0].snippet);
    assert_eq!(hits[0].started_at.as_deref(), Some("2026-03-01T10:00:00.000Z"));
    // Every word must be there (AND), in any order.
    assert_eq!(ids(&db, "плиты бетон"), ["a"]);
    assert!(ids(&db, "плиты кирпич").is_empty());
}

#[test]
fn user_input_is_escaped_for_match() {
    let db = indexed_db();
    for query in [
        "\"", "\"\"", "a\" OR \"b", "*", "--", "NEAR(", "title:", "(", ")", "фунд*", "x:y", "^",
        "AND", "OR NOT", "\\", "' OR 1=1 --", "фундамент\"",
    ] {
        db.search_meetings(query, None)
            .unwrap_or_else(|e| panic!("query {query:?} failed: {e:#}"));
    }
    // A quote inside the text is just a character.
    assert_eq!(ids(&db, "\"готово\""), ["b"]);
    assert_eq!(ids(&db, "готово"), ["b"]);
}

#[test]
fn short_or_empty_query_finds_nothing() {
    let db = indexed_db();
    for query in ["", " ", "б", " б ", "  "] {
        assert!(ids(&db, query).is_empty(), "{query:?}");
    }
    // Two characters are enough.
    assert_eq!(ids(&db, "пла"), ["b"]);
}

#[test]
fn limit_is_respected() {
    let db = MeetingDb::open_in_memory().unwrap();
    for n in 0..5 {
        let id = format!("m{n}");
        local_meeting(&db, &id, "Объект Север", &[], &[]);
        db.index_local_meeting(&id).unwrap();
    }
    assert_eq!(db.search_meetings("север", Some(3)).unwrap().len(), 3);
    assert_eq!(db.search_meetings("север", None).unwrap().len(), 5);
}

#[test]
fn index_follows_rename_notes_and_delete() {
    let db = indexed_db();

    db.rename_meeting("b", "Приёмка кровли").unwrap();
    db.index_local_meeting("b").unwrap();
    assert_eq!(ids(&db, "кровли"), ["b"]);
    assert!(ids(&db, "планёрка").is_empty());

    local_meeting(&db, "c", "Пустая", &[], &[]);
    db.index_local_meeting("c").unwrap();
    assert!(ids(&db, "арматура").is_empty());
    db.upsert_note(&crate::managers::meeting::Note {
        id: "c-n".into(),
        meeting_id: "c".into(),
        at_seconds: 1.0,
        text: "Заказать арматуру".into(),
        updated_at: "2026-03-01T10:00:00.000Z".into(),
    })
    .unwrap();
    db.index_local_meeting("c").unwrap();
    assert_eq!(ids(&db, "арматуру"), ["c"]);

    assert_eq!(db.note_meeting_id("c-n").unwrap().as_deref(), Some("c"));
    db.delete_note("c-n").unwrap();
    db.index_local_meeting("c").unwrap();
    assert!(ids(&db, "арматуру").is_empty());

    db.delete_meeting("a").unwrap();
    db.remove_local_index("a").unwrap();
    assert!(ids(&db, "фундамент").is_empty());
    // A meeting that is gone leaves the index through a re-index, too.
    db.index_local_meeting("a").unwrap();
}

#[test]
fn meetings_from_before_the_index_are_indexed_once() {
    let db = MeetingDb::open_in_memory().unwrap();
    local_meeting(&db, "old", "Старая встреча", &["про фундамент"], &[]);
    local_meeting(&db, "live", "Идёт запись", &["про фундамент"], &[]);
    db.mark_recording("live").unwrap();

    assert!(ids(&db, "фундамент").is_empty());
    assert_eq!(db.index_missing_local().unwrap(), 1);
    assert_eq!(ids(&db, "фундамент"), ["old"]);
    assert_eq!(db.index_missing_local().unwrap(), 0);
}

#[test]
fn server_meetings_are_searched_by_summary_and_by_opened_text() {
    let db = MeetingDb::open_in_memory().unwrap();
    let mut first = item(1, "Встреча с заказчиком", None);
    first.customer_name = Some("СтройИнвест".to_string());
    first.micro_summary = Some("Обсудили сроки поставки арматуры".to_string());
    let second = item(2, "Звонок", None);
    db.put_library(&[first.clone(), second.clone()]).unwrap();

    assert_eq!(ids(&db, "стройинвест"), ["1"]);
    assert_eq!(ids(&db, "арматуры"), ["1"]);
    assert!(ids(&db, "гарантийное").is_empty());
    let hit = &db.search_meetings("арматуры", None).unwrap()[0];
    assert_eq!(hit.kind, SearchKind::Server);
    assert_eq!(hit.title, "Встреча с заказчиком");
    assert_eq!(hit.started_at.as_deref(), Some("2026-03-01T10:00:00"));

    // Opened: the protocol and the phrases join the entry, and survive a refresh.
    db.put_view(&view(
        second.clone(),
        "## Протокол\nГарантийное обязательство 5 лет",
        &["реплика про опалубку"],
    ))
    .unwrap();
    assert_eq!(ids(&db, "гарантийное"), ["2"]);
    assert_eq!(ids(&db, "опалубку"), ["2"]);
    db.put_library(&[first, second]).unwrap();
    assert_eq!(ids(&db, "гарантийное"), ["2"]);

    // Gone from the site: gone from the search and from the cache.
    db.put_library(&[item(1, "Встреча с заказчиком", None)]).unwrap();
    assert!(ids(&db, "гарантийное").is_empty());
    assert!(db.get_view(2).unwrap().is_none());
}

#[test]
fn server_copy_of_a_local_meeting_is_not_repeated() {
    let db = MeetingDb::open_in_memory().unwrap();
    local_meeting(&db, "uuid-1", "Планёрка по кровле", &[], &[]);
    db.index_local_meeting("uuid-1").unwrap();
    db.put_library(&[
        item(10, "Планёрка по кровле", Some("uuid-1")),
        item(11, "Планёрка по фасаду", None),
        item(12, "Планёрка чужого приложения", Some("other-uuid")),
    ])
    .unwrap();

    let hits = db.search_meetings("планёрка", None).unwrap();
    let found: Vec<(SearchKind, &str)> = hits.iter().map(|h| (h.kind, h.id.as_str())).collect();
    assert_eq!(found.len(), 3, "{found:?}");
    assert!(found.contains(&(SearchKind::Local, "uuid-1")));
    assert!(found.contains(&(SearchKind::Server, "11")));
    assert!(found.contains(&(SearchKind::Server, "12")));
    assert!(!found.contains(&(SearchKind::Server, "10")));

    // The local one deleted: the server's copy takes its place.
    db.delete_meeting("uuid-1").unwrap();
    db.remove_local_index("uuid-1").unwrap();
    assert_eq!(ids(&db, "кровле"), ["10"]);
}

#[test]
fn yo_is_found_as_ye_but_short_i_is_not_i() {
    let db = indexed_db();
    // "Ёмкость" in a phrase, "Планёрка" in a title: found either way.
    for query in ["емкость", "ёмкость", "ЁМКОСТЬ", "планерка", "планёрка"] {
        assert_eq!(ids(&db, query).len(), 1, "{query}");
    }
    // The title is shown as it was written.
    assert_eq!(db.search_meetings("планерка", None).unwrap()[0].title, "Планёрка");
    local_meeting(&db, "k", "Май", &[], &[]);
    db.index_local_meeting("k").unwrap();
    assert_eq!(ids(&db, "май"), ["k"]);
    assert!(ids(&db, "маи").is_empty());
}
