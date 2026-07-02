"""Speaker Identity Graph v1 (Этап 4): модели и helper-функции."""

from app.core.context.speaker_identity import (
    SpeakerIdentity,
    build_speaker_context_text,
    build_speaker_identity_map,
    make_stable_speaker_id,
    merge_speaker_identity,
    normalize_functional_role,
    normalize_side,
    normalize_speaker_label,
    side_to_legacy,
)


def test_normalize_speaker_label():
    assert normalize_speaker_label("  Speaker   1 ") == "Speaker 1"
    assert normalize_speaker_label(None) == "unknown_speaker"
    assert normalize_speaker_label("") == "unknown_speaker"


def test_make_stable_speaker_id_stable_and_independent_of_name():
    a = make_stable_speaker_id("Speaker 1")
    b = make_stable_speaker_id("Speaker 1")
    assert a == b
    assert make_stable_speaker_id("Speaker 1") != make_stable_speaker_id("Speaker 2")
    # одинаковая метка с разным регистром/пробелами → один id
    assert make_stable_speaker_id("speaker 1") == make_stable_speaker_id("  Speaker 1 ")


def test_normalize_side_our_side():
    for v in ("self", "us", "our", "we", "мы", "наша сторона", "our_side"):
        assert normalize_side(v) == "our_side"


def test_normalize_side_counterparty():
    for v in ("opponent", "customer", "client", "заказчик", "оппонент", "not_self", "не мы"):
        assert normalize_side(v) == "counterparty"


def test_normalize_side_third_party():
    for v in ("third_party", "observer", "external", "третья сторона", "наблюдатель"):
        assert normalize_side(v) == "third_party"


def test_normalize_side_unknown_fallback():
    assert normalize_side("blah") == "unknown"
    assert normalize_side(None) == "unknown"
    assert normalize_side("") == "unknown"


def test_side_to_legacy():
    assert side_to_legacy("our_side") == "self"
    assert side_to_legacy("counterparty") == "opponent"
    assert side_to_legacy("third_party") == "opponent"
    assert side_to_legacy("unknown") == "unknown"


def test_normalize_functional_role():
    assert normalize_functional_role("pm") == "project_manager"
    assert normalize_functional_role("заказчик") == "customer"
    assert normalize_functional_role("engineer") == "engineer"
    assert normalize_functional_role("nonsense") == "unknown"
    assert normalize_functional_role(None) == "unknown"


def test_confidence_clamp():
    assert SpeakerIdentity(raw_speaker_label="a", confidence=5).confidence == 1.0
    assert SpeakerIdentity(raw_speaker_label="a", confidence=-2).confidence == 0.0
    assert SpeakerIdentity(raw_speaker_label="a", confidence="bad").confidence == 0.0


def test_empty_label_becomes_unknown_speaker():
    assert SpeakerIdentity(raw_speaker_label="").raw_speaker_label == "unknown_speaker"
    assert SpeakerIdentity(raw_speaker_label="x").stable_id  # auto-filled


def test_merge_manual_correction_beats_legacy():
    legacy = SpeakerIdentity(raw_speaker_label="Speaker 1", side="counterparty",
                             confidence=0.85, source="legacy_role", evidence=["legacy_role:Speaker 1"])
    manual = SpeakerIdentity(raw_speaker_label="Speaker 1", side="our_side",
                             confidence=0.95, source="manual_correction",
                             evidence=["manual_correction:Speaker 1"])
    merged = merge_speaker_identity(legacy, manual)
    assert merged.side == "our_side"  # manual wins
    assert merged.source == "manual_correction"
    assert merged.confidence == 0.95
    # evidence объединён без дублей
    assert "legacy_role:Speaker 1" in merged.evidence
    assert "manual_correction:Speaker 1" in merged.evidence


def test_merge_manual_wins_even_with_lower_confidence():
    legacy = SpeakerIdentity(raw_speaker_label="S", side="counterparty", confidence=0.99, source="legacy_role")
    manual = SpeakerIdentity(raw_speaker_label="S", side="our_side", confidence=0.6, source="manual_correction")
    merged = merge_speaker_identity(legacy, manual)
    assert merged.side == "our_side"
    assert merged.source == "manual_correction"


def test_build_speaker_identity_map_aggregates():
    ids = [
        SpeakerIdentity(raw_speaker_label="S1", side="our_side", confidence=0.9, source="manual_correction"),
        SpeakerIdentity(raw_speaker_label="S2", side="counterparty", confidence=0.85, source="legacy_role"),
        SpeakerIdentity(raw_speaker_label="S3", side="unknown", confidence=0.0, source="transcript_label"),
    ]
    m = build_speaker_identity_map(ids)
    assert m.side_counts == {"our_side": 1, "counterparty": 1, "unknown": 1}
    assert m.source_summary == {"manual_correction": 1, "legacy_role": 1, "transcript_label": 1}
    assert 0.0 <= m.average_confidence <= 1.0
    assert m.version == "speaker_identity_v1"


def test_build_speaker_context_text_empty():
    assert build_speaker_context_text(build_speaker_identity_map([])) == "Speaker roles are unknown."


def test_build_speaker_context_text_fields():
    ids = [SpeakerIdentity(raw_speaker_label="SM_0", side="our_side",
                           functional_role="project_manager", confidence=0.92, source="manual_correction")]
    txt = build_speaker_context_text(build_speaker_identity_map(ids))
    assert "SM_0" in txt
    assert "side=our_side" in txt
    assert "functional_role=project_manager" in txt
    assert "confidence=0.92" in txt
    assert "source=manual_correction" in txt
