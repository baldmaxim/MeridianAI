"""Этап 25: privacy export manifest — секции, транскрипт-текст в payload но не в логах, без S3 key/URL."""

import json
import logging

from app.services.privacy_export_service import PrivacyExportService
from tests.privacy_test_utils import (  # noqa: F401
    commit_db, mk_user, mk_meeting, add_transcript, add_suggestion, add_document,
)

_SVC = PrivacyExportService()


async def test_export_manifest_sections(commit_db):
    owner = await mk_user(commit_db, "exp1@t.local")
    m = await mk_meeting(commit_db, owner, title="Переговоры")
    await add_transcript(commit_db, m, text="экспортируемый транскрипт")
    await add_suggestion(commit_db, m)
    await add_document(commit_db, owner, m)
    await commit_db.commit()

    man = await _SVC.build_export_manifest(commit_db, m.id, owner)
    assert {"meeting", "transcript", "suggestions", "summary", "speaker_roles", "documents", "audio"} <= set(man.sections)
    assert man.counts["transcript"] >= 1
    # транскрипт-текст ЕСТЬ в payload (это контент пользователя)
    assert any("экспортируемый транскрипт" in (s.get("text") or "") for s in man.data["transcript"])


async def test_export_no_s3key_filename_or_url(commit_db):
    owner = await mk_user(commit_db, "exp2@t.local")
    m = await mk_meeting(commit_db, owner)
    await add_document(commit_db, owner, m, s3_key="documents/leakkey123.pdf")
    await commit_db.commit()

    man = await _SVC.build_export_manifest(commit_db, m.id, owner)
    blob = json.dumps(man.model_dump(), ensure_ascii=False)
    assert "documents/leakkey123.pdf" not in blob   # нет raw S3 key
    assert "СекретныйДоговор.pdf" not in blob        # нет raw filename
    assert "http" not in blob                        # нет URL


async def test_export_transcript_text_not_logged(commit_db, caplog):
    owner = await mk_user(commit_db, "exp3@t.local")
    m = await mk_meeting(commit_db, owner)
    await add_transcript(commit_db, m, text="СЕКРЕТ_В_ЛОГАХ_НЕТ")
    await commit_db.commit()

    with caplog.at_level(logging.INFO, logger="meridian.privacy"):
        await _SVC.build_export_manifest(commit_db, m.id, owner)
    logtext = "\n".join(r.getMessage() for r in caplog.records)
    assert "[Privacy] event=privacy_export_created" in logtext
    assert "СЕКРЕТ_В_ЛОГАХ_НЕТ" not in logtext


async def test_export_include_flags_no_raw_bundling(commit_db):
    owner = await mk_user(commit_db, "exp4@t.local")
    m = await mk_meeting(commit_db, owner)
    await add_document(commit_db, owner, m)
    await commit_db.commit()

    man = await _SVC.build_export_manifest(commit_db, m.id, owner,
                                           include_documents=True, include_audio=True)
    assert man.includes_raw_documents is False and man.includes_raw_audio is False
    assert any("document" in w for w in man.warnings)
