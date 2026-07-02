"""Этап 25: privacy data inventory — counts по категориям, safe refs, shared docs, без raw content."""

import json

from app.services.privacy_data_inventory import PrivacyDataInventoryService
from tests.privacy_test_utils import (  # noqa: F401 — commit_db фикстура
    commit_db, mk_user, mk_meeting, add_transcript, add_suggestion, add_document,
    add_meeting_audio, add_job, add_participant, add_context_source,
)

_SVC = PrivacyDataInventoryService()


async def test_inventory_counts_by_category(commit_db):
    owner = await mk_user(commit_db, "inv-owner@t.local")
    m = await mk_meeting(commit_db, owner)
    await add_transcript(commit_db, m)
    await add_suggestion(commit_db, m)
    await add_document(commit_db, owner, m)
    await add_meeting_audio(commit_db, owner, m)
    await add_job(commit_db, m)
    await commit_db.commit()

    rep = await _SVC.build_meeting_inventory(commit_db, m.id, owner)
    t = rep.totals
    assert t["transcript"] >= 1 and t["suggestion"] >= 1
    assert t["document"] >= 1 and t["audio"] >= 1 and t["job"] >= 1
    cats = {it.category for it in rep.items}
    assert {"meeting", "transcript", "audio", "suggestion", "summary", "speaker_identity",
            "document", "document_chunk", "job", "learning", "trace", "storage_object"} <= cats
    trace = next(it for it in rep.items if it.category == "trace")
    assert trace.deletable is False and trace.storage_backend == "external"


async def test_inventory_no_raw_content_and_safe_refs(commit_db):
    owner = await mk_user(commit_db, "inv2@t.local")
    m = await mk_meeting(commit_db, owner)
    await add_transcript(commit_db, m, text="СЕКРЕТНЫЙ_транскрипт цена")
    await add_document(commit_db, owner, m, s3_key="documents/secretkey999.pdf")
    await commit_db.commit()

    rep = await _SVC.build_meeting_inventory(commit_db, m.id, owner)
    blob = json.dumps(rep.model_dump(), ensure_ascii=False)
    assert "СЕКРЕТНЫЙ_транскрипт" not in blob
    assert "СекретныйДоговор.pdf" not in blob
    assert "documents/secretkey999.pdf" not in blob


async def test_inventory_shared_document_marked(commit_db):
    owner = await mk_user(commit_db, "inv3@t.local")
    m1 = await mk_meeting(commit_db, owner)
    m2 = await mk_meeting(commit_db, owner)
    await add_document(commit_db, owner, m1, shared_meeting=m2)
    await commit_db.commit()

    rep = await _SVC.build_meeting_inventory(commit_db, m1.id, owner)
    doc_item = next(it for it in rep.items if it.category == "document")
    assert doc_item.shared_reference is True and doc_item.deletable is False


async def test_inventory_includes_participant_context_snapshot(commit_db):
    # Этап 26: participant / meeting_context / saved_transcription / ai_settings_snapshot в totals
    owner = await mk_user(commit_db, "invc-o@t.local")
    other = await mk_user(commit_db, "invc-p@t.local")
    snapshot = '{"speaker_identity_hints": {"speaker_labels": {"SM_0": {"side": "our_side"}}}}'
    m = await mk_meeting(commit_db, owner, ai_settings_snapshot_json=snapshot)
    await add_participant(commit_db, m, owner, role="owner")
    await add_participant(commit_db, m, other)
    await add_context_source(commit_db, m)
    await commit_db.commit()

    rep = await _SVC.build_meeting_inventory(commit_db, m.id, owner)
    assert rep.totals.get("participant") == 2
    assert rep.totals.get("meeting_context") == 1
    assert rep.totals.get("ai_settings_snapshot") == 1
    cats = {it.category for it in rep.items}
    assert {"participant", "meeting_context", "saved_transcription", "ai_settings_snapshot"} <= cats
    # никаких raw значений hints (только count/наличие)
    blob = json.dumps(rep.model_dump(), ensure_ascii=False)
    assert "our_side" not in blob and "SM_0" not in blob and "speaker_labels" not in blob


async def test_inventory_meeting_not_found(commit_db):
    owner = await mk_user(commit_db, "inv4@t.local")
    rep = await _SVC.build_meeting_inventory(commit_db, 999999, owner)
    assert "meeting_not_found" in rep.blockers
