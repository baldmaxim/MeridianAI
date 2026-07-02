# Live Speaker Audio Attribution Wiring (Stage 7)

Подключает live-поток к цепочке Stage 6: structured segment/source metadata →
`speaker_label ↔ audio_source_id/channel_label` → SpeakerAudioLinkMap →
`speaker_identity_hints` (audio_sources/channel_labels) → Speaker Identity Graph →
speaker_context → Signal Engine.

Stage 6 умел применить hint, если link уже есть. **Stage 7 создаёт link только если есть
structured metadata и attribution достаточно устойчивая.** Нет metadata / неоднозначно →
ничего не делаем, side остаётся unknown.

## Почему нельзя маппить primary→our_side автоматически

`primary`/`secondary`/`desktop`/`phone` — это **зона записи / устройство**, а НЕ сторона и НЕ
личность. Запись часто идёт с одного общего room-mic (primary), на котором слышны ОБЕ стороны.
Если приписать всех спикеров к `primary`, а `primary`→our_side, то контрагент станет «нашим».
Поэтому сторона появляется только через explicit `speaker_identity_hints`, привязанный к
источнику/каналу, И только когда есть стабильная per-speaker привязка.

## Почему on_start_listening недостаточно

На старте listening speaker label ещё неизвестен (диаризация даёт метку только на committed
segment). Привязать speaker→source можно лишь там, где ОДНОВРЕМЕННО известны speaker_label и
изолированный источник/канал — это committed-segment хук, а не старт.

## Что считается safe structured observation

`SpeakerAudioObservation`: `speaker_label` + (`audio_source_id` и/или `channel_label`), опц.
`attribution_confidence`, `source_is_isolated`, `device_role`, `route`, `turn_index`, `source`.
- `source_is_isolated=true` означает: attribution из ОТДЕЛЬНОГО source/channel pipeline
  (per-speaker), а не из общего room-mic.
- Никакого transcript text. Записи без speaker label и без source/channel игнорируются.

Пример segment payload:
```json
{ "speaker_label": "SM_0", "audio_source_id": "secondary", "channel_label": "right",
  "attribution_confidence": 0.82, "source_is_isolated": true }
```

## Как tracker делает stable link

`SpeakerAudioAttributionTracker.build_link_map()` группирует observations по стабильному id
спикера и создаёт link, если:
- **A.** ≥ `min_observations` (деф. 2) наблюдений на одном source/channel и `dominance_ratio` ≥
  `min_dominance_ratio` (деф. 0.67); ИЛИ
- **B.** одно isolated high-confidence: `source_is_isolated=true` и `attribution_confidence` ≥
  `single_high_confidence_threshold` (деф. 0.85).

Link НЕ создаётся, если:
- нет speaker_label или нет source/channel;
- одно сомнительное наблюдение non-isolated с generic room-токеном (primary/desktop/...) —
  `allow_single_source_room_mic_links=false`;
- конфликт sources/channels без доминанты → speaker помечается **ambiguous**, link нет.

Link confidence = `min(1, avg_confidence × dominance_ratio)`, но не ниже `min_confidence`.

## Связь со speaker_identity_hints

Link сам по себе НЕ даёт стороны. Сторона приходит из snapshot:
`speaker_identity_hints.audio_sources["secondary"] = {side: counterparty}` +
link `SM_0 ↔ secondary` ⇒ `SM_0 = counterparty` (source=audio_channel, conf ≤0.85). См.
[audio_channel_identity_wiring.md](audio_channel_identity_wiring.md).

## Текущее состояние live-привязки

Связи `speaker_label → track_id/source/channel` в live-диаризации **пока нет**: `MultiSourceIngest`
держит track→role/side_hint, `SecondaryAudioShadow` — connection→side_hint, оба без speaker_label;
`CommittedSegment` не несёт source/channel. Поэтому `MeetingRoom._on_committed_segment` зовёт
`session.observe_speaker_audio_attribution(...)` только если сегмент несёт per-speaker source/channel
(сейчас → no-op). Точка расширения помечена `TODO(stage7)` в meeting_room.py и multi_source_ingest.py.
До этого момента поведение в бою прежнее (side остаётся unknown).

## Что смотреть в trace

`SIGNAL_ENGINE_TRACE` (только агрегаты): `speaker_audio_attribution_observation_count`,
`speaker_audio_attribution_stable_link_count`, `speaker_audio_attribution_ambiguous_count`,
`speaker_audio_attribution_average_confidence`, `speaker_audio_attribution_sources`,
а также `speaker_audio_linked_count`, `unknown_side_count`.

В `signal_trace_analysis` → `speaker_context`: `attribution_observation_count_p50`,
`attribution_stable_link_count_p50`, `attribution_ambiguous_count_p50`,
`attribution_average_confidence_p50`, `attribution_source_event_rate`, `by_attribution_source`,
плюс `audio_linked_event_rate`, `unknown_side_event_rate`, `hint_source_event_rate`. Notes:
«observations есть, но stable links 0», «часть labels ambiguous», «мало live audio attribution».

## Ограничения

- Нет UI, нет БД-миграций, нет LLM inference.
- Нет вывода стороны из device/source/channel токенов.
- Tracker не уверен → link не создаётся.
- Trace/logs не содержат raw labels/source ids/channel ids/имён/текста переговоров.
