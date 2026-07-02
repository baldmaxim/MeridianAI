# Signal Engine — канареечное включение на одной встрече

Документ для backend/операторов. Frontend здесь не участвует.

## Что делает canary override

Signal Engine (контекстная классификация переговорной ситуации) по умолчанию работает в
**shadow-режиме**: классифицирует и пишет `SIGNAL_ENGINE_TRACE` в логи, но подсказки
по-прежнему идут по старому event/keyword flow. Поведение пользователя не меняется.

Canary override позволяет включить **live** Signal Engine (реальные подсказки от сигнала)
для **одной конкретной встречи**, не трогая глобальные флаги и другие встречи. Override
хранится в snapshot настроек встречи (per-meeting), а не в профиле AI и не в глобальном config.

Ключи override (скрытые, не показываются в UI как «профиль» или «режим»):

| Ключ | Тип | Смысл |
|---|---|---|
| `signal_engine_enabled` | bool/null | вкл/выкл слой для встречи |
| `signal_engine_shadow_mode` | bool/null | `false` = live-подсказки от сигнала |
| `signal_engine_allow_legacy_fallback` | bool/null | при техническом сбое разрешить старый flow |
| `signal_engine_min_confidence` | 0..1/null | порог уверенности |
| `signal_engine_min_actionability` | 0..1/null | порог «есть конкретное действие» |
| `signal_engine_min_urgency` | 0..1/null | порог срочности |
| `signal_engine_trace_enabled` | bool/null | писать ли trace |
| `signal_engine_trace_sample_rate` | 0..1/null | доля логируемых проверок |
| `signal_engine_llm_timeout_seconds` | 1..60/null | таймаут классификации |

`null` (или отсутствие ключа) = «использовать глобальный config».

## Что НЕ меняется при глобальном shadow=true

- Глобальные дефолты остаются безопасными: `AI_SIGNAL_ENGINE_ENABLED=true`,
  `AI_SIGNAL_ENGINE_SHADOW_MODE=true`. Live signal-подсказки глобально **не включены**.
- Встречи без override продолжают работать как раньше (старый event/keyword flow).
- Override применяется, только если глобально `AI_SIGNAL_ENGINE_SESSION_OVERRIDES_ENABLED=true`.
  Если выставить его в `false` — все per-meeting signal overrides игнорируются (kill-switch).

## Как включить live Signal Engine на одной встрече

`PATCH /api/meetings/{meeting_id}/ai-settings` (нужны права записи встречи — `can_record_meeting`):

```json
{
  "signal_engine_shadow_mode": false,
  "signal_engine_enabled": true,
  "signal_engine_min_confidence": 0.65,
  "signal_engine_min_actionability": 0.65,
  "signal_engine_min_urgency": 0.45
}
```

В логах появится строка вида `[SignalCanary] meeting_id=... user_id=... changed_keys=[...]`
(только имена ключей, без значений и без текста переговоров).

## Как вернуть встречу к global defaults

Передать те же ключи со значением `null` — override очистится, встреча вернётся к глобальному config:

```json
{
  "signal_engine_shadow_mode": null,
  "signal_engine_enabled": null,
  "signal_engine_min_confidence": null,
  "signal_engine_min_actionability": null,
  "signal_engine_min_urgency": null
}
```

## Что смотреть в логах (калибровка)

Маркер строки: `SIGNAL_ENGINE_TRACE {json}`. Ключевые поля:

- `would_prompt_without_shadow` — сработала бы подсказка вне shadow (главный сигнал «сколько раз»).
- `decision_reason` — почему показали/смолчали (`allowed`/`shadow_mode`/`low_confidence`/…).
- `situation_type` — тип ситуации (price_pressure, liability_shift, …).
- `novelty_key` — ключ дедупликации; частый повтор = возможные дубли.
- `score` — сводная сила сигнала (для подбора порогов).
- `error_kind` — доля технических сбоев / невалидных ответов модели.
- `latency_ms` — задержка классификации (под таймаут).

Offline-сводка по логам:

```bash
cd meridian-web/backend
../.venv/Scripts/python.exe -m app.core.context.signal_trace_analysis /path/to/app.log
```

Выводит JSON-сводку (rates, распределения, перцентили score/latency, кандидаты порогов, notes).

## Предупреждение по безопасности

- **`signal_engine_trace_include_text` НЕ включать на реальных переговорах.** По умолчанию
  trace не содержит текста переговоров — только длины, hash и агрегаты.
- Включить `trace_include_text` через meeting override **нельзя** без явного глобального
  разрешения `AI_SIGNAL_ENGINE_SESSION_TRACE_TEXT_OVERRIDE_ALLOWED=true`. По умолчанию запрещено:
  даже если передать `signal_engine_trace_include_text=true` в snapshot, resolver его проигнорирует.
