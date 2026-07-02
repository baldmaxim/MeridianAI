"""Speaker Identity Graph v1 (Этап 4): SpeakerIdentityService."""

from types import SimpleNamespace

from app.services.speaker_identity_service import SpeakerIdentityService

SVC = SpeakerIdentityService()


def _by_label(m):
    return {i.raw_speaker_label: i for i in m.speakers.values()}


def test_build_from_legacy_roles_flat_dict():
    m = SVC.build_from_legacy_roles({"Speaker 1": "self", "Speaker 2": "opponent"})
    byl = _by_label(m)
    assert byl["Speaker 1"].side == "our_side"
    assert byl["Speaker 1"].source == "legacy_role"
    assert byl["Speaker 1"].confidence == 0.85
    assert byl["Speaker 2"].side == "counterparty"


def test_build_from_legacy_roles_nested_dict():
    m = SVC.build_from_legacy_roles({"Speaker 1": {"side": "self", "role": "pm"}})
    ident = _by_label(m)["Speaker 1"]
    assert ident.side == "our_side"
    assert ident.functional_role == "project_manager"


def test_build_from_legacy_roles_list_of_objects():
    items = [SimpleNamespace(speaker_label="SM_0", side="opponent", role="procurement")]
    m = SVC.build_from_legacy_roles(items)
    ident = _by_label(m)["SM_0"]
    assert ident.side == "counterparty"
    assert ident.functional_role == "procurement"


def test_extract_labels_from_recent_dialog():
    dialog = "\n".join([
        "Speaker 1: давайте обсудим цену",
        "SM_0: мы готовы",
        "[Speaker 2] нет, дорого",
        "[SM_1] подождите",
        "МЫ: фиксируем",
        "НЕ МЫ: посмотрим",
    ])
    labels = SVC.extract_labels_from_recent_dialog(dialog)
    assert "Speaker 1" in labels
    assert "SM_0" in labels
    assert "Speaker 2" in labels
    assert "SM_1" in labels
    assert "МЫ" in labels
    assert "НЕ МЫ" in labels


def test_build_runtime_map_adds_unknown_labels_from_dialog():
    m = SVC.build_runtime_map(recent_dialog="Speaker 9: что-то\nSpeaker 10: ещё")
    byl = _by_label(m)
    assert byl["Speaker 9"].side == "unknown"
    assert byl["Speaker 9"].source == "transcript_label"
    assert byl["Speaker 9"].confidence == 0.0


def test_manual_overrides_take_priority_over_transcript_labels():
    # Speaker 1 в диалоге как unknown, но есть manual override → manual_correction остаётся
    m = SVC.build_runtime_map(
        manual_overrides={"Speaker 1": "self"},
        recent_dialog="Speaker 1: привет\nSpeaker 2: пока",
    )
    byl = _by_label(m)
    assert byl["Speaker 1"].side == "our_side"
    assert byl["Speaker 1"].source == "manual_correction"
    assert byl["Speaker 1"].confidence == 0.99
    # Speaker 2 — только из диалога
    assert byl["Speaker 2"].source == "transcript_label"


def test_legacy_roles_priority_over_transcript():
    m = SVC.build_runtime_map(
        legacy_roles={"Speaker 1": "opponent"},
        recent_dialog="Speaker 1: реплика",
    )
    ident = _by_label(m)["Speaker 1"]
    assert ident.source == "legacy_role"
    assert ident.side == "counterparty"


def test_device_role_hint_capped_confidence_and_unknown_side():
    m = SVC.build_runtime_map(device_roles={"Speaker 1": "desktop"})
    ident = _by_label(m)["Speaker 1"]
    assert ident.confidence <= 0.55
    assert ident.side == "unknown"  # device НЕ определяет сторону
    assert ident.device_role == "desktop"
    assert ident.source == "device_role"


def test_empty_input_returns_empty_map():
    m = SVC.build_runtime_map()
    assert m.speakers == {}
    assert m.side_counts == {}
    assert SVC.build_context_text(m) == "Speaker roles are unknown."


# --- Этап 5: identity_hints, explicit sides, tightened extraction ---

