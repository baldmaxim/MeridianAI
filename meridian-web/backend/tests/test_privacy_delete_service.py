"""Этап 25: privacy delete — dry-run план + confirmation token, гейты hard delete, shared skip,
local guard, S3 delete через fake storage, partial failure."""

import pytest
from sqlalchemy import func, select

from app.config import get_settings
from app.models.meeting import TranscriptSegmentRecord
from app.services import document_storage
from app.services.privacy_delete_service import (
    PrivacyDeleteService, verify_confirmation_token, _make_confirmation_token,
)
from tests.privacy_test_utils import (  # noqa: F401
    commit_db, mk_user, mk_meeting, add_transcript, add_suggestion, add_document, add_meeting_audio,
    add_participant,
)

_SVC = PrivacyDeleteService()
_FLAGS = {"include_documents": True, "include_audio": True, "include_meeting_record": False}


async def test_dry_run_plan_and_token(commit_db, monkeypatch):
    monkeypatch.setattr(get_settings(), "privacy_hard_delete_enabled", True)
    owner = await mk_user(commit_db, "del1@t.local")
    m = await mk_meeting(commit_db, owner)
    await add_transcript(commit_db, m)
    await add_suggestion(commit_db, m)
    await commit_db.commit()

    plan = await _SVC.build_delete_plan(commit_db, m.id, owner)
    assert plan.dry_run is True and plan.confirmation_token
    assert any(it.category == "transcript" and it.will_delete for it in plan.items)


async def test_hard_delete_disabled_blocks(commit_db, monkeypatch):
    monkeypatch.setattr(get_settings(), "privacy_hard_delete_enabled", False)
    owner = await mk_user(commit_db, "del2@t.local")
    m = await mk_meeting(commit_db, owner)
    await commit_db.commit()
    rep = await _SVC.execute_delete_plan(commit_db, m.id, owner, dry_run=False, confirmation_token="x")
    assert rep.executed is False and "hard_delete_disabled" in rep.blockers


async def test_confirmation_token_required_and_tampered(commit_db, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "privacy_hard_delete_enabled", True)
    monkeypatch.setattr(s, "privacy_delete_require_dry_run_first", True)
    owner = await mk_user(commit_db, "del3@t.local")
    m = await mk_meeting(commit_db, owner)
    await commit_db.commit()

    rep = await _SVC.execute_delete_plan(commit_db, m.id, owner, dry_run=False, confirmation_token=None)
    assert not rep.executed and "confirmation_token_missing" in rep.blockers
    rep2 = await _SVC.execute_delete_plan(commit_db, m.id, owner, dry_run=False,
                                          confirmation_token="aaa.bbb.ccc")
    assert not rep2.executed and any("token" in b for b in rep2.blockers)


async def test_confirmation_token_flag_mismatch(commit_db, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "privacy_hard_delete_enabled", True)
    monkeypatch.setattr(s, "privacy_delete_require_dry_run_first", True)
    owner = await mk_user(commit_db, "del4@t.local")
    m = await mk_meeting(commit_db, owner)
    await commit_db.commit()
    tok = _make_confirmation_token(m.id, owner.id, _FLAGS)  # include_meeting_record=False
    rep = await _SVC.execute_delete_plan(commit_db, m.id, owner, dry_run=False,
                                         confirmation_token=tok, include_meeting_record=True)
    assert not rep.executed and "confirmation_token_flags_mismatch" in rep.blockers


async def test_execute_deletes_content_shared_skipped_s3_called(commit_db, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "privacy_hard_delete_enabled", True)
    monkeypatch.setattr(s, "privacy_delete_require_dry_run_first", False)
    deleted = []

    async def _fake_del(key):
        deleted.append(key)
    monkeypatch.setattr(document_storage, "delete_object", _fake_del)

    owner = await mk_user(commit_db, "del5@t.local")
    m = await mk_meeting(commit_db, owner)
    m2 = await mk_meeting(commit_db, owner)
    await add_transcript(commit_db, m)
    await add_document(commit_db, owner, m, s3_key="documents/solo.pdf")
    await add_document(commit_db, owner, m, s3_key="documents/shared.pdf", shared_meeting=m2)
    await add_meeting_audio(commit_db, owner, m, key="meridian/1/meeting_audio/a.opus")
    await commit_db.commit()

    rep = await _SVC.execute_delete_plan(commit_db, m.id, owner, dry_run=False, **_FLAGS)
    assert rep.executed and not rep.blockers
    cnt = (await commit_db.execute(
        select(func.count()).select_from(TranscriptSegmentRecord)
        .where(TranscriptSegmentRecord.session_id == m.id))).scalar()
    assert cnt == 0
    assert "documents/solo.pdf" in deleted            # meeting-scoped doc → S3 deleted
    assert "documents/shared.pdf" not in deleted        # shared → skipped
    assert "meridian/1/meeting_audio/a.opus" in deleted  # meeting audio → S3 deleted


