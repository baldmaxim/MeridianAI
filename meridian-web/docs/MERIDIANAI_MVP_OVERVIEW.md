# MeridianAI — обзор MVP (v0.11.0)

> **Версия:** 0.11.0 · **Стенд:** https://app.example.com · **Статус:** MVP baseline (production-deployed)
>
> Итоговый документ для разработчика и руководителя. Фиксирует текущее устройство продукта
> в точке v0.11.0 — опорный baseline для дальнейшего развития.

---

## 1. Краткое описание продукта

**MeridianAI** — AI-ассистент для переговоров в строительной сфере. Слушает разговор в
реальном времени, расшифровывает его (speech-to-text) и по ходу встречи выдаёт менеджеру
структурированные подсказки: что сказать, о чём спросить, какой риск зафиксировать,
где не уступать. После встречи автоматически собирает протокол и накапливает знания по
заказчику/объекту, которые используются в следующих переговорах.

- **Что делает.** Realtime-транскрипция → структурированные LLM-подсказки с доказательствами →
  дерево обсуждённых тем → финальный протокол (решения, задачи, риски, открытые вопросы) →
  контролируемое накопление знаний.
- **Для кого.** Менеджеры и инженеры строительной компании, ведущие переговоры с заказчиками
  (цена, сроки, гарантии, объёмы, договор, доп. работы).
- **Главная ценность.** Не «расшифровка ради расшифровки», а **поддержка решений по ходу
  встречи** + автоматический протокол + **память** по каждому заказчику и объекту: каждая
  следующая встреча начинается уже с накопленным контекстом.

---

## 2. Основной пользовательский сценарий

1. **Подготовка встречи.** Менеджер создаёт встречу, задаёт тему, заметки, свою роль и
   слабые места оппонента (manual context).
2. **Выбор заказчика/объекта.** Встреча привязывается к `Customer` и `ProjectObject` —
   это определяет, какие документы и какие накопленные знания подтянутся в контекст.
3. **Документы.** К объекту/встрече прикладываются договоры, ВОР, сметы (PDF/Excel/Word).
   Файлы грузятся напрямую в S3 по presigned-ссылке, фоновый worker извлекает текст и
   режет его на чанки (`DocumentChunk`).
4. **Previous meetings.** Менеджер выбирает 2–5 предыдущих встреч с этим заказчиком —
   их сводки (решения, договорённости) войдут в контекст подсказок и протокола.
5. **Телефон-диктофон.** Телефон подключается к той же встрече в роли `phone` и работает
   микрофоном: пишет аудио и шлёт его в комнату. Desktop при этом — экран с подсказками.
6. **Desktop-подсказки.** На ноутбуке менеджер видит живую расшифровку, дерево тем и
   карточки-подсказки (`SuggestionCard`) с доказательствами. Можно запросить подсказку
   вручную или «усилить позицию» (strengthen).
7. **Завершение.** Менеджер останавливает запись и завершает встречу.
8. **Протокол.** Запускается фоновая финализация (`meeting_finalize`): LLM строит протокол —
   title, micro-summary, теги, решения, задачи, риски, открытые вопросы.
9. **Learning.** Отдельный фоновый job (`learning_extract`) предлагает кандидатов в знания
   (термины, триггеры, плейбуки, черты заказчика, стоп-фразы). Они **не применяются
   автоматически** — менеджер подтверждает или отклоняет.
10. **Новая встреча — уже «с памятью».** Подтверждённые знания и сводки прошлых встреч
    автоматически подмешиваются в контекст следующих переговоров с этим заказчиком/объектом.

---

## 3. Архитектура

```
                         ┌──────────────────────────────────────┐
   Desktop (React)  ─────┤                                       │
   Phone   (React)  ─────┤   WebSocket  /ws/meetings/{meeting_id} │
   Viewer / Participant  │            (один MeetingRoom)          │
                         └───────────────┬──────────────────────┘
                                         │
                              ┌──────────▼───────────┐        ┌──────────────┐
                              │  FastAPI backend     │◄──────►│ PostgreSQL    │
                              │  REST + WS handler   │ async  │ (asyncpg)     │
                              │  SessionManager      │        │ Alembic       │
                              └───┬───────────┬──────┘        └──────────────┘
                                  │           │                       ▲
                  STT providers   │           │  enqueue jobs         │ DML
        (Deepgram/ElevenLabs/     │           ▼                       │
         Gemini/Speechmatics)     │   ┌───────────────┐        ┌──────┴───────┐
                                  │   │ jobs (PG)     │◄──────►│   Worker     │
                  LLM (OpenRouter)│   │ outbox/queue  │ claim  │ python -m    │
                                  ▼   └───────────────┘        │ app.worker   │
                          ┌──────────────┐                     └──────┬───────┘
                          │  S3 (presign │◄───── presigned PUT/GET ────┘
                          │  PUT/GET)    │       (документы, batch-аудио)
                          └──────────────┘
```

