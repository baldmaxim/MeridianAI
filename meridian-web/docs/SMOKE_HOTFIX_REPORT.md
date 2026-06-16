# Smoke / Hotfix Report — MeridianAI (AI-output layer + Conversation Tree)

Дата: 2026-06-16 · Стенд: `meridian.fvds.ru`

## 1. Summary

**Что было сломано.** После завершения MVP (1/10–10/10) и стендового деплоя обнаружены 4 бага
AI-выходного слоя: все вызовы LLM падали из-за не-ASCII HTTP-заголовка (A); подсказка с
прикреплённым S3-документом крашилась на `len(None)` (B); Deepgram-транскрипт отображался, но не
сохранялся, из-за чего финализация видела пустой транскрипт (C); переключение default AI-профиля
периодически давало 500 из-за порядка flush (D). Итог: живые подсказки, финализация и авто-обучение
де-факто не работали.

**Что исправлено.** Все 4 бага устранены одним hotfix-коммитом, плюс задеплоены ранее
подготовленные коммиты Conversation Tree и persisted speaker roles. Применены миграции 0013/0014.

**Итоговый статус: ✅ AI-output layer восстановлен.** Smoke-шаги 7 (подсказки), 9 (финализация),
10 (обучение) — зелёные на проде. Стенд рабочий.

## 2. Environment

| Параметр | Значение |
|---|---|
| Стенд | https://meridian.fvds.ru (environment=production, v0.10.0) |
| Backend image | `ghcr.io/baldmaxim/meridian-api:5779e7bc…` (api + worker), `meridian-frontend:5779e7bc…` |
| Commit (HEAD на сервере) | `5779e7bc5c179b13b61d9524f623e57334c3b24a` |
| Alembic revision | `0014` (head) |
| DB | Yandex Managed PostgreSQL (`Meridian_AI`) — runtime; миграции — отдельным шагом (migration role) |
| S3 | configured, reachable=true |
| STT | Deepgram (configured) |
| LLM | OpenRouter (configured), модель `google/gemini-3-flash-preview` |

> Деплой — образы из GHCR (immutable SHA-tag), без сборки на VDS. Соседние сервисы VPS
> (Keycloak/nginx/Xray/Supabase/remnawave) не затронуты. Секреты в отчёте не приводятся.

## 3. Deployed commits

| Commit | Назначение |
|---|---|
| `c8acd2a` | feat(meetings): add live conversation tree panel |
| `a1d90b2` | fix(meetings): persist speaker roles for conversation tree |
| `5779e7bc` | fix(ai): restore LLM outputs and Deepgram transcript persistence (баги A/B/C/D) |

## 4. Bugs fixed

### A — Non-ASCII HTTP header ломал все вызовы LLM · CRITICAL
- **Root cause.** `core/llm/client.py` — заголовок `X-Title: "Meridian — AI Negotiation Helper"`
  содержал em-dash (U+2014). HTTP-заголовки кодируются как latin-1/ASCII → каждый запрос к OpenRouter
  падал: `'ascii' codec can't encode character '—' in position 9`.
- **Affected flows.** Live/manual подсказки, финализация, learning extraction — всё, что зовёт LLM.
- **Fix.** Заголовки вынесены в константу `OPENROUTER_APP_HEADERS`; em-dash заменён на ASCII-дефис
  (`Meridian - AI Negotiation Helper`).
- **Verification.** Юнит-тест на ASCII-кодируемость всех заголовков; на проде `X-Title` ASCII,
  ноль `ascii/codec`-ошибок в логах, LLM реально возвращает контент (шаги 7/9/10).

### B — `len(doc.content)` при `content=None` (S3-документы) · CRITICAL
- **Root cause.** `core/context/document_loader.py:242,268` делал `len(doc.content)`. S3-документы
  (DocumentRecord/DocumentChunk) не имеют inline-`content` → `TypeError: object of type 'NoneType'
  has no len()`; `request_suggestion` с документом крашился.