async def test_local_path_guard_skips_outside_dir(commit_db, monkeypatch):
    monkeypatch.setattr(get_settings(), "privacy_hard_delete_enabled", True)
    owner = await mk_user(commit_db, "del6@t.local")
    m = await mk_meeting(commit_db, owner, audio_path="/etc/passwd")
    await commit_db.commit()
    plan = await _SVC.build_delete_plan(commit_db, m.id, owner, include_audio=True)
    local_items = [it for it in plan.items if (it.safe_ref or "").startswith("local:")]
    assert local_items and local_items[0].action == "skip_unsupported"
    assert local_items[0].will_delete is False


async def test_execute_deletes_saved_transcription_local_file(commit_db, monkeypatch, tmp_path):
    s = get_settings()
    monkeypatch.setattr(s, "privacy_hard_delete_enabled", True)
    monkeypatch.setattr(s, "privacy_delete_require_dry_run_first", False)
    monkeypatch.setattr(s, "transcription_dir", str(tmp_path))
    f = tmp_path / "transcript.txt"
    f.write_text("секретный транскрипт на диске", encoding="utf-8")

    from app.models.meeting import SavedTranscription
    owner = await mk_user(commit_db, "del-st@t.local")
    m = await mk_meeting(commit_db, owner)
    commit_db.add(SavedTranscription(session_id=m.id, filename="transcript.txt", format="txt",
                                     file_path=str(f), segment_count=1))
    await commit_db.commit()

    rep = await _SVC.execute_delete_plan(commit_db, m.id, owner, dry_run=False, **_FLAGS)
    assert rep.executed
    assert not f.exists()  # локальный файл транскрипта удалён


async def test_execute_skips_saved_transcription_file_outside_allowed(commit_db, monkeypatch, tmp_path):
    # файл ВНЕ transcription_dir/upload_dir не трогаем (guard)
    s = get_settings()
    monkeypatch.setattr(s, "privacy_hard_delete_enabled", True)
    monkeypatch.setattr(s, "privacy_delete_require_dry_run_first", False)
    monkeypatch.setattr(s, "transcription_dir", str(tmp_path / "allowed"))
    (tmp_path / "allowed").mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("не трогать", encoding="utf-8")

    from app.models.meeting import SavedTranscription
    owner = await mk_user(commit_db, "del-st2@t.local")
    m = await mk_meeting(commit_db, owner)
    commit_db.add(SavedTranscription(session_id=m.id, filename="outside.txt", format="txt",
                                     file_path=str(outside), segment_count=1))
    await commit_db.commit()

    rep = await _SVC.execute_delete_plan(commit_db, m.id, owner, dry_run=False, **_FLAGS)
    assert rep.executed
    assert outside.exists()  # вне allowed dir — не удалён


async def test_delete_plan_participant_and_snapshot_categories(commit_db, monkeypatch):
    # Этап 26: категории delete-плана выровнены с inventory (participant, ai_settings_snapshot)
    monkeypatch.setattr(get_settings(), "privacy_hard_delete_enabled", True)
    owner = await mk_user(commit_db, "delp@t.local")
    m = await mk_meeting(commit_db, owner, ai_settings_snapshot_json='{"speaker_identity_hints": {}}')
    await add_participant(commit_db, m, owner, role="owner")
    await commit_db.commit()
    plan = await _SVC.build_delete_plan(commit_db, m.id, owner, include_meeting_record=True)
    cats = {it.category for it in plan.items}
    assert "participant" in cats and "ai_settings_snapshot" in cats


async def test_verify_confirmation_token_helper():
    tok = _make_confirmation_token(5, 7, _FLAGS)
    ok, _ = verify_confirmation_token(tok, 5, 7, _FLAGS)
    assert ok
    bad, reason = verify_confirmation_token(tok, 6, 7, _FLAGS)
    assert not bad and reason == "confirmation_token_meeting_mismatch"
    missing, r2 = verify_confirmation_token(None, 5, 7, _FLAGS)
    assert not missing and r2 == "confirmation_token_missing"
