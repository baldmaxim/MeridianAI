# Field Canary Report + Provider Log Hardening (Stage 20)

Backend-only **полевой отчёт** по одной реальной canary-встрече перед практическим rollout: единый
безопасный срез по audio/multichannel, per-channel STT provider health/cost/budget, candidate
emission, source reconciliation, speaker hint coverage, Signal Engine — + рекомендация + safe PATCH-
кандидаты. Плюс усиленная приватность provider error logging.

Tool **ничего не применяет**, не ходит в сеть/БД, не вызывает LLM, печатает JSON для ручного PATCH.

## Зачем это перед MVP rollout

Stage 16–19 дали транспорт/провайдер/operations/monitor по слоям. Stage 20 сводит их в ОДИН отчёт по
`--meeting-id`, чтобы оператор за один взгляд понял: где сейчас canary, что безопасно включить дальше,
сколько стоит провайдер, и нет ли утечек.

## Operational lifecycle

1. Stage 16 — multichannel shadow (UI).
2. per-channel STT shadow + provider (`emit-shadow --provider elevenlabs_batch`, ключ server-side).
3. **field report** (`field_canary_report --meeting-id`).
4. emit candidate patch если ready.
5. source_reconcile shadow analysis (`would_attach_rate`).
6. source_reconcile active canary (Stage 13/14).
7. active monitor / rollback (Stage 14).

## Команды

```bash
cd meridian-web/backend
../.venv/Scripts/python.exe -m app.core.context.field_canary_report /path/app.log --meeting-id 123
../.venv/Scripts/python.exe -m app.core.context.field_canary_report /path/app.log --meeting-id 123 --provider-cost-per-minute 0.40
../.venv/Scripts/python.exe -m app.core.context.field_canary_report /path/app.log --meeting-id 123 --emit-next-patch
../.venv/Scripts/python.exe -m app.core.context.field_canary_report /path/app.log --meeting-id 123 --output report.json
# через общий operations-CLI:
../.venv/Scripts/python.exe -m app.core.context.canary_operations field-report /path/app.log --meeting-id 123
```
Exit: `0` ок; `2` файл не найден; `3` неверные аргументы; `4` нет safe next patch (--emit-next-patch) /
mixed meetings (--require-single-meeting).

## Статусы

`no_data` · `collecting` · `per_channel_shadow_ready` · `candidate_emit_ready` · `source_reconcile_ready`
· `active_source_reconcile_running` · `healthy` · `rollback_recommended` · `needs_hints` · `not_ready`.

## Какие patch-и предлагает (`patches`)

- `per_channel_shadow_patch` — старт per-channel STT shadow (+detected provider).
- `per_channel_emit_candidates_patch` — shadow→emit (None пока не ready); source_reconcile остаётся shadow.
- `per_channel_rollback_patch` — все `audio_per_channel_stt_*` → null.
- `source_reconcile_active_patch` — из Stage 12/13 readiness (None пока не ready_for_active).
- `source_reconcile_rollback_patch` — `source_reconcile_*` → null.

`--emit-next-patch` печатает один рекомендованный следующий patch (или exit 4). Все patch-и
печатаются, **не применяются**. `endpoint_template` — placeholder `{meeting_id}`.

## Как читать

- **audio:** `multichannel_seen`, `max_channels_seen_p50`, `v2_parse_errors`, `v2_sequence_gaps`, `capture_routes/pipelines`.
- **per_channel_stt:** provider/enabled/shadow_mode, `transcribe_success_count`, `candidate_shadow_suppressed_count`/`candidate_emit_count`, `adapter_unavailable_count`/`api_key_missing_count`/`timeout_count`/`provider_error_count`/`budget_exhausted_count`, `cache_hit_rate`, `average_dominance_p50`, `average_transcribe_latency_p95_ms`.
- **source_reconciliation:** `would_attach_rate`/`actual_attach_rate`, `by_match_reason`, `score_p50`, `low_overlap_rate`/`low_text_similarity_rate`/`ambiguous_rate`.
- **speaker_context:** `unknown_side_event_rate`/`hint_source_event_rate`/`audio_linked_event_rate`/`avg_speaker_confidence_p50`.
- **signal_engine:** `would_prompt_rate`/`actual_prompt_rate`/`timeout_exception_rate`/`latency_p95_ms`.
- **cost_usage:** `provider_call_count`, `provider_audio_seconds`/`provider_audio_minutes`, `estimated_cost`, `cost_per_minute_used`, `cache_hit_rate`, `budget_exhausted_count`.

## Cost

Pricing НЕ зашит. При `--provider-cost-per-minute X` → `estimated_cost = provider_audio_minutes * X`.
Без cost-input → `estimated_cost=null`. `provider_audio_seconds`/`provider_calls` берутся из новых
безопасных trace-агрегатов (`provider_audio_seconds_used`/`provider_calls_used` из `PerChannelSttBudget`),
без raw audio.

## Provider error log hardening

`BatchTranscriptionService` больше **не логирует raw provider body**: вместо `e.response.text` —
`safe_provider_error_summary` (`provider`/`error_type`/`status_code`/`response_body_chars`/
`response_body_hash` sha256[:16]/`content_type`). Preview тела выключен по умолчанию
(`TRANSCRIPTION_PROVIDER_ERROR_BODY_PREVIEW_ENABLED=false`); при включении всё равно редактирует
`Authorization`/`xi-api-key`/`Bearer`/`sk_*` и обрезает. Per-channel адаптер логирует ту же safe-сводку.

## Safety

- отчёт без raw text/audio/source ids/channel labels/speaker labels/segment ids/candidate ids/API keys;
- `safety_checks` проверяют сериализованный отчёт+patches на запрещённые токены (включая `xi-api-key`/`Authorization`/`Bearer`/`sk_live`, `pcm16_mono`/`RIFF`);
- patch-и печатаются, не применяются; не включают Signal Engine active; не модифицируют `speaker_identity_hints`;
- side inference нет; `channel_{index}` — техническая зона; «add speaker_identity_hints» — рекомендация, значения задаёт оператор.

## Связь со `speaker_identity_hints`

`needs_hints` означает: links/candidates есть, но `unknown_side_event_rate` высок и `hint_source_event_rate`
низкий → добавить `speaker_identity_hints` (`audio_sources.channel_0/channel_1` или `channel_labels`)
ОТДЕЛЬНЫМ PATCH. Tool значения не выдумывает. Оператор задаёт их из UI «Роли и стороны»
(Этап 21) — см. [speaker_role_confirmation_ui.md](speaker_role_confirmation_ui.md).

## Known limitations

- cost-estimate требует `--provider-cost-per-minute` от оператора;
- качество отчёта зависит от фильтра по одной встрече (`--meeting-id`/`--require-single-meeting`);
- hints по-прежнему ручные/явные;
- `latency_p95_ms` per-channel — средняя latency адаптера (proxy), не истинный p95.

## См. также

Traces (SIGNAL/PER_CHANNEL_STT/SOURCE_RECONCILE) пишутся только в `app.log` и приложением не удаляются
(logrotate). Privacy/retention контролы данных встречи — [privacy_retention_delete_export.md](privacy_retention_delete_export.md).
