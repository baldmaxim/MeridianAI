# Source Reconciliation — Canary Controls + Calibration Trace (Stage 11)

Делает Source Attribution Reconciliation ([source_attribution_reconciliation.md](source_attribution_reconciliation.md))
управляемым и калибруемым: global config flags, hidden per-meeting overrides, shadow mode и
отдельный безопасный `SOURCE_RECONCILE_TRACE` + offline-анализатор.

## Что добавляет Stage 11

- Глобальные флаги `AI_SOURCE_RECONCILE_*` (enabled/shadow/пороги/лимиты/trace).
- Hidden per-meeting canary override (`source_reconcile_*` в meeting AI settings snapshot).
- **Shadow mode по умолчанию (true):** candidates принимаются, matches считаются, trace пишется,
  но `source_attribution` НЕ прикрепляется → безопасный rollout, никакого тихого attach на всех встречах.
- `SOURCE_RECONCILE_TRACE` — отдельная строка лога на попытку reconcile (только агрегаты/категории).
- `source_reconcile_trace_analysis` — offline CLI для калибровки порогов.

## Три разных shadow/слоя — не путать

| Слой | Что делает | shadow=true |
|---|---|---|
| **Signal Engine shadow** | контекстная классификация ситуации | классифицирует, но подсказки идут по старому flow |
| **Source Reconcile shadow** (Stage 11) | сопоставляет source candidate ↔ committed segment | считает would_attach, пишет trace, но НЕ прикрепляет source_attribution |
| **speaker_identity_hints** | задаёт сторону для source/channel | сторона приходит ТОЛЬКО отсюда (не из reconcile) |

Reconciliation НЕ даёт сторону. Она лишь привязывает `speaker_label` к технической зоне записи
(source/channel) через stable link; сторону даёт hint поверх этой привязки.

## Как включить active reconciliation на одной встрече

`PATCH /api/meetings/{id}/ai-settings` (нужен `can_record_meeting`):
```json
{
  "source_reconcile_shadow_mode": false,
  "source_reconcile_enabled": true,
  "source_reconcile_min_text_similarity": 0.78,
  "source_reconcile_min_time_overlap": 0.45,
  "source_reconcile_min_match_score": 0.62,
  "source_reconcile_ambiguity_margin": 0.08
}
```
В логах: `[SourceReconcileCanary] meeting_id=… user_id=… changed_keys=[…]` (только имена ключей).

## Как вернуть к global defaults

```json
{
  "source_reconcile_shadow_mode": null,
  "source_reconcile_enabled": null,
  "source_reconcile_min_text_similarity": null,
  "source_reconcile_min_time_overlap": null,
  "source_reconcile_min_match_score": null,
  "source_reconcile_ambiguity_margin": null
}
```
`null` (или отсутствие ключа) = «использовать global config». Если глобально
`AI_SOURCE_RECONCILE_SESSION_OVERRIDES_ENABLED=false` — все per-meeting overrides игнорируются (kill-switch).

## Как читать SOURCE_RECONCILE_TRACE

Маркер: `SOURCE_RECONCILE_TRACE {json}`. Ключевые поля:
- `would_attach_without_shadow` — прикрепили бы вне shadow (главный сигнал «сколько»);
- `actual_attach` — реально прикрепили (shadow off);
- `decision_reason` (disabled/shadow_mode/allowed/low_overlap/ambiguous/…), `match_reason`;
- `match_score`, `time_overlap`, `text_similarity`, `attribution_confidence`;
- `candidate_source`/`source_kind`/`attribution_source` — только enum-категории;
- `thresholds`, `overrides_applied`, `latency_ms`.

raw text / speaker labels / source ids / channel ids / segment ids / имена — НЕ логируются.

## CLI-анализатор

```bash
cd meridian-web/backend
../.venv/Scripts/python.exe -m app.core.context.source_reconcile_trace_analysis /path/to/app.log
```
Выводит JSON: would/actual rates, by_decision_reason/by_match_reason/by_candidate_source/by_source_kind,
перцентили score/overlap/similarity/confidence, `threshold_candidates` (под target attach rates),
notes. Перед включением active canary смотреть: `would_attach_rate`, `by_match_reason`
(no_candidates/low_overlap/low_text_similarity/ambiguous), `score.p50`, `threshold_candidates`.

## Readiness harness + combined analyzer (Stage 12)

Перед включением active canary: synthetic end-to-end harness и combined readiness analyzer
(`SOURCE_RECONCILE_TRACE` + `SIGNAL_ENGINE_TRACE` → verdict + `suggested_patch`). См.
[canary_readiness.md](canary_readiness.md):
```bash
python -m app.core.context.source_reconcile_canary_harness --scenario all
python -m app.core.context.canary_readiness_analysis /path/to/app.log
```

## Safety

- Нет вывода стороны; нет raw text/source ids/labels в логах/trace.
- primary/room-mic / generic-токен без isolation по-прежнему заблокированы.
- source/channel = зона записи, не личность; текст — только техническое совпадение сегментов.
- `bridge_segment_source_attribution` — явный internal вызов, НЕ подчиняется shadow (ставит attribution напрямую).
- Без active canary (shadow=true глобально) reconcile не прикрепляет ничего на других встречах.