- **Frontend** — React 19.2 + TypeScript + Vite 7.3 + Zustand 5.0.11. Состояние встречи —
  `store/meetingStore.ts`. Хуки: `useWebSocket` (комната/роль устройства), `useAudioRecorder`
  (захват PCM 16 kHz через AudioWorklet).
- **Backend** — FastAPI + SQLAlchemy async. REST API (`/api/...`) + WebSocket-ядро
  (`app/ws/handler.py`). Бизнес-логика встречи — в `app/services/` и `app/core/`.
- **Worker** — отдельный процесс `python -m app.worker`. Берёт задачи из PG-таблицы `jobs`
  (паттерн jobs/outbox, §16: claim `FOR UPDATE SKIP LOCKED`, ретраи с backoff, восстановление
  «зависших»).
- **PostgreSQL** — единственная БД (asyncpg). Схема — только через Alembic-миграции
  (без `create_all`/ad-hoc ALTER в проде).
- **S3-совместимое хранилище** — документы и batch-аудио. Браузер грузит/качает напрямую по
  presigned-ссылкам; backend байты файлов не проксирует.
- **WebSocket** — `/ws/meetings/{meeting_id}?token=<jwt>&device_role=<role>`. Аудио — binary
  frames; команды и события — JSON.
- **Провайдеры:** STT — Deepgram / ElevenLabs / Gemini / Speechmatics (выбор через настройки);
  LLM — OpenRouter (OpenAI-совместимый API).

---

## 4. Ключевые сущности

| Сущность | Таблица | Назначение |
|---|---|---|
| `Customer` | `customers` | Заказчик (контрагент). Корень привязки знаний/документов. |
| `ProjectObject` | `project_objects` | Объект (стройка/проект) заказчика. |
| `Department` | `departments` | Отдел; доступы сотрудников к объектам. |
| `MeetingSession` | `meeting_sessions` | Встреча: метаданные, статус, протокол, привязки к customer/object, снапшот AI-настроек. |
| **MeetingRoom** | — *(in-memory)* | Живая комната встречи по `meeting_id`. **Не таблица БД** — состояние в процессе backend. |
| `MeetingParticipant` | `meeting_participants` | Участники встречи (many-to-many встреча↔пользователи) + их роль. |
| `DocumentRecord` | `documents` | Загруженный документ (S3-ключ, статус обработки, метаданные). |
| `DocumentChunk` | `document_chunks` | Фрагмент текста документа для контекста (chunk_index, страница/лист, токены). |
| `MeetingContextSource` | `meeting_context_sources` | Источник контекста встречи (документ / прошлая встреча и т.п.), флаг `included` и приоритет. |
| `MeetingConversationTopic` | `meeting_conversation_topics` | Тема обсуждения для дерева: сводки и последние реплики обеих сторон, refs. |
| `MeetingSpeakerRole` | `meeting_speaker_roles` | Привязка спикера к стороне (наша/заказчик/…) — источник истины для дерева. |
| `AISettingsProfile` | `ai_settings_profiles` | Профиль AI-настроек (модели, режим, toggles, лимиты). |
| `LearningCandidate` | `learning_candidates` | Кандидат в знания (status=pending до подтверждения человеком). |
| `GlossaryTerm` | `glossary_terms` | **Знание:** термин/определение (scope global/customer/object). |
| `TriggerPhrase` | `trigger_phrases` | **Знание:** фраза-триггер события переговоров + рекомендуемая реакция. |
| `NegotiationPlaybook` | `negotiation_playbooks` | **Знание:** ситуация → рекомендуемая фраза/техника + что просить взамен. |
| `CounterpartyTrait` | `counterparty_traits` | **Знание:** черта заказчика/объекта + стратегия. |
| `ForbiddenPhrase` | `forbidden_phrases` | **Знание:** что НЕ говорить + лучшая альтернатива. |

Сопутствующие: `User`, `ApiKey`, `UserSettings`, `UserIdentity`, `ObjectAccessGrant`,
`TranscriptSegmentRecord`, `MeetingSuggestion`, `MeetingDocumentRecord`, `FileRecord`,
`BatchJob`, протокольные таблицы (`meeting_decisions`, `meeting_action_items`,
`meeting_risks`, `meeting_open_questions`), `Job`, `AuditLog`.

---

## 5. Live-встреча

