# Deploy Checklist — MeridianAI (MVP)

Деплой — portal-scoped (не трогает nginx/Keycloak/соседей VPS). Сборка локально/в CI,
на проде — только готовые образы (§19). Схема БД — только Alembic (§8).

## Перед деплоем
- [ ] Прогнаны `pytest` (backend) и `npm run build` (frontend) — зелёные
- [ ] `alembic heads` — ровно одна голова; `alembic upgrade head` / `downgrade -1` оффлайн ок
- [ ] Образы собраны (CI/GHCR) с immutable-тегами
- [ ] `.env` на проде заполнен (DATABASE_URL, JWT_SECRET, ENCRYPTION_KEY, S3_*, и т.д.)

## Деплой
1. [ ] **Бэкап БД** до миграции: `pg_dump`/снапшот тома
2. [ ] Применить миграции отдельным шагом: `alembic upgrade head`
3. [ ] Проверить ревизию: `alembic current` → head (0012)
4. [ ] Перезапустить backend (api) из нового образа
5. [ ] Перезапустить/запустить worker из нового образа (обязателен)
6. [ ] `GET /api/health/deep` (admin) — database ok, alembic current==head, s3 reachable, jobs ok

## Smoke после деплоя
7. [ ] `scripts/mvp_smoke.py` → PASS
8. [ ] Загрузить тестовый документ → статус `ready` (worker отработал)
9. [ ] Создать тестовую встречу (customer/object) → получает default AI-профиль
10. [ ] Phone recorder smoke: `/recorder/{id}` → старт записи → desktop видит транскрипт
11. [ ] Finalize smoke: завершить встречу → протокол `completed/partial` (или `disabled`, если выключено)
12. [ ] Learning smoke: кандидаты появились → approve один → знание в базе
13. [ ] Access-control smoke: view-only видит, но не меняет; no-access получает 403/404
14. [ ] Failure smoke: остановить worker → документ остаётся `processing`, UI показывает статус (не падает)

## Откат (rollback)
- [ ] Откатить образы api/worker на предыдущий immutable-тег
- [ ] При необходимости откатить миграцию: `alembic downgrade <prev>` (миграции 0006–0012 обратимы)
- [ ] Восстановить БД из бэкапа, если миграция повредила данные
- [ ] Проверить `/api/health/deep`

## Заметки
- Деплой Meridian не трогает Keycloak/nginx и соседние сервисы на хосте
- Worker — отдельный процесс; без него документы/финализация/обучение не выполняются
- Зависшие job восстанавливаются при старте воркера и через `POST /api/health/jobs/recover-stale`
