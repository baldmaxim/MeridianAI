# Committed Segment Source Attribution (Stage 8)

Передаёт безопасную structured «зону записи» на committed transcript segment, чтобы Stage 7
attribution-tracker начал получать реальные observations:

committed segment → `speaker_label` + `audio_source_id/channel_label/source_is_isolated/`
`attribution_confidence/attribution_source/source_kind` → `MeetingRoom._on_committed_segment` →
`SessionManager.observe_speaker_audio_attribution` → `SpeakerAudioAttributionTracker` →
`SpeakerAudioLinkMap` → Speaker Identity Graph → speaker_context → Signal Engine.

## Почему Stage 7 был готов, но live был no-op

`CommittedSegment` не нёс source/channel, а `MeetingRoom._speaker_audio_attribution_payload`
возвращал None. Stage 8 добавляет optional `CommittedSegment.source_attribution` и реальную
extract/gate-логику, так что hook начинает отдавать payload — НО только при безопасной metadata.

## Почему нельзя primary→our_side

`primary`/`secondary`/`desktop`/`phone` — техническая зона/устройство, НЕ сторона и НЕ личность.
Часто запись идёт с одного общего room-mic (primary), на котором слышны обе стороны. Если
приписать всех к primary, а hint primary→our_side, контрагент станет «нашим». Поэтому общий
room-mic не даёт observation; сторона приходит отдельно — через `speaker_identity_hints`.

## Поддерживаемые поля segment metadata

Плоско на сегменте ИЛИ вложенно (`source_attribution`/`audio_attribution`/`segment_metadata`/
`diarization_metadata`/`multi_source`):
- `speaker_label` / `speaker` / `label` / `raw_speaker_label`
- `audio_source_id` / `source_id` / `source` / `input_source` / `track_id`
- `channel_label` / `channel` / `channel_name`
- `device_role`, `route`
- `attribution_confidence` / `source_confidence` / `confidence`
- `source_is_isolated` / `isolated` / `isolated_source` / `per_speaker_source`
- `attribution_source`, `source_kind`, `turn_index`

`text`/`transcript`/`recent_dialog` НЕ читаются. Без `speaker_label` → None.

## Когда создаётся observation (`should_emit`)

True, если есть `speaker_label` + (`audio_source_id` и/или `channel_label`) И:
- `source_is_isolated=true` и `confidence ≥ 0.55`; ИЛИ
- `source_kind ∈ {isolated_source, multi_channel, secondary_shadow, manual}` и `confidence ≥ 0.55`; ИЛИ
- `attribution_source ∈ {diarization_result, multi_source_segment, secondary_shadow_segment,`
  `manual_runtime_metadata}` и `confidence ≥ 0.55` и `source_kind ≠ room_mic`.

False (no-op): нет label/source/channel; `source_kind=room_mic` без isolation; generic room-токен
(primary/desktop/phone/...) без isolation; `confidence < 0.55`.

### Safe committed segment
```json
{ "speaker_label": "SM_1", "text": "...", "source_attribution": {
    "audio_source_id": "secondary", "channel_label": "right", "source_is_isolated": true,
    "attribution_confidence": 0.86, "attribution_source": "secondary_shadow_segment",
    "source_kind": "secondary_shadow" } }
```
→ observation создаётся.

### Unsafe segment
```json
{ "speaker_label": "SM_0", "audio_source_id": "primary", "source_kind": "room_mic",
  "source_is_isolated": false }
```
→ observation НЕ создаётся.

## Dedupe

Один committed segment могут увидеть и MeetingRoom, и SessionManager (ctx). Двойной счёт сломал бы
dominance. Payload несёт `segment_id` → tracker дедупит по `dedupe_key` (bounded ~5000 ключей);
без ключа — старое поведение. Счётчик дублей — в `SpeakerAudioAttributionStats.dedupe_seen_count`.

## Связь со speaker_identity_hints