- **MeetingRoom по `meeting_id`.** На каждую активную встречу — одна in-memory комната
  (`app/services/meeting_room.py`): `RoomRegistry` (реестр `meeting_id → MeetingRoom`,
  потокобезопасный per-meeting lock) + `SessionManager` (STT/LLM-движок комнаты).
- **Multi-device.** К одной комнате подключаются несколько устройств; роль задаётся при
  подключении (`device_role`):
  - `desktop` — экран с расшифровкой, деревом и подсказками;
  - `phone` — телефон-микрофон (диктофон);
  - `viewer` — наблюдатель (без записи);
  - `participant` — участник.
- **Active audio source.** В каждый момент **только одно** подключение является источником
  аудио (`is_active_audio_source`). Устанавливается командой `start_audio`, снимается при
  `stop_audio` или отключении.
- **Broadcast.** События комнаты (расшифровка, статусы записи, подключение/отключение
  устройств, обновления дерева, подсказки) рассылаются всем подключениям.
- **Phone recorder.** Телефон в роли `phone` шлёт binary-аудио в комнату; desktop получает
  расшифровку и подсказки через broadcast. События: `phone_recording_started/stopped`,
  `audio_source_disconnected`.
- **Права записи.** `can_send_audio` = роль ∈ {`desktop`, `phone`} **И** у пользователя есть
  право записывать встречу (`can_record_meeting`). `viewer`/`participant` аудио не шлют.

---

## 6. Контекст встречи

