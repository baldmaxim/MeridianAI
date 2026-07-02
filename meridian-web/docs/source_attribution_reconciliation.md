# Source Attribution Reconciliation (Stage 10)

Связывает основной committed transcript segment (есть `speaker_label`, нет source/channel) с
isolated/per-channel **source candidate** (есть source/channel, нет `speaker_label`). При сильном
НЕ-ambiguous совпадении строит `source_attribution` и прикрепляет к committed segment → дальше
работает цепочка Stage 8/7 (observation → link → speaker_context → Signal Engine).

## Зачем Stage 10 (что не дал Stage 9)

Stage 9 добавил `bridge_segment_source_attribution`, но он **никем не вызывался автоматически**:
live single-STT даёт speaker_label без source/channel; multi-channel-live даёт source/channel без
speaker_label (разные модели/потоки). Stage 10 — безопасный reconciler, который их сводит.

## Схема

```
multi_channel_live / secondary_shadow per-channel segment (source/channel, без speaker_label)
  → live_multi_channel_segment_to_source_candidate / secondary_shadow_segment_to_source_candidate
  → MeetingRoom._on_live_final_segment → session.observe_source_attribution_candidate
  → SourceAttributionReconciler.observe_candidate (накапливает)

committed segment (speaker_label) → SessionManager._on_committed
  → reconcile_source_attribution_for_segment → reconciler.reconcile_segment
  → при match: attach source_attribution → committed-hook (Stage 8) → observation → link
```

## Поддерживаемые candidate-поля

`text`/`transcript` (только для технического match), `start_ms/start/end_ms/end/timestamp_ms/`
`start_server_ms/end_server_ms`, `audio_source_id/source_id/source/input_source/track_id`,
`channel_label/channel/channel_name`, `source_is_isolated/isolated/per_channel/per_source`,
`source_kind`, `attribution_source`, `attribution_confidence/confidence/source_confidence`,
`candidate_id/segment_id/id`, `turn_index`, `device_role`, `route`, `candidate_pipeline`. Вложенно:
`source_attribution_candidate/source_attribution/audio_attribution/multi_source/segment_metadata/`
`diarization_metadata`. Кандидат **отклоняется** без source/channel, при room_mic non-isolated, при
generic room-токене без isolation, при confidence < `min_candidate_confidence` (0.55).

## Matching policy

- **explicit correlation** (сильнейший): `candidate.turn_index == segment.turn_index` ИЛИ
  `candidate.candidate_id == segment.segment_id` → match (score≥0.9), без порогов overlap/text.
- **time + text**: требуется `time_overlap ≥ 0.45` И `text_similarity ≥ 0.78`.
- **text-only** (нет времени): очень высокий `text_similarity ≥ 0.9` И единственный eligible-кандидат.
- **time-only** (нет текста): `time_overlap ≥ 0.8` И `candidate_confidence ≥ 0.85` И единственный.
- **score** = `clamp(0.45·time_overlap + 0.4·text_similarity + 0.15·candidate_confidence)`; reject
  если `score < 0.62`.
- **ambiguity**: если топ-2 кандидата в пределах `ambiguity_margin` (0.08) → **ambiguous**, без attribution.

## Когда прикрепляется / НЕ прикрепляется

Прикрепляется: есть speaker_label, есть isolated/per-channel candidate, сильный НЕ-ambiguous match,
`build_segment_source_attribution_dict` пропускает (should_emit). Поле берёт `speaker_label` из
committed-сегмента, source/channel/device/route — из кандидата, `attribution_confidence =
min(candidate_confidence, match_score)`. НЕ прикрепляется: нет кандидатов / нет speaker_label / нет
текста и времени / низкий overlap или similarity / ambiguous / room_mic / уже задан (bridge/manual
не перезаписывается).

## Безопасность

- **Никакого вывода стороны.** `side`/`side_hint` (включая `ch.side` multi-channel) НЕ используется
  и НЕ переносится в граф. source/channel/track — техническая зона записи, не сторона/личность.
- primary/room_mic non-isolated и generic-токены без isolation — заблокированы (candidate и should_emit).
- secondary сам по себе НЕ counterparty; primary сам по себе НЕ our_side.
- Текст — только для технического совпадения; не для стороны и не для подсказок.
- raw text / speaker labels / source ids / channel ids / segment ids НЕ логируются и НЕ в trace —
  только агрегаты (counts, score, категории reason/source).

## Связь со speaker_identity_hints

Reconciliation даёт `source_attribution` → observation → stable link `SM_1 ↔ secondary`. Сторону
даёт отдельно `speaker_identity_hints.audio_sources["secondary"]={side:counterparty}` ⇒
`SM_1 = counterparty` (source=audio_channel, conf ≤0.85). См.
[audio_channel_identity_wiring.md](audio_channel_identity_wiring.md).

## Что смотреть в trace

`source_reconcile_candidate_count`, `source_reconcile_match_count`, `source_reconcile_match_reasons`,
`source_reconcile_ambiguous_count`, `source_reconcile_average_match_score`, плюс
`speaker_audio_attribution_*`, `unknown_side_event_rate`, `hint_source_event_rate`. В
`signal_trace_analysis` → `source_reconciliation` (p50/match_rate/by_candidate_source/by_match_reason)
+ notes: «candidates есть, matches 0», «ambiguous > 0», «reconciliation работает, но hints не
покрывают sources/channels», «низкий score reconciliation».

## Текущее состояние

Кандидаты поступают только из live multi-channel STT (opt-in `multi_channel_live_enabled`);
secondary-shadow пока без STT → helper возвращает None (TODO). Без кандидатов поведение прежнее
(`source_attribution` остаётся None, side unknown). Нет UI/БД-миграций/LLM.

## Stage 11: canary controls + calibration trace

Reconciliation теперь управляется флагами `AI_SOURCE_RECONCILE_*` и hidden per-meeting override
`source_reconcile_*`. **По умолчанию shadow_mode=true** — candidates считаются и трассируются, но
`source_attribution` НЕ прикрепляется (active attach только при `source_reconcile_shadow_mode=false`
через session override или global). Отдельный `SOURCE_RECONCILE_TRACE` + CLI-анализатор для
калибровки порогов. Подробности и пример PATCH: [source_reconciliation_canary.md](source_reconciliation_canary.md).
