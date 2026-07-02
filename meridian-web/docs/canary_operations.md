# Canary Operations Toolkit (Stage 13)

Backend-only tooling для практического запуска source_reconcile canary на **ОДНОЙ** встрече:
фильтрация trace по `meeting_id`/`session_id`/`check_id`, безопасный canary plan и готовые PATCH
JSON (shadow / active / rollback). Поверх [canary_readiness.md](canary_readiness.md) (Stage 12).

Tool **ничего не применяет сам**: только печатает JSON для ручного `PATCH /api/meetings/{id}/ai-settings`.

> Per-channel STT (Stage 17–19) имеет ОТДЕЛЬНЫЙ canary-контур: `per_channel_stt_canary_operations` /
> `per_channel_stt_canary_monitor` (или `canary_operations monitor-per-channel-stt`). Сначала довести
> per-channel STT до candidate-emission (source_reconcile остаётся shadow), и лишь ПОТОМ — source_reconcile
> active canary этим tool. См. [per_channel_stt_canary_operations.md](per_channel_stt_canary_operations.md).
>
> Перед rollout — единый **field report** по одной встрече (`canary_operations field-report --meeting-id`):
> audio/per-channel/cost/source_reconcile/hints/signal + safe next-patch. См.
> [field_canary_report.md](field_canary_report.md).

## Почему нельзя анализировать смешанный app.log без `--meeting-id`

Один `app.log` содержит trace многих встреч. Без фильтра:
- readiness verdict смешивает разные встречи (одна готова, другая нет);
- `actual_attach>0` на одной встрече даёт verdict `active_canary_running` и **маскирует** встречи,
  которые ещё в shadow.

Поэтому readiness/plan считаем **по одной встрече**: `--meeting-id <id>`. Анализатор добавляет
warning, если в логе несколько meeting_id, а фильтр не задан; `--require-single-meeting` делает
это жёсткой ошибкой (exit 4).

> meeting_id используется только для фильтрации. В выводе — `trace_scope` (counts/флаги) и
> `trace_filters.filter_hashes` (sha256), **не** сырые списки id.

## Canary lifecycle

1. **shadow collection** — применить `emit-shadow` patch на встрече (reconcile включён, attach НЕ
   происходит): `source_reconcile_enabled=true`, `source_reconcile_shadow_mode=true`, `trace_enabled=true`.
2. **collect** — провести несколько сессий, собрать `SOURCE_RECONCILE_TRACE` + `SIGNAL_ENGINE_TRACE`.
3. **readiness by meeting** — `plan <log> --meeting-id <id>`: verdict + blockers/warnings + patch'и.
4. **active на ОДНОЙ встрече** — если verdict `ready_for_active_source_reconcile_canary`, применить
   `active_source_reconcile_patch` (`shadow_mode=false`) только на этой встрече.
5. **monitor** — `active_canary_monitor <log> --meeting-id <id>` (Stage 14): status/recommendation,
   `actual_attach_rate`, `score_p50`, `unknown_side_event_rate`; см.
   [active_canary_monitoring.md](active_canary_monitoring.md).
6. **rollback** — `emit-rollback` patch (или `rollback_patch` из монитора при `rollback_recommended`)
   обнуляет source_reconcile_* → встреча возвращается к global defaults.

## Команды

```bash
cd meridian-web/backend
# 1. shadow collection patch (лог не нужен)
../.venv/Scripts/python.exe -m app.core.context.canary_operations emit-shadow

# 3. план по одной встрече
../.venv/Scripts/python.exe -m app.core.context.canary_operations plan /path/app.log --meeting-id 123

# 4. только active patch (exit 4, если не ready)
../.venv/Scripts/python.exe -m app.core.context.canary_operations emit-active /path/app.log --meeting-id 123

# 5. мониторинг active canary (Stage 14; или прямой модуль active_canary_monitor)
../.venv/Scripts/python.exe -m app.core.context.canary_operations monitor /path/app.log --meeting-id 123

# 6. rollback patch (лог не нужен)
../.venv/Scripts/python.exe -m app.core.context.canary_operations emit-rollback
```

Exit codes: `0` ок; `2` файл не найден; `3` неверные аргументы; `4` not ready (для `emit-active`)
или несколько meeting_id при `--require-single-meeting` (у readiness CLI).

## Применить PATCH вручную

Patch из вывода → телом в `PATCH /api/meetings/{meeting_id}/ai-settings` (нужен `can_record_meeting`).
Tool печатает `endpoint_template` с **placeholder** `{meeting_id}` — id подставляет оператор, чтобы
не утёк в артефакты. Пример active patch:
```json
{
  "source_reconcile_enabled": true,
  "source_reconcile_shadow_mode": false,
  "source_reconcile_min_text_similarity": 0.78,
  "source_reconcile_min_time_overlap": 0.45,
  "source_reconcile_min_match_score": 0.9,
  "source_reconcile_ambiguity_margin": 0.08
}
```

## Что tool НЕ делает

- не применяет patch (только печатает JSON);
- не включает Signal Engine active mode (`signal_engine_shadow_mode=false` никогда не ставит);
- не меняет и не очищает `speaker_identity_hints`;
- не ходит в сеть, не читает БД, не вызывает LLM;
- не печатает `curl` с токеном и не подставляет meeting_id в endpoint.

## Rollback

- `source_reconcile_*` ключи → `null` возвращают встречу к global defaults (Stage 11 семантика
  «отсутствие ключа/None = global config»).
- `speaker_identity_hints` **не** очищаются автоматически (стороны/маппинги сохраняются).
- `signal_engine_*` **не** трогаются.

## Safety

- source/channel/track = техническая зона записи, **не** сторона и **не** личность.
- Сторона появляется только через `speaker_identity_hints` поверх stable link — tool её не выводит
  и не угадывает по тексту.
- В выводе нет raw text / source ids / speaker labels / channel ids / segment ids / candidate ids;
  meeting/session id даются как counts/hashes, не списком.
- `safety_checks` в плане проверяют сериализованный план на запрещённые ключи/подстроки.
- Patch'и валидируются через существующий `ai_settings.validate_patch` (без раскрытия содержимого
  в случае ошибки — только имя класса исключения).
