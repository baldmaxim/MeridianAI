# Canary Readiness Harness + Combined Trace Analysis (Stage 12)

Перед реальным active canary (Stage 11 `source_reconcile_shadow_mode=false`) Stage 12 даёт два
backend-only инструмента (без БД/LLM/network/frontend):

| Инструмент | Что это |
|---|---|
| `source_reconcile_canary_harness` | **synthetic end-to-end chain test** — прогоняет искусственный кейс через всю цепочку (candidate → reconciler → source_attribution → tracker → link map → hints → speaker graph → speaker_context) и возвращает безопасные агрегаты + leak_check |
| `canary_readiness_analysis` | **real-logs readiness report** — читает `SOURCE_RECONCILE_TRACE` + `SIGNAL_ENGINE_TRACE`, строит единый вердикт + blockers/warnings + suggested_patch |

Оба выводят ТОЛЬКО агрегаты. Никакого raw text / speaker labels / source ids / channel ids /
segment ids в stdout/result. Synthetic text — только in-memory для similarity. Сторона приходит
ТОЛЬКО из `speaker_identity_hints` поверх stable link; source/channel = зона записи, не сторона/личность.

## Запуск harness

```bash
cd meridian-web/backend
../.venv/Scripts/python.exe -m app.core.context.source_reconcile_canary_harness --scenario all
../.venv/Scripts/python.exe -m app.core.context.source_reconcile_canary_harness --scenario safe_match --active
../.venv/Scripts/python.exe -m app.core.context.source_reconcile_canary_harness --case-file path/to/case.json
```
Встроенные сценарии: `safe_match`, `shadow_match`, `unsafe_primary_blocked`, `ambiguous_blocked`,
`no_hint_unknown`, `low_similarity_rejected`, `time_only_strict`. Exit: 0 успех; 2 нет `--case-file`;
3 невалидный case (безопасная ошибка, без дампа). В result: `would_attach_without_shadow`,
`actual_attach`, `speaker_audio_stable_link_count`, `speaker_side_counts`, `speaker_context_chars`,
`speaker_context_hash`, `public_payload_contains_source_attribution` (всегда false), `leak_check` (всё false).

## Запуск analyzer

```bash
../.venv/Scripts/python.exe -m app.core.context.canary_readiness_analysis /path/to/app.log
```
Exit: 0; 2 файл не найден. Пустые логи → `verdict=no_data`.

## Verdicts

| verdict | смысл | что делать |
|---|---|---|
| `no_data` | нет trace events | включить логи на встречах, повторить |
| `ready_for_shadow_collection` | есть signal events, нет reconcile | включить multi_channel_live + собрать SOURCE_RECONCILE_TRACE (shadow) |
| `not_ready` | reconcile есть, но blockers (no_candidates/low_overlap/low_text_similarity/ambiguous/low score) | устранить blockers, собрать ещё shadow |
| `ready_for_active_source_reconcile_canary` | would_attach>0, без blockers | применить `suggested_patch` на ОДНОЙ канареечной встрече |
| `active_canary_running` | actual_attach>0 | мониторить actual_attach + unknown_side_event_rate; не расширять |

## Применить suggested_patch

`PATCH /api/meetings/{meeting_id}/ai-settings` телом из `suggested_patch`, например:
```json
{
  "source_reconcile_enabled": true,
  "source_reconcile_shadow_mode": false,
  "source_reconcile_min_text_similarity": 0.78,
  "source_reconcile_min_time_overlap": 0.45,
  "source_reconcile_min_match_score": 0.62,
  "source_reconcile_ambiguity_margin": 0.08
}
```
Откат — те же ключи `null` (см. [source_reconciliation_canary.md](source_reconciliation_canary.md)).

## Operations toolkit (Stage 13)

Для практического запуска canary на ОДНОЙ встрече (фильтрация по `meeting_id`, готовые
shadow/active/rollback PATCH JSON) — [canary_operations.md](canary_operations.md):
```bash
python -m app.core.context.canary_operations plan /path/to/app.log --meeting-id 123
python -m app.core.context.canary_operations emit-active /path/to/app.log --meeting-id 123
```
Readiness тоже умеет фильтровать по встрече, чтобы не смешивать verdict разных встреч:
```bash
python -m app.core.context.canary_readiness_analysis /path/to/app.log --meeting-id 123 --require-single-meeting
```

## Safety

- source/channel/track = зона записи, НЕ сторона и НЕ личность; сторону даёт только `speaker_identity_hints`.
- Нет вывода стороны из текста/токенов; нет raw text/source ids/speaker labels/segment ids в выводе.
- harness leak_check проверяет сериализованный result на raw values (сами values не печатает).
- public payload (`to_wire_full`/`public_committed_segment_payload`) НЕ содержит `source_attribution`.
- active source_reconcile — только на одной canary-встрече через session override; глобально shadow=true.
- Нет БД-миграций, нет LLM, нет network calls; runtime-поведение не меняется.