def test_build_runtime_map_applies_speaker_labels_hint():
    m = SVC.build_runtime_map(
        recent_dialog="SM_0: реплика",
        identity_hints={"speaker_labels": {"SM_0": {"side": "our_side",
                        "functional_role": "project_manager", "confidence": 0.95}}},
    )
    ident = _by_label(m)["SM_0"]
    assert ident.side == "our_side"
    assert ident.functional_role == "project_manager"
    assert ident.source == "manual_correction"
    assert ident.confidence == 0.95


def test_stable_ids_hint_updates_existing_identity():
    from app.core.context.speaker_identity import make_stable_speaker_id
    sid = make_stable_speaker_id("Speaker 2")
    m = SVC.build_runtime_map(
        recent_dialog="Speaker 2: hi",
        identity_hints={"stable_ids": {sid: {"side": "counterparty", "confidence": 0.9}}},
    )
    ident = _by_label(m)["Speaker 2"]
    assert ident.side == "counterparty"
    assert ident.source == "manual_correction"


def test_explicit_my_label_is_our_side():
    m = SVC.build_runtime_map(recent_dialog="МЫ: фиксируем условия")
    ident = _by_label(m)["МЫ"]
    assert ident.side == "our_side"
    assert ident.confidence == 0.9
    assert ident.source == "transcript_label"


def test_explicit_not_my_label_is_counterparty():
    m = SVC.build_runtime_map(recent_dialog="НЕ МЫ: дайте скидку")
    ident = _by_label(m)["НЕ МЫ"]
    assert ident.side == "counterparty"
    assert ident.confidence == 0.9


def test_generic_name_not_extracted_by_default():
    labels = SVC.extract_labels_from_recent_dialog("Иван: давайте обсудим\nМенеджер: согласен")
    assert labels == []


def test_allow_generic_labels_true_extracts_names():
    labels = SVC.extract_labels_from_recent_dialog("Иван: давайте", allow_generic_labels=True)
    assert "Иван" in labels


def test_strict_patterns_still_extract_speaker_forms():
    labels = SVC.extract_labels_from_recent_dialog(
        "Speaker 1: a\nSM_0: b\n[Speaker 2] c\nS_3: d\nSPEAKER_4: e")
    assert {"Speaker 1", "SM_0", "Speaker 2", "S_3", "SPEAKER_4"} <= set(labels)


def test_manual_overrides_priority_over_identity_hints():
    # manual_overrides (our_side) должен победить identity_hint (counterparty) для SM_0
    m = SVC.build_runtime_map(
        manual_overrides={"SM_0": "self"},
        identity_hints={"speaker_labels": {"SM_0": {"side": "counterparty", "confidence": 0.98}}},
    )
    ident = _by_label(m)["SM_0"]
    assert ident.side == "our_side"
    assert ident.source == "manual_correction"


def test_audio_sources_no_metadata_does_not_create_side():
    # без metadata-связи source→label hint не применяется (не выдумываем)
    m = SVC.build_runtime_map(
        identity_hints={"audio_sources": {"primary": {"side": "our_side", "confidence": 0.8}}},
    )
    assert m.speakers == {}  # ничего не создано


def test_audio_sources_with_metadata_capped_confidence():
    # metadata = {speaker_label: source_id} (label→source, формат Этапа 6)
    m = SVC.build_runtime_map(
        identity_hints={"audio_sources": {"primary": {"side": "our_side", "confidence": 0.99}}},
        audio_source_metadata={"SM_5": "primary"},
    )
    ident = _by_label(m)["SM_5"]
    assert ident.side == "our_side"
    assert ident.source == "audio_channel"
    assert ident.confidence <= 0.85


# --- Этап 6: audio/channel hints через explicit link ---

def test_audio_sources_hint_applies_with_metadata_link():
    m = SVC.build_runtime_map(
        recent_dialog="SM_0: реплика\nSM_1: ответ",
        identity_hints={"audio_sources": {
            "primary": {"side": "our_side", "confidence": 0.8},
            "secondary": {"side": "counterparty", "confidence": 0.8}}},
        audio_source_metadata={"SM_0": "primary", "SM_1": "secondary"},
    )
    byl = _by_label(m)
    assert byl["SM_0"].side == "our_side"
    assert byl["SM_0"].source == "audio_channel"
    assert byl["SM_1"].side == "counterparty"