Контекст, который подмешивается в подсказки и в протокол, собирается из нескольких слоёв
(все управляются toggle'ами AI-профиля):

1. **Manual meeting context** — заданные менеджером поля: `meeting_topic`, `meeting_notes`,
   `meeting_role` (наша сторона), `opponent_weaknesses`, `negotiation_type`.
2. **Документы** — релевантные `DocumentChunk` из приложенных документов (лимит чанков/символов
   зависит от режима профиля).
3. **Previous meetings** — сводки 2–5 выбранных прошлых встреч (решения, договорённости).
4. **Approved knowledge** — подтверждённые знания (`GlossaryTerm`/`TriggerPhrase`/
   `NegotiationPlaybook`/`CounterpartyTrait`/`ForbiddenPhrase`), отфильтрованные по scope:
   `global` / `customer` / `object`.
5. **AI settings toggles** — каждый слой можно выключить на уровне профиля/встречи:
   `document_context_enabled`, `knowledge_context_enabled`,
   `previous_meetings_context_enabled` и др.

---

## 7. Подсказки

- **SuggestionCard** — структурированная карточка (`app/schemas/suggestion.py`):
  - `type` — `say_now` / `ask` / `counter` / `risk` / `fixation` / `trade_concession` /
    `pause` / `clarify` / `summarize`;
  - `priority` (важность), `title`, `text` (готовая фраза), `why` (обоснование);
  - `evidence[]` — массив доказательств;
  - `confidence` (0–1), `needs_user_check` (флаг «проверь перед использованием»),
    `source_mode`.
- **Evidence (доказательства).** Каждое со ссылкой на источник: `transcript` (таймкод MM:SS),
  `document` (имя + страница/раздел), `meeting_context`, `previous_meeting`, `playbook`,
  `protocol`, `unknown`.
- **Fallback.** Если структурированный ответ не получен/невалиден — срабатывает резервный
  путь по ключевым словам (цена, срок, гарантия, договор…) со статус-сообщением.
- **Режимы:**
  - `auto` — автоподсказки по детектору событий/ключевым словам (с debounce и cooldown,
    можно отключить на встречу);
  - `manual` — подсказки по запросу (несколько разнотипных карточек);
  - `strengthen` — «усилить позицию»: полноконтекстный стратегический ответ (стриминг).
- **Safety guards** (`app/services/suggestion_parser.py`): высокий confidence без evidence —
  понижается и помечается на проверку; ссылка на документ с неизвестным ref — флаг;
  категоричные утверждения («по договору», «обязан») без доказательства — ограничение
  confidence; уступка (`trade_concession`) без условия («если», «в обмен») — флаг.

---

## 8. Conversation Tree (дерево обсуждения)

- **Две колонки — «Мы» / «Заказчик».** По каждой теме видно позицию обеих сторон
  (`our_summary` / `opponent_summary`, последние реплики, refs с таймкодами).
- **Grouping / upsert.** Реплики детерминированно (без LLM) раскладываются по темам-ключам
  (`price`, `deadlines`, `payment`, `contract`, `documents`, `warranty`, `quality`,
  `responsibility`, `volumes`, `extra_work`, `supply`, `other`). Новая тема — создаётся,
  существующая — дополняется (rolling summary + ref).
- **Speaker roles.** Сторона реплики определяется по `MeetingSpeakerRole`
  (`self`/`opponent` → наша/заказчик; `ally` → наша; `third_party` → пропускается).
- **Refs.** По каждой стороне хранятся последние сегменты-ссылки (segment_id, спикер,
  таймкод, текст).
- **Ручное редактирование.** Статус темы, проставленный пользователем (sticky), переживает
  автообновления; роли спикеров можно править.
- **Rebuild.** После правки ролей дерево пересобирается из сохранённых сегментов
  (`rebuild_from_segments`).
- **Вход в финализацию.** Компактная карта позиций по темам передаётся в контекст протокола.

---

## 9. Финализация

- **Job `meeting_finalize`** (`app/services/meeting_finalize.py`). По завершении встречи в
  очередь ставится фоновая задача; LLM строго по фактам строит протокол.
- **Вход:** метаданные встречи, транскрипт (с усечением длинных), релевантные чанки
  документов, карта позиций из дерева, сводки прошлых встреч.
- **Результат** (`MeetingFinalizationResult`):
  - `protocol_markdown` / `protocol_json` — протокол для экспорта/хранения;
  - `decisions` — решения (со статусом и доказательствами);
  - `action_items` — задачи (исполнитель/срок/статус);
  - `risks` — риски (severity + доказательства);
  - `open_questions` — открытые вопросы;
  - `title`, `micro_summary`, `tags`, `meeting_type`.
- **Хранение.** Поля протокола — в `meeting_sessions`; структурированные части —
  в отдельных таблицах `meeting_decisions` / `meeting_action_items` / `meeting_risks` /
  `meeting_open_questions`.
- **Статусы:** `queued` → `running` → `completed` | `partial` | `error`
  (+ `finalized_at`). При невалидном JSON — попытка ремонта, иначе `partial` с ошибкой.

---

## 10. Controlled learning (контролируемое обучение)

- **Job `learning_extract`** (`app/services/learning_extract.py`) запускается после
  финализации: из протокола и встречи извлекаются кандидаты в знания.
- **Pending candidates.** Кандидаты сохраняются как `LearningCandidate` со
  `status=pending` и **не применяются автоматически**. Типы: `term`, `trigger_phrase`,
  `playbook`, `counterparty_trait`, `forbidden_phrase`.
- **Approve / reject.** Менеджер просматривает кандидатов в UI: при подтверждении —
  создаётся запись в соответствующей knowledge-таблице (status=approved); при отклонении —
  кандидат отбрасывается.
- **Approved knowledge.** Подтверждённые знания подмешиваются в контекст будущих встреч
  (с учётом scope global/customer/object).
- **Future prompts.** Так система «учится» по каждому заказчику/объекту, оставаясь под
  контролем человека (human-in-the-loop).

---

## 11. Настройки AI

- **AI profiles** (`AISettingsProfile`). Профиль задаёт STT-провайдера/модель, LLM-модели
  (live-подсказки, strengthen, финализация, learning), режим, toggles и лимиты.
- **Meeting snapshot.** На старте встречи разрешённые настройки «замораживаются» в
  `ai_settings_snapshot_json` — модель/провайдер не меняются в середине сессии.
- **Режимы `fast` / `balanced` / `deep`** — пресеты «глубины»: число карточек, объём
  контекста документов, число прошлых встреч, интервал автоподсказок и др.

  | Режим | auto/manual карточек | чанков док-в | прошлых встреч | min интервал авто |
  |---|---|---|---|---|
  | fast | 1 / 3 | 3 | 2 | 30 c |
  | balanced | 2 / 5 | 6 | 5 | 20 c |
  | deep | 2 / 5 | 10 | 5 | 20 c |

- **Toggles.** `auto_suggestions_enabled`, `suggestion_structured_enabled`,
  `document_context_enabled`, `knowledge_context_enabled`,
  `previous_meetings_context_enabled`, `finalization_enabled`,
  `learning_extraction_enabled`, `conversation_tree_enabled`.
- **Лимиты.** `max_auto_cards` / `max_manual_cards`, `document_context_max_chunks` /
  `…_max_chars`, `previous_context_max_meetings` / `…_max_chars`,
  `knowledge_context_max_items`, `auto_suggestion_min_interval_seconds`.
- **Приоритет резолва настроек:** snapshot встречи → профиль, назначенный встрече →
  дефолтный профиль пользователя → базовые значения из конфигурации.

---

## 12. Деплой и эксплуатация

- **Health-эндпоинты:**
  - `GET /health/live` — liveness (процесс жив);
  - `GET /health/ready` — readiness (готовность; на нём стоит деплой-гейт);
  - `GET /api/health` — публичный rich-статус: version, database, флаги
    `s3_configured` / `llm_configured` / `stt_configured`;
  - `GET /api/health/deep` — глубокая диагностика (db, alembic current/head, S3, jobs) —
    admin/dev;
  - `GET /api/health/jobs` — счётчики очереди по статусам; `POST /api/health/jobs/recover-stale`
    — ручное восстановление зависших задач;
  - `GET /api/health/config-summary` — безопасная сводка конфигурации (без секретов).
- **Worker.** Отдельный процесс `python -m app.worker`; обрабатывает `batch_transcribe`,
  `document_process`, `meeting_finalize`, `learning_extract`, `file_physical_delete`.
- **Миграции.** Только Alembic, **отдельным шагом** деплоя (`alembic upgrade head`),
  не из app-контейнера. Изменение схемы = новая миграция (миграции не правятся задним числом).
- **S3.** Загрузка/скачивание через presigned PUT/GET; ключи генерируются сервером
  (`meridian/{user_id}/{purpose}/{uuid}{ext}`), backend байты не проксирует.
- **CI/GHCR (рабочий путь).** push в `main` → GitHub Actions собирает образы → GHCR →
  на vds `deploy-ghcr.sh` (pull образов, миграции, рестарт api/worker/frontend/edge).
  Сборка на проде запрещена (только готовые образы).
- **Rollback.** Передеплой предыдущим immutable-тегом: `TAG=<prev-sha> ./deploy.sh`.
- **Portal-scoped.** Деплой Meridian не трогает nginx, Keycloak и соседние сервисы на хосте
  — принцип no-neighbor-damage.

---

## 13. Текущий статус v0.11.0

- **Version:** `0.11.0` (`backend/app/config.py`, `APP_VERSION`).
- **Миграции:** Alembic head — `0014_speaker_roles` (0001…0014).
- **Провайдеры:** STT / LLM / S3 сконфигурированы (видно по флагам `/api/health`:
  `stt_configured`, `llm_configured`, `s3_configured`).
- **Smoke:** зелёный (см. `docs/SMOKE_HOTFIX_REPORT.md`).
- **AI-output восстановлен:** возвращены вывод LLM-подсказок и персист транскрипта Deepgram
  (commit `5779e7b` — *fix(ai): restore LLM outputs and Deepgram transcript persistence*).
- **Стенд:** https://app.example.com (production-deployed).

---

## 14. Ограничения MVP

- **MeetingRoom — in-memory.** Состояние комнаты живёт в одном процессе backend; нет
  горизонтального масштабирования комнат и переживания рестартов «вживую».
- **Нет Redis / pub-sub.** Broadcast — внутри процесса; multi-instance fan-out не реализован.
- **Полноценного SaaS-RBAC ещё нет.** Изоляция данных — по `owner_user_id` (+ гранты на
  объекты), а не по `organization_id`; ролевая модель уровня tenant — впереди.
- **Embeddings нет.** Подбор чанков документов — без векторного поиска (keyword/эвристики),
  не семантический.
- **Conversation Tree зависит от speaker roles.** Без корректно проставленных ролей спикеров
  раскладка «Мы / Заказчик» страдает (нужен rebuild после правок).
- **Атрибуция evidence в знаниях зависит от модели.** Качество ссылок/доказательств в
  кандидатах знаний определяется LLM и требует проверки человеком.
- **Нагрузочного тестирования ещё нет.** Поведение под конкуррентной нагрузкой/многими
  комнатами не измерялось.

---

## 15. Roadmap после MVP

1. **Redis-backed rooms** — вынести состояние комнат и broadcast в Redis (pub/sub),
   масштабирование и устойчивость к рестартам.
2. **organization_id + RBAC** — переход на tenant-модель и полноценные роли/права.
3. **Embeddings / hybrid search** — векторный + гибридный поиск по документам и знаниям.
4. **Экспорт DOCX / PDF** — выгрузка протокола в офисные форматы.
5. **Observability / Sentry (frontend)** — фронтовый мониторинг ошибок, uptime, дашборды.
6. **Audit trail** — расширение аудита действий (`audit_log`).
7. **Rate limiting / quotas** — лимиты на API и потребление AI.
8. **Keycloak / OIDC в production** — целевой SSO (AUTH_MODE с фоллбэком на local).
9. **Security hardening** — донастройка по корп-стандарту перед SaaS.
10. **Load testing** — нагрузочные сценарии (много комнат/устройств/задач).
