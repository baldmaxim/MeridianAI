# Speaker Identity Graph v1

Внутренний backend-слой нормализации ролей спикеров (Этап 4). Без UI, без БД-миграций,
без LLM-инференса ролей. Полностью backward-compatible с legacy self/opponent.

## Зачем

Раньше «сторона говорящего» смешивалась с техническим источником звука и legacy-метками.
Граф разводит три РАЗНЫХ понятия, чтобы Signal Engine не путал «кто говорит» с «откуда звук»:

| Понятие | Что это | Примеры значений |
|---|---|---|
| **device_role** | технический источник аудио/канал | desktop, phone, secondary, observer |
| **speaker_side** | переговорная сторона | our_side, counterparty, third_party, unknown |
| **functional_role** | функция участника | decision_maker, engineer, procurement, legal, ... |

Ключевой принцип: `device_role != speaker_side != functional_role`. «desktop» НЕ значит «наша
сторона»; «Speaker 1» НЕ значит «оппонент». Нет данных → `side="unknown"`, низкий confidence.

## Маппинг legacy self/opponent → новые стороны

| legacy | new side |
|---|---|
| self / us / our / мы | `our_side` |
| opponent / not_self / client / customer / заказчик | `counterparty` |
| third_party / observer / external / наблюдатель | `third_party` |
| (неизвестно) | `unknown` |

Обратный маппинг для совместимости (`side_to_legacy`): our_side→self, counterparty→opponent,
third_party→opponent, unknown→unknown. Существующий API (`speaker_roles.py`,
`SpeakerSideAssignmentPanel`, ручные назначения) не меняется — граф читает их как вход.

Источники (`SpeakerIdentitySource`) и доверие:
- подтверждённые пользователем роли → `manual_correction` (confidence ~0.95);
- прочие persisted-роли → `legacy_role` (~0.85);
- метки из транскрипта → `transcript_label` (confidence 0.0, side=unknown);
- device/channel → `device_role`, **только weak hint**, confidence ≤ 0.55, side остаётся unknown.

## Как влияет на Signal Engine

`SessionManager._signal_flow` строит runtime `SpeakerIdentityMap` (без БД/LLM) и компактный
`speaker_context` и передаёт его в:
- `SignalEngine.classify(..., speaker_context=...)` — модель использует роли как ГЛАВНЫЙ
  источник сторон, не угадывает по метке, не путает device_role со стороной;
- `build_auto_cards_prompt_from_signal(..., speaker_context=...)` — подсказка всегда адресована
  нашей стороне; при `speaker_side=unknown` предпочтительны clarify/fixation, а не агрессивный
  counter; если counterparty просит уступку — обмен (trade_concession).

Если роли неизвестны — `speaker_context` пуст, и промпт явно пишет «Роли участников неизвестны.
Не делай жёстких предположений о стороне говорящего.»

## Что НЕ делаем на этом этапе

- UI / фронтенд изменения;
- DB migration / новые таблицы;
- LLM-инференс ролей (граф собирается из уже имеющихся данных);
- распознавание лиц / личностей (face/person identity).

## Что смотреть в trace (SIGNAL_ENGINE_TRACE)

Только агрегаты (имена/метки/сырой текст ролей НЕ логируются):
- `speaker_side_counts` — сколько спикеров по сторонам (our_side/counterparty/third_party/unknown);
- `speaker_average_confidence` — средняя уверенность графа;
- `speaker_sources` — распределение источников (manual_correction/legacy_role/transcript_label/...);
- `speaker_context_chars` — длина контекста (есть ли роли вообще).

Offline-сводка (`signal_trace_analysis`) добавляет блок `speaker_context`:
`events_with_speaker_context`, `avg_speaker_confidence_p50`, `unknown_side_event_rate`, `by_source`,
плюс notes при `unknown_side_event_rate > 0.5` или `avg_speaker_confidence_p50 < 0.6`.