def test_audio_sources_hint_does_not_apply_without_link():
    m = SVC.build_runtime_map(
        recent_dialog="SM_0: реплика",
        identity_hints={"audio_sources": {"primary": {"side": "our_side", "confidence": 0.8}}},
    )
    assert _by_label(m)["SM_0"].side == "unknown"  # нет link → не применилось


def test_channel_labels_hint_applies_with_metadata_link():
    m = SVC.build_runtime_map(
        identity_hints={"channel_labels": {
            "left": {"side": "our_side", "confidence": 0.8},
            "right": {"side": "counterparty", "confidence": 0.8}}},
        channel_metadata={"SM_0": "left", "SM_1": "right"},
    )
    byl = _by_label(m)
    assert byl["SM_0"].side == "our_side"
    assert byl["SM_1"].side == "counterparty"
    assert byl["SM_0"].confidence <= 0.85


def test_manual_overrides_beats_audio_channel_hint():
    m = SVC.build_runtime_map(
        manual_overrides={"SM_0": "self"},
        identity_hints={"audio_sources": {"primary": {"side": "counterparty", "confidence": 0.85}}},
        audio_source_metadata={"SM_0": "primary"},
    )
    ident = _by_label(m)["SM_0"]
    assert ident.side == "our_side"
    assert ident.source == "manual_correction"


def test_speaker_label_hint_beats_audio_channel_hint():
    m = SVC.build_runtime_map(
        identity_hints={
            "speaker_labels": {"SM_0": {"side": "our_side", "confidence": 0.95}},
            "audio_sources": {"primary": {"side": "counterparty", "confidence": 0.85}}},
        audio_source_metadata={"SM_0": "primary"},
    )
    ident = _by_label(m)["SM_0"]
    assert ident.side == "our_side"
    assert ident.source == "manual_correction"


def test_audio_channel_conflict_close_confidence_is_unknown():
    # source→our_side(0.8) vs channel→counterparty(0.8): близкий конфликт → unknown
    m = SVC.build_runtime_map(
        identity_hints={
            "audio_sources": {"primary": {"side": "our_side", "confidence": 0.8}},
            "channel_labels": {"left": {"side": "counterparty", "confidence": 0.8}}},
        audio_source_metadata={"SM_0": "primary"},
        channel_metadata={"SM_0": "left"},
    )
    ident = _by_label(m)["SM_0"]
    assert ident.side == "unknown"
    assert "conflicting_audio_channel_hints" in ident.evidence


def test_audio_channel_conflict_strong_wins_with_penalty():
    # source→our_side(0.85) vs channel→counterparty(0.6): diff>=0.15 → our_side, conf -0.1
    m = SVC.build_runtime_map(
        identity_hints={
            "audio_sources": {"primary": {"side": "our_side", "confidence": 0.85}},
            "channel_labels": {"left": {"side": "counterparty", "confidence": 0.6}}},
        audio_source_metadata={"SM_0": "primary"},
        channel_metadata={"SM_0": "left"},
    )
    ident = _by_label(m)["SM_0"]
    assert ident.side == "our_side"
    assert "conflicting_audio_channel_hints" in ident.evidence
    assert ident.confidence <= 0.75 + 1e-9  # 0.85 - 0.1


def test_structured_link_creates_identity_even_if_label_absent_from_dialog():
    # SM_9 нет в recent_dialog, но есть link → identity создаётся
    m = SVC.build_runtime_map(
        recent_dialog="SM_0: hi",
        identity_hints={"audio_sources": {"primary": {"side": "our_side", "confidence": 0.8}}},
        audio_source_metadata={"SM_9": "primary"},
    )
    assert "SM_9" in _by_label(m)
    assert _by_label(m)["SM_9"].side == "our_side"


def test_device_role_not_side_with_audio_links():
    m = SVC.build_runtime_map(device_roles={"SM_0": "desktop"})
    ident = _by_label(m)["SM_0"]
    assert ident.side == "unknown"
    assert ident.device_role == "desktop"
