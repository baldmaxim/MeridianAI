# Per-channel STT Canary Operations + Provider Timeout Hardening (Stage 19)

Backend-only эксплуатационный контур для безопасного запуска Stage 18 per-channel STT canary на
ОДНОЙ встрече: shadow → candidate-emission → rollback, плюс мониторинг готовности. Поверх
[per_channel_stt_candidates.md](per_channel_stt_candidates.md). Tool **ничего не применяет** —
печатает JSON для ручного `PATCH /api/meetings/{id}/ai-settings`.

## Что добавляет Stage 19

- **Provider timeout hardening:** `BatchTranscriptionService.transcribe(..., request_timeout=...)` (default
  None → прежние 300s для production-финализации); per-channel адаптер передаёт bounded
  `min(max(timeout_seconds,1),120)` внутрь HTTP — orphan-поток не живёт дольше asyncio-таймаута.
- **Operations toolkit** (`per_channel_stt_canary_operations`): shadow / emit-candidates / rollback patch + plan.
- **Monitor** (`per_channel_stt_canary_monitor`): читает PER_CHANNEL_STT_TRACE + SOURCE_RECONCILE_TRACE +
  SIGNAL_ENGINE_TRACE, фильтрует по meeting/session/check, выдаёт status + recommendation + suggested/rollback patch.

## Lifecycle

1. **Stage 16:** включить multichannel shadow в UI (2+ канала).
2. **Stage 18/19:** `emit-shadow --provider elevenlabs_batch` (API-ключ — server-side, не в patch).
3. Собрать `PER_CHANNEL_STT_TRACE` за несколько сессий.
4. `plan`/`monitor` по `--meeting-id`.
5. Если `ready_for_candidate_emit` → `emit-candidates` (per-channel `shadow_mode=false`).
6. `source_reconcile` остаётся `shadow=true` (отдельный слой).
7. Только позже — Stage 13/14 для `source_reconcile_shadow_mode=false`.
8. `emit-rollback` при provider errors/cost.

## Команды

```bash
cd meridian-web/backend
../.venv/Scripts/python.exe -m app.core.context.per_channel_stt_canary_operations emit-shadow --provider elevenlabs_batch
../.venv/Scripts/python.exe -m app.core.context.per_channel_stt_canary_operations plan /path/app.log --meeting-id 123
../.venv/Scripts/python.exe -m app.core.context.per_channel_stt_canary_operations emit-candidates /path/app.log --meeting-id 123
../.venv/Scripts/python.exe -m app.core.context.per_channel_stt_canary_monitor /path/app.log --meeting-id 123 --emit-rollback-if-needed
../.venv/Scripts/python.exe -m app.core.context.per_channel_stt_canary_operations emit-rollback
# эквивалент монитора через общий operations-CLI:
../.venv/Scripts/python.exe -m app.core.context.canary_operations monitor-per-channel-stt /path/app.log --meeting-id 123
```
Exit: `0` ок; `2` файл не найден; `3` неверные аргументы; `4` not ready (emit-candidates) / mixed meetings (--require-single-meeting).

## Patches

- **shadow patch:** `audio_per_channel_stt_enabled=true`, `shadow_mode=true`, `trace_enabled=true`,
  `provider=<...>` (+опц. budget/threshold). НЕ трогает source_reconcile/signal_engine/hints.
- **emit-candidates patch:** `audio_per_channel_stt_shadow_mode=false` + держит source_reconcile
  shadow-safe (`source_reconcile_enabled=true`, `source_reconcile_shadow_mode=true`,
  `source_reconcile_trace_enabled=true`). **НЕ** ставит `source_reconcile_shadow_mode=false`,
  **НЕ** трогает `signal_engine_*`/`speaker_identity_hints`. None, если не ready.
- **rollback patch:** все 23 `audio_per_channel_stt_*` → `null`. **НЕ** очищает `source_reconcile_*`,
  `signal_engine_*`, `speaker_identity_hints` — возврат только per-channel слоя к global defaults.

## Monitor: status / recommendation

| status | recommendation |
|---|---|
| `no_data` | `enable_multichannel_shadow` |
| `no_multichannel` | `enable_multichannel_shadow` / `collect_more_data` |
| `provider_unavailable` | `configure_provider` (noop / api_key_missing / unknown_provider) |
| `shadow_collecting` | `collect_more_data` / `tighten_vad` / `check_provider_latency` / `increase_budget` |
| `ready_for_candidate_emit` | `emit_candidates` (+ `suggested_patch`) |
| `candidate_emit_running` | `continue_candidate_emit` |
| `warning` | `collect_more_data` (candidates есть, но reconcile не матчит) |
| `rollback_recommended` | `rollback_per_channel_stt` (timeout/provider error/latency) |

## Связь с `source_reconcile_shadow_mode`

emit-candidates только переводит per-channel STT в candidate-emission; кандидаты идут в
`SourceAttributionReconciler`, который остаётся `shadow=true` (would_attach считается, attach нет).
Включение `source_reconcile_shadow_mode=false` — отдельный шаг (Stage 13/14), эти tools его НЕ делают.

## Связь со `speaker_identity_hints`

Кандидаты несут технические `audio_source_id="channel_{index}"`/`channel_label="channel_{index}"`. Это
НЕ сторона. Сторона задаётся явно через `speaker_identity_hints` (`audio_sources.channel_0`/`channel_1`
или `channel_labels`) поверх stable link — отдельным PATCH, не этими tools.

## Safety

- no auto apply; no DB/network в tooling; API-ключ только server-side (из `session._elevenlabs_key`,
  не в patch/snapshot/logs);
- нет raw audio/text/source ids/channel labels/speaker labels/segment ids/candidate ids в выводе;
- `safety_checks` в plan/report проверяют сериализованные data/patch на запрещённые токены;
- channel = техническая зона, не сторона.

## TRACE: что смотреть

**Перед emit-candidates** (PER_CHANNEL_STT_TRACE): `transcribe_success_count > 0` (provider реально
работает, не `adapter_unavailable`/`api_key_missing`), `candidate_shadow_suppressed_count > 0`,
`transcribe_timeout_count`/`transcribe_provider_error_count`/`transcribe_budget_exhausted_count` низкие,
`average_dominance` ≥ ~0.65, `max_channels_seen ≥ 2`, `by_provider` = реальный provider.

**После emit-candidates** (SOURCE_RECONCILE_TRACE): `would_attach_rate > 0` и `by_match_reason`
(matched vs low_overlap/low_text_similarity/ambiguous) — готовность к Stage 13/14 source_reconcile active.

## Stage 20: единый field report

Перед реальным rollout — единый отчёт по одной встрече (audio/per-channel/cost/source_reconcile/hints/
signal) + safe next-patch: см. [field_canary_report.md](field_canary_report.md)
(`field_canary_report --meeting-id` или `canary_operations field-report`). Plus усиленный provider error
logging (без raw body/ключей).

## Troubleshooting

- **no multichannel frames** → Stage 16 shadow не включён / браузер не отдаёт каналы.
- **provider noop / api_key_missing** → задать `provider=elevenlabs_batch` + ключ server-side.
- **budget exhausted** → поднять `max_provider_calls_per_meeting` / `max_provider_audio_seconds_per_meeting`.
- **timeout / provider_error** → проверить latency/сеть; rollback при высокой доле.
- **shadow suppressed candidates** → перейти на emit-candidates.
- **candidates есть, но source_reconcile no matches** → проверить timestamps/text similarity (Stage 13/14).
