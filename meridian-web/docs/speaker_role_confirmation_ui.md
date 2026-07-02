# Подтверждение ролей и сторон участников (Этап 21)

Лёгкий операторский UI на live-странице встречи: панель **«Роли и стороны»**. Оператор ЯВНО
подтверждает, кто относится к нашей стороне / контрагенту / третьей стороне, и (опционально)
функциональную роль голосов транскрипта и каналов записи. Результат сохраняется в существующий
скрытый механизм `speaker_identity_hints` (Этап 4/5) поверх snapshot AI-настроек встречи.

Это **не** AI-профиль, **не** выбор режима ассистента, **не** автоопределение стороны. Сторона
появляется только после подтверждения оператором.

## Что делает

- Показывает **строгие** метки спикеров из транскрипта (`SM_0`, `Speaker 1`, `SPEAKER_1`, `S_1`,
  `МЫ`/`НЕ МЫ`/`OUR_SIDE`/`COUNTERPARTY`/`THIRD_PARTY`). Произвольные метки-имена («Иван:»,
  «Менеджер:») игнорируются — это PII/свободный текст, а не стабильный ключ.
- Показывает **каналы записи** (`channel_0`, `channel_1`, …), если запись мультиканальная
  (`actualChannelCount ≥ 2`) или включён multichannel shadow (Этап 15/16). Канал = техническая
  зона записи, **не** сторона.
- Для каждой строки — выбор стороны (`наша / контрагент / третья / — не указано —`) и функциональной
  роли (ЛПР, РП, инженер, технадзор, снабжение, юрист, финансы, продажи, подрядчик, заказчик,
  наблюдатель).
- Кнопки: **Сохранить роли** (PATCH только `speaker_identity_hints`), **Сбросить назначения**
  (PATCH `{speaker_identity_hints: null}`), **Обновить список** (перечитать транскрипт + серверные
  назначения).
- Секция **«Сохранённые назначения»** — что сейчас реально хранится на сервере.

## Формат сохранения

PATCH `/api/meetings/{id}/ai-settings` телом только:

```json
{
  "speaker_identity_hints": {
    "speaker_labels": { "SM_0": { "side": "our_side", "functional_role": "decision_maker",
                                  "confidence": 0.95, "source": "manual_correction" } },
    "audio_sources":  { "channel_0": { "side": "counterparty", "functional_role": "unknown",
                                       "confidence": 0.75, "source": "audio_channel" } },
    "channel_labels": { "channel_1": { "side": "third_party", "functional_role": "observer",
                                       "confidence": 0.75, "source": "audio_channel" } }
  }
}
```

- `speaker_label` → группа `speaker_labels`, `source=manual_correction`, conf 0.95.
- канал → группа `audio_sources`/`channel_labels`, `source=audio_channel`, conf 0.75.
- строки со стороной `unknown` или выключенные — **пропускаются**.
- backend (`normalize_identity_hints`) финально нормализует/клампит и **выбрасывает PII**
  (`display_name`/`organization`/`raw_speaker_label` не сохраняются).
- неуправляемые UI-группы существующих hints (например `stable_ids`) переносятся как есть — PATCH
  заменяет всё значение snapshot, поэтому фронт их сохраняет, чтобы не затереть.

## Как это влияет на подсказки

`speaker_identity_hints` — вход Speaker Identity Graph (Этап 4). Явно подтверждённая сторона
повышает приоритет источника (`manual_correction`) над диаризацией/каналом при разрешении, кто
«наш», а кто «контрагент». Никакой LLM-инференс стороны по тексту не выполняется.

## Что НЕ делает

- не создаёт «карточку человека» / AI-профиль;
- не угадывает сторону по содержанию реплик;
- не сохраняет имена, организации, идентификаторы устройств;
- не меняет STT/LLM-настройки, режим, Signal Engine, source_reconcile, per-channel STT;
- не блокирует старт/ход встречи (ошибки неблокирующие);
- не трогает старую панель `SpeakerSideAssignmentPanel` и WS `set_speaker_role`.

## Файлы

- `frontend/src/features/speakerIdentity/speakerIdentityTypes.ts` — типы и опции сторон/ролей.
- `frontend/src/features/speakerIdentity/speakerIdentityHints.ts` — чистые утилиты (строгие метки,
  черновики каналов, сборка/очистка патча, слияние с сохранёнными).
- `frontend/src/components/meeting/SpeakerIdentityReviewPanel.tsx` — панель.
- `frontend/src/api/aiSettings.ts` — `patchMeetingSpeakerIdentityHints`.
- Backend без изменений: schema/validate_patch/GET/логирование групп — с Этапа 5.

## Логирование

PATCH логирует только группы (без меток/значений/имён):
`[SpeakerIdentityHints] meeting_id=… user_id=… changed=true cleared=<bool> groups=[…]`.

## Безопасность

- В hint нет PII — только техническая зона + сторона + функц. роль + confidence + source.
- Канал/источник = техническая зона записи, не сторона и не личность.
- Права на изменение — как на редактирование встречи (`can_record_meeting`); без прав панель
  доступна только на просмотр.