- **Affected flows.** Live/manual подсказки при прикреплённом документе (основной MVP-сценарий).
- **Fix.** None-guard в обоих методах (пустой content пропускается); на месте загрузки в legacy-loader
  S3-документы пропускаются — их текст подаётся через DocumentChunk-провайдер
  (`build_meeting_doc_context`).
- **Verification.** Юнит-тесты на `content=None`; на проде подсказка с `.md`-документом вернула
  карточки с `evidence source=document` (шаг 7), без `NoneType`-ошибок.

### C — Deepgram-транскрипт не сохранялся → empty transcript при финализации · HIGH
- **Root cause.** `services/meeting_room.py:_persist_segments` сохраняет только
  `session.committed_segments`. ElevenLabs-путь их наполняет, а Deepgram/legacy-путь
  (`_on_legacy_transcript`) — нет. Итог: live transcript на экране есть, но в БД 0 сегментов →
  `finalize: meeting N partial (empty transcript)`.
- **Affected flows.** Финализация и авто-обучение на дефолтном STT (Deepgram).
- **Fix.** В `_on_legacy_transcript` финальные (не partial) legacy-сегменты конвертируются в
  `CommittedSegment` (`_legacy_to_committed`) и кладутся в `_committed_segments` — независимо от
  WS-рассылки; партиалы/пустые пропускаются (без дублей); ElevenLabs-путь не затронут.
- **Verification.** Юнит-тест (legacy-финал → committed-store) + DB-тест (persisted сегмент →
  непустой транскрипт). На проде: 5 сегментов в БД, финализация `completed` (шаг 9).

### D — `make_default` нарушал partial-unique `uq_ai_profile_default` · MEDIUM
- **Root cause.** `services/ai_settings.py:make_default` ставил новый default и снимал старый в одном
  flush; порядок UPDATE'ов (по PK) мог дать два `is_default=true` одновременно — детерминированно
  падало, когда id целевого профиля < id текущего default (`duplicate key … uq_ai_profile_default`).
- **Affected flows.** Переключение default AI-профиля (500).
- **Fix.** Сначала снять `is_default` со всех прочих → `flush()` → затем выставить целевой → `flush()`.
- **Verification.** Тест порядка flush (unset-before-set) + интеграционный тест «ровно один default».

## 5. Smoke results

### Step 7 — Suggestions ✅
Встреча (Deepgram) + прикреплённый ready `.md` (ВОР) → стрим русского аудио → manual suggestion.
- 2 карточки, **не fallback**: `type=trade_concession` (conf 0.9) и `type=clarify` (conf 0.9);
  legacy-поля `text/type/confidence` присутствуют.
- **evidence:** `source=document` (цитата «Бетон М300: цена 62 000 тенге за кубометр») + `source=transcript`.
- Логи api/worker: ноль `ascii / NoneType / Traceback`.

### Step 9 — Finalization ✅
Live-встреча (Deepgram) → запись реплик → завершение через WS `finalize_meeting`.
- transcript segments в БД: **5** (Bug C устранён).
- `finalization_status = completed` (не `partial`, не `empty transcript`).
- Протокол: `title`, `micro_summary`, `tags=[бетон, переговоры, цена, договор подряда]`,
  `protocol_markdown` (836 симв.), `decisions=0, action_items=0, risks=1, open_questions=2`.
- Worker: `finalize: meeting 15 completed (decisions=0, actions=0, risks=1)`; ноль ascii/traceback.
- `decisions/action_items=0` — корректно: монолог одной стороны без зафиксированных решений/задач.

### Step 10 — Learning extraction ✅
Встреча → финализация → авто-extraction → approve → knowledge → новая встреча.
- `learning_status` отработал; **candidates = 4**: `trigger_phrase, playbook, counterparty_trait,
  trigger_phrase`.
- Approve `trigger_phrase` → элемент в `/api/knowledge/triggers` (`matched_new=1`).
- Новая встреча по тому же customer/object получила approved knowledge в prompt context (см. §6).
- Логи: LLM реально вызван (job ~10s), ноль ascii/traceback.

