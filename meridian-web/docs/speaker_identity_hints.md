# Speaker Identity Hints v1

Скрытый per-meeting механизм явного маппинга speaker labels / audio sources / channel labels
на переговорную сторону. Backend-only: без UI, без БД-миграций, без LLM-инференса ролей.
Дополняет Speaker Identity Graph v1 ([speaker_identity_graph.md](speaker_identity_graph.md)).

## Зачем

В реальных встречах без явных назначений `unknown_side_event_rate` высок, и Signal Engine
не знает, кому адресовать подсказку. Hints дают backend-способ явно сказать:
- `SM_0` = наша сторона (project_manager);
- `Speaker 2` = заказчик (counterparty);
- зона записи `primary`/`left` = наша сторона, `secondary`/`right` = контрагент.

Без угадывания: «Speaker 1» НЕ оппонент по умолчанию, «desktop» НЕ наша сторона.

## Отличие от AI-профилей

Это **не профиль** и не пользовательский выбор. Профили (`AISettingsProfile`) — это видимые
настройки модели/режима. Hints — скрытый per-meeting/canary override в snapshot встречи,
не отображается в UI, не входит в `AISettingsProfileCreate/Update/Out`. Живёт только в
`MeetingAISettingsPatch`/`AISettingsResolved` и snapshot конкретной встречи.

## Как задать

`PATCH /api/meetings/{meeting_id}/ai-settings` (нужны права записи встречи):

```json
{
  "speaker_identity_hints": {
    "speaker_labels": {
      "SM_0":      {"side": "our_side",    "functional_role": "project_manager", "confidence": 0.95, "source": "manual_correction"},
      "Speaker 2": {"side": "counterparty","functional_role": "customer",        "confidence": 0.9}
    },
    "stable_ids": {
      "speaker_a1b2c3d4": {"side": "our_side", "functional_role": "engineer", "confidence": 0.9}
    },
    "audio_sources": {
      "primary":   {"side": "our_side",    "confidence": 0.75, "source": "audio_channel"},
      "secondary": {"side": "counterparty","confidence": 0.75, "source": "audio_channel"}
    },
    "channel_labels": {
      "left":  {"side": "our_side",    "confidence": 0.75},
      "right": {"side": "counterparty","confidence": 0.75}
    }
  }
}
```

В логах: `[SpeakerIdentityHints] meeting_id=… user_id=… changed=true cleared=false groups=[…]`
(только имена групп, без labels/значений/имён).

## Как очистить

```json
{ "speaker_identity_hints": null }
```

## Как влияет на граф

`SpeakerIdentityService.build_runtime_map` накладывает hints поверх базовой карты. Приоритет:
1. `manual_overrides` / подтверждённые роли (`self.speaker_roles`);
2. `identity_hints.speaker_labels` / `stable_ids` (source=manual_correction, conf ≤ 0.98);
3. legacy roles;
4. `identity_hints.audio_sources` / `channel_labels` — **только** при наличии связи
   source/channel → label через metadata (conf ≤ 0.85). Без связи не применяются (не выдумываем);
5. метки из `recent_dialog` (unknown, conf 0.0);
6. device hints (weak, conf ≤ 0.55, side=unknown).

Конфликты решает `merge_speaker_identity` по приоритету источника/уверенности —
`manual_correction` всегда бьёт `audio_channel`/`transcript_label`.

## Ограничения

- Нет UI, нет БД-миграций, нет LLM-инференса ролей.
- `display_name` / `organization` в hint **не принимаются и не хранятся** (без PII в snapshot).
- `raw_speaker_label` внутри hint не нужен — ключ dict уже является label/source id.
- audio_source/channel hint — это **зона записи (канал/источник), а не доказанная личность**;
  применяется только при явной metadata-связке, иначе игнорируется.
- side=unknown в hint не превращается в уверенное назначение (confidence обнуляется).

## Что смотреть в trace / анализе

В `SIGNAL_ENGINE_TRACE` (только агрегаты, без меток/имён):
- `speaker_count`, `speaker_unknown_side_count`, `speaker_hint_source_count`;
- `speaker_side_counts`, `speaker_sources`, `speaker_average_confidence`.

В `signal_trace_analysis` → `speaker_context`:
- `hint_source_event_rate` (доля событий с явными hints), `hint_source_count_p50`;
- `unknown_side_event_rate`, `avg_speaker_confidence_p50`, `speaker_count_p50`, `by_source`.

Notes для калибровки: низкий `hint_source_event_rate` (<0.2) → «мало явных hints»;
`unknown_side_event_rate` > 0.5 → «улучшить role assignment»;
`avg_speaker_confidence_p50` < 0.6 → «низкая уверенность графа».
