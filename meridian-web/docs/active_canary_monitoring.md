# Active Canary Monitor + Rollback Recommendation (Stage 14)

Backend-only мониторинг **активной** source_reconcile canary-встречи: читает
`SOURCE_RECONCILE_TRACE` + `SIGNAL_ENGINE_TRACE`, фильтрует по `meeting_id`/`session_id`/`check_id`
(Stage 13), оценивает качество `actual_attach` и выдаёт безопасную рекомендацию + готовый
**rollback patch** (не применяет). Часть canary-цепочки поверх
[canary_operations.md](canary_operations.md) и [canary_readiness.md](canary_readiness.md).

## Когда запускать

После применения `active_source_reconcile_patch` (Stage 13 `emit-active`, `shadow_mode=false`) на
ОДНОЙ встрече — чтобы понять, безопасно ли продолжать или нужен откат. Анализ только по одной
встрече (`--meeting-id`), иначе verdict смешает встречи.

## Команды

```bash
cd meridian-web/backend
../.venv/Scripts/python.exe -m app.core.context.active_canary_monitor /path/app.log --meeting-id 123
../.venv/Scripts/python.exe -m app.core.context.active_canary_monitor /path/app.log --meeting-id 123 --emit-rollback-if-needed
../.venv/Scripts/python.exe -m app.core.context.active_canary_monitor /path/app.log --meeting-id 123 --require-single-meeting
# эквивалент через operations-CLI:
../.venv/Scripts/python.exe -m app.core.context.canary_operations monitor /path/app.log --meeting-id 123
```
Exit: `0` ок; `2` файл не найден; `3` неверные аргументы; `4` несколько meeting_id при
`--require-single-meeting`.

## status

| status | смысл |
|---|---|
| `no_data` | нет trace events вообще |
| `shadow_only` | reconcile в shadow (would_attach есть, attach нет) или нет SOURCE_RECONCILE_TRACE |
| `collecting` | active attach начался, но событий мало / нет candidates |
| `healthy` | active attach, выборка достаточна, blockers нет |
| `warning` | active attach, hard-blockers нет, но низкое покрытие hints / проблемы качества без attach |
| `rollback_recommended` | active attach с деградацией — рекомендуется откат |

## primary_recommendation

| рекомендация | когда |
|---|---|
| `remain_in_shadow` | нет данных / нет source reconcile / shadow считает would, attach не идёт |
| `collect_more_data` | мало событий / много no_candidates |
| `continue_active` | active attach здоров |
| `rollback_source_reconcile` | active attach деградировал (см. ниже) |
| `add_speaker_identity_hints` | active attach ок, но roles в основном unknown, hints не покрывают sources |
| `tighten_thresholds` | высок low_text_similarity / ambiguous |
| `check_multichannel_timestamps` | высок low_overlap (расходятся timestamp-шкалы каналов) |

## Что смотреть

- `source_reconciliation.actual_attach_rate` — доля сегментов, которым реально прикрепили source.
- `source_reconciliation.actual_to_would_ratio` — насколько shadow-прогноз совпал с active.
- `source_reconciliation.ambiguous_rate` / `low_overlap_rate` / `low_text_similarity_rate`.
- `source_reconciliation.score_p50` / `score_p90` — **по would-attach population** (качество именно
  прикрепляемых матчей, не занижено законно отклонёнными room-mic-сегментами).
- `speaker_context.unknown_side_event_rate` / `hint_source_event_rate` / `audio_linked_event_rate`.
- `signal_engine.timeout_exception_rate` / `latency_p95_ms` — информационные warnings (Signal Engine
  сам по себе rollback source reconcile НЕ вызывает).

### Когда рекомендуется rollback

Только при `active_state="active_attaching"` (actual_attach>0) и любом из:
- `ambiguous_rate > 0.10`;
- `low_overlap_rate > 0.25`;
- `low_text_similarity_rate > 0.25`;
- `score_p50 < 0.65`;
- `actual_attach_rate > 0.25` (слишком агрессивный attach);
- active attach при `unknown_side_event_rate > 0.7` + `hint_source_event_rate < 0.2` + высоком
  `audio_linked_event_rate` (links есть, hints не покрывают, attach активен).

### Когда рекомендуется add_speaker_identity_hints

active attach без hard-blockers, но `unknown_side_event_rate > 0.5` и `hint_source_event_rate < 0.2`
(или severe coverage gap не настолько критичный, чтобы откатывать) → лучше добавить явные hints, чем
откатывать.

## Как откатить

```bash
../.venv/Scripts/python.exe -m app.core.context.active_canary_monitor /path/app.log --meeting-id 123 --emit-rollback-if-needed
```
Если `rollback_recommended=true` — взять `rollback_patch` из output и вручную:
`PATCH /api/meetings/{meeting_id}/ai-settings` (id подставляет оператор; tool печатает
`rollback_endpoint_template` с placeholder).

Rollback **очищает** только `source_reconcile_*` overrides (возврат к global defaults). **НЕ
очищает** `speaker_identity_hints` и **не трогает** `signal_engine_*`.

## Canary lifecycle (полный)

1. `emit-shadow` → собрать shadow trace;
2. `plan` / `readiness` → verdict `ready_for_active_source_reconcile_canary`;
3. `emit-active` → применить active patch на ОДНОЙ встрече;
4. **`active_canary_monitor`** → отслеживать здоровье, ловить деградацию;
5. `emit-rollback` / `rollback_patch` → откат при `rollback_recommended`.

## Safety

- tool **не применяет** patch, не ходит в сеть, не читает БД, не вызывает LLM;
- source/channel/track = техническая зона записи, **не** сторона и **не** личность;
- сторона приходит только через `speaker_identity_hints` поверх stable link — tool её не выводит и
  по тексту не угадывает;
- Stage 14 raw text не читает и не выводит; в output нет raw text / source ids / speaker labels /
  channel ids / segment ids / candidate ids; meeting/session id даются как counts/hashes;
- `safety_checks` в отчёте проверяют сериализованные data-поля на запрещённые подстроки;
- глобальный Signal Engine rollout не включается; `signal_engine_*` не трогается.