## 6. Learning extraction proof

- **Кандидаты.** `learning_extract: meeting 16 → 4 candidates` (worker, ~10s, LLM вызван).
- **Approve.** Кандидат `trigger_phrase` «Давление на сроки и гарантии» → HTTP 200.
- **Knowledge.** `/api/knowledge/triggers` содержит элемент:
  `phrase = "беспокоят сроки поставки материала и гарантийные обязательства"`,
  `event_type = deadline_pressure`.
- **Prompt context injection (deterministic).** Для новой встречи `build_meeting_knowledge_context(m2)`
  вернул блок (238 симв.):
  ```
  Триггерные фразы и реакция:
  - Если звучит «беспокоят сроки поставки материала и гарантийные обязательства» (deadline_pressure)
    → Запросить конкретные требования к SLA по поставкам и уточнить риски по гарантии.
  ```
  `contains approved trigger: True` — approved-знание реально попадает в промпт новой встречи.
- **Nuance по evidence.** В live-подсказке новой встречи evidence карточки = `['transcript']` — LLM не
  атрибутировал триггер как evidence. Это ожидаемо: knowledge-блок присутствует в промпте (доказано
  прямым вызовом провайдера), но цитирование его как evidence — на усмотрение модели.

## 7. Database / migrations

- Прод был на **alembic 0012**; после деплоя — **0014** (применено отдельным шагом, migration role).
- Применены `0013` (conversation tree + AI-toggle) и `0014` (speaker roles); цепочка
  `0012 → 0013 → 0014`, обе миграции обратимы (`downgrade()` присутствует).
- Новые объекты схемы (проверены на runtime-БД):
  - таблица `meeting_conversation_topics` (+ индексы) — Conversation Tree;
  - таблица `meeting_speaker_roles` (+ индекс) — persisted speaker roles;
  - колонка `ai_settings_profiles.conversation_tree_enabled` (bool, default true).
- Jobs: dead/failed = 0.

## 8. Remaining limitations

- Approved knowledge попадает в prompt context, но **LLM не всегда атрибутирует** его как `evidence`
  (источник в карточке может остаться `transcript`).
- **Conversation Tree** зависит от корректного назначения speaker roles (сторона «мы/оппонент»);
  при дефолтной диаризации спикеры могут быть `Unknown` — карта позиций будет беднее.
- **Redis/pub-sub** ещё нет — live-комнаты держатся в памяти процесса (single-VM); горизонтальное
  масштабирование WS требует отдельного шага.
- **Public SaaS hardening** (Keycloak OIDC §6, observability/Sentry frontend §8, нагрузочное тестирование)
  — вне рамок этого hotfix-цикла, отдельным этапом.
- Резервный backup перед миграцией снят с локального postgres-контейнера; для данных Yandex
  использовать штатные снапшоты Managed PostgreSQL (миграции 0013/0014 аддитивные и обратимые).

## 9. Cleanup

- Тестовые встречи / объекты / заказчики (SMOKE7/9/10) — удалены.
- Approved trigger («deadline_pressure») — заархивирован (`/knowledge/triggers/{id}/archive`).
- Остальные learning-кандидаты — rejected.
- Тестовые пользователи (`smoke-*`, role=user) остаются (нет self-deactivate без admin) — безвредны.

## 10. Final MVP acceptance status

- ✅ MVP-стенд рабочий: health ok, `llm_configured=true`, `stt_configured=true`, `s3_configured=true`,
  alembic 0014, dead/failed jobs = 0.
- ✅ AI-output layer восстановлен: подсказки (с document evidence), финализация (с протоколом),
  авто-обучение (кандидаты → knowledge → prompt context) — подтверждены вживую.
- ✅ Conversation Tree / speaker roles задеплоены (схема на месте).
- **Готово к переходу к итоговой документации / roadmap** (Keycloak, observability, scaling, SaaS-hardening).