Segment source metadata НЕ даёт сторону. `speaker_identity_hints.audio_sources["secondary"]={side:
counterparty}` даёт сторону для источника; граф соединяет это с speaker через stable link
(`SM_1 ↔ secondary`) ⇒ `SM_1 = counterparty` (source=audio_channel, conf ≤0.85).

## Что смотреть в trace

`speaker_audio_attribution_observation_count`, `..._stable_link_count`, `..._ambiguous_count`,
`speaker_audio_linked_count`, `speaker_unknown_side_count`. В `signal_trace_analysis`:
`attribution_observation_count_p50` vs `attribution_stable_link_count_p50` (есть наблюдения, но
нет links → крутить metadata/thresholds), `attribution_ambiguous_count_p50`, `audio_linked_event_rate`,
`unknown_side_event_rate`.

## Ограничения

- Нет UI, нет БД-миграций, нет LLM inference, нет вывода стороны из source/device токенов.
- Общий primary room-mic без isolation → молчание. Старое поведение без metadata не меняется.
- Trace/logs не содержат raw labels/source ids/channel ids/имён/текста переговоров.

## Stage 9: какой реальный live-path выбран

**Реального авто-пути пока НЕТ** — выбран вариант D (bridge + TODO), без выдумывания metadata.
Инспекция live segment creation (2026-06):
- **Live single-STT (ElevenLabs/legacy)** — `_on_committed` (session_manager.py): `speaker_label`
  есть, но изолированного source/channel НЕТ (общий room-mic) → `source_attribution` не ставим.
- **Live multi-channel STT** (`LiveMultiChannelSegment`, multi_channel_live_session.py) — есть
  `channel_label`/`track_id`/`source_kind` (изолированный канал), но **нет диаризованного
  `speaker_label`** (сегменты по каналу, не по спикеру); отдельная модель и DB-таблица; opt-in
  диагностический оверлей (`multi_channel_live_enabled`). `ch.side` — это side_hint, НЕ сторона.
- **secondary_audio_shadow / multi_source_ingest** — только raw audio + side_hint (RMS), НИКОГДА
  не дают `speaker_label`. `get_speaker_audio_attribution_payload()` → `[]` + TODO.

Поэтому `source_attribution` ставится только через **bridge**, когда появится реально
изолированный путь:
- `build_segment_source_attribution_dict(...)` — безопасно строит dict (или None);
- `attach_source_attribution_to_committed_segment(segment, attribution)` — проставляет поле;
- `SessionManager.bridge_segment_source_attribution(segment, ...)` — точка вызова для будущего
  isolated STT/diarization. Точные TODO: `session_manager._on_committed`,
  `multi_channel_live_session` (per-channel сегмент), `secondary_audio_shadow`/`multi_source_ingest`.

## Stage 9: защита public payload от утечки

Все 3 места сериализации committed-сегмента наружу используют явные whitelisted-dict
(`CommittedSegment.to_wire` / `to_wire_full` / `to_dict`, `MeetingRoom._persist_segments`) — НЕ
`asdict()`/`model_dump()`. Поэтому новое поле `source_attribution` **не утекает** во frontend.
Дополнительно: `public_committed_segment_payload(segment)` (defense-in-depth) удаляет technical-
ключи; регресс-тест фиксирует инвариант (даже при заданном `source_attribution`).

## Stage 9: как проверить вручную

1. `seg = CommittedSegment(speaker_label="SM_1", ...)`;
   `session.bridge_segment_source_attribution(seg, audio_source_id="secondary",
   source_is_isolated=True, attribution_confidence=0.86,
   attribution_source="secondary_shadow_segment", source_kind="secondary_shadow")` → True,
   `seg.source_attribution` заполнен.
2. Прогнать сегмент через `MeetingRoom._on_committed_segment` → ожидать рост
   `speaker_audio_attribution_observation_count` / `stable_link_count` в shadow-trace.
3. Задать `speaker_identity_hints.audio_sources["secondary"]={side:counterparty}` → проверить, что
   `SM_1` получает side в speaker_context и `unknown_side_event_rate` снижается.
4. Убедиться, что `seg.to_wire_full()` НЕ содержит `source_attribution`/`audio_source_id`.
