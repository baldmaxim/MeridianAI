# Production cutover — авторитетный multi-channel transcript (Этап 9.8)

Перевод конкретной встречи с одноканального (single) STT на **авторитетный** multi-channel
транскрипт. Single STT остаётся всегда-включённым **горячим резервом**. Перевод — только
**вручную**, авто-promote отсутствует. По умолчанию всё **выключено** (rollout 0% + allowlist).

## Модель

- **Эпоха транскрипции** (`meeting_transcription_epochs`) — непрерывный отрезок server timeline
  с одним источником: `single` | `multi_channel`. Переключение = новая эпоха. Эпоха 0 при
  первом promote моделирует прошлый single-отрезок. Открытая эпоха одна (end NULL).
- **Авторитетный транскрипт** — для каждой эпохи берутся сегменты её источника в `[start, end)`:
  single → committed STT (по **speech-time**), multi → сохранённые multi-channel сегменты.
  На стыке источников — boundary-dedupe (одна реплика могла попасть в оба источника).
- **Multi-channel сегменты** (`meeting_multi_channel_segments`) — ТОЛЬКО нормализованный текст
  + сторона/канал/время/уверенность. Никогда raw/PCM/слова-с-аудио/ответ провайдера.
- **Speech-time метки** — `transcript_segments.speech_start_ms/speech_end_ms` (nullable):
  абсолютная server-эпоха РЕЧИ (якорь старта стрима + provider-relative), а не момент прихода
  committed-события. Нужны для корректной атрибуции к эпохам у границы.

## Флаги (env, по умолчанию выключено)

| Переменная | Default | Назначение |
|---|---|---|
| `MULTI_CHANNEL_CUTOVER_ENABLED` | `false` | Kill switch функции |
| `MULTI_CHANNEL_CUTOVER_ROLLOUT_PERCENT` | `0` | Canary % (детерминированный bucket по meeting_id) |
| `MULTI_CHANNEL_CUTOVER_ALLOWLIST_USER_IDS` | `` | CSV user_id — всегда доступно |
| `MULTI_CHANNEL_CUTOVER_ALLOWLIST_MEETING_IDS` | `` | CSV meeting_id — всегда доступно |
| `MULTI_CHANNEL_CUTOVER_REQUIRE_QUALITY_GATE` | `true` | Гейт качества перед promote |
| `MULTI_CHANNEL_CUTOVER_ALLOW_FORCE` | `true` | Разрешить force-обход quality-gate |
| `MULTI_CHANNEL_CUTOVER_MIN_FINAL_SEGMENTS` | `5` | Минимум финальных multi-сегментов |
| `MULTI_CHANNEL_CUTOVER_MIN_MATCH_RATIO` | `0.5` | Минимум совпадения с основным (reconciliation) |
| `MULTI_CHANNEL_CUTOVER_MAX_SECONDARY_SILENCE_RATIO` | `0.7` | Макс. тишина secondary-канала |
| `MULTI_CHANNEL_CUTOVER_AUTO_FALLBACK_ON_FAILURE` | `true` | Авто-откат при ЖЁСТКОМ сбое live |
| `MULTI_CHANNEL_CUTOVER_BOUNDARY_DEDUPE_MS` | `1500` | Окно дедупа на стыке источников |
| `MULTI_CHANNEL_CUTOVER_BOUNDARY_DEDUPE_SIMILARITY` | `0.6` | Порог похожести текста для дедупа |
| `MULTI_CHANNEL_CUTOVER_MAX_PERSISTED_SEGMENTS` | `20000` | DoS-guard на сохранение multi-сегментов |
| `MULTI_CHANNEL_CUTOVER_RECENT_MINUTES` | `5` | Окно «недавнего диалога» для подсказок |

Промежуточная раскатка: `ENABLED=true` + узкий `ALLOWLIST_MEETING_IDS`, либо
`ROLLOUT_PERCENT=5..100`. Полный откат — `ENABLED=false` (моментально снимает доступность
promote; уже открытые multi-эпохи закроются авто-fallback при сбое/перезапуске).

## Поток

1. Запустить live multi-channel STT (Этап 9.6), дождаться `streaming` и накопления финалов.
2. Открыть «Источник транскрипта (cutover)» → проверить quality (зелёный) и доступность раскатки.
3. Нажать **Перевести на multi-channel** (или `force`, если гейт не пройден и разрешён force).
   → создаётся эпоха multi; авторитетный транскрипт, Context Pack, дерево, финализация
   начинают использовать multi-источник; single продолжает писаться в резерв.
4. Откат: **Откатить на single STT** (ручной) — открывает single-эпоху.

## Авто-fallback и recovery

- **Hard failure**: live-сессия `failed`/`stopped` пока promoted → авто-fallback на single
  (если `AUTO_FALLBACK_ON_FAILURE=true`). Качество (тишина/несовпадение) **не** триггерит откат.
- **Restart recovery**: при пересоздании комнаты, если последняя эпоха multi и открыта (live
  не может работать после рестарта) → авто-fallback `recovery_fallback` на single.

## Аудит

`transcription_promote`, `transcription_fallback`, `transcription_auto_fallback`,
`transcription_cutover_recovery` — с `meeting_id`, `to_source`, `reason`, `automatic`.

## API

- `GET  /api/meetings/{id}/transcription-authority/state` — текущее состояние (доступ — viewer).
- `POST /api/meetings/{id}/transcription-authority/promote` `{force?}` — нужна активная сессия + право записи.
- `POST /api/meetings/{id}/transcription-authority/fallback` — право записи.
- `GET  /api/meetings/{id}/transcription-authority/transcript` — постхок авторитетный транскрипт из БД.

WS (additive): server→client `transcription_authority_state` / `transcription_authority_error`;
client→server `transcription_promote` / `transcription_fallback` / `get_transcription_authority`.

## Миграция

`0020_transcription_cutover` (после `0019`): nullable `speech_start_ms/speech_end_ms` в
`transcript_segments` + таблицы `meeting_transcription_epochs`, `meeting_multi_channel_segments`.
Аддитивно, существующие данные/поведение не затрагиваются. Применять отдельным шагом:
`alembic upgrade head`.

## Инварианты безопасности

- Single STT и его байты **не изменяются**; promote не трогает primary-пайплайн.
- Secondary-аудио не попадает в primary STT; raw/PCM/ключи не логируются и не сохраняются.
- Без эпох (99% встреч) поведение идентично до-cutover: `build_authoritative_from_db` → None,
  провайдер авторитета → None, прежние пути (committed/finalize/tree) без изменений.
