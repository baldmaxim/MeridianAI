# Корпоративный стандарт v3.1: single-VPS baseline для архитектуры, инфраструктуры, аутентификации и эксплуатации порталов

## 1. Назначение

Документ определяет корпоративный стандарт для web-порталов, backend API, frontend-приложений, фоновых задач, файлового хранения, централизованной аутентификации, deployment, мониторинга и интеграций.

Эта редакция стандарта фиксирует базовый сценарий первичного внедрения: **single-VPS deployment**. На первичном этапе используется один production VPS/VM в Yandex Compute Cloud. На нём размещаются reverse proxy, backend API, workers и Keycloak. Создание второй VPS/VM и Yandex Application Load Balancer на этом этапе **не требуется**.

Такой вариант считается базовым для быстрого и понятного запуска портала, если требования к отказоустойчивости допускают single point of failure на уровне runtime-сервера. При росте нагрузки или требований к доступности архитектура должна расширяться до HA-схемы отдельным инфраструктурным этапом: добавляется вторая VPS/VM, выносится ingress layer в управляемый L7-balancer и включается rolling deployment.

Стандарт фиксирует обязательные архитектурные решения:

- базовую инфраструктуру порталов;
- централизованную аутентификацию через Keycloak;
- интеграцию с Active Directory;
- модель пользователей сотрудников и подрядчиков;
- авторизацию пользователей и сервисов;
- SQL-first миграции;
- фоновые задачи и ретраи;
- загрузку, хранение и удаление файлов;
- transactional email;
- deployment flow;
- observability;
- хранение секретов;
- shared libraries и project templates.

Стандарт не фиксирует внутренние классы, второстепенные библиотеки и конкретные структуры таблиц, если они не влияют на безопасность, совместимость, эксплуатационную надёжность или переносимость между порталами.

---

## 2. Базовая production-архитектура

Базовая схема первичного внедрения — **один production VPS/VM**.

```text
Пользователи
   ↓ HTTPS
DNS A/AAAA records
   ├─ auth.example.com
   ├─ auth-admin.example.com
   ├─ api.portal-a.ru
   ├─ api.portal-b.ru
   └─ api.portal-c.ru
        ↓ один публичный IP
Yandex Compute Cloud / VPS
   └─ backend-vps-1
        ├─ nginx reverse proxy
        ├─ portal-a-api
        ├─ portal-a-worker
        ├─ portal-b-api
        ├─ portal-b-worker
        └─ keycloak
             ↓
Yandex Managed PostgreSQL
   ├─ portal_a_db
   ├─ portal_b_db
   └─ keycloak_db
        ↓
S3-compatible object storage
```

На первичном этапе **не создаются**:

- вторая backend VPS/VM;
- Yandex Application Load Balancer;
- backend groups для балансировщика;
- rolling update между двумя runtime-нодами.

Публичные домены указывают на один публичный IP `backend-vps-1`. Входящий HTTP/HTTPS-трафик принимает nginx reverse proxy на этой же VPS/VM и маршрутизирует запросы к Keycloak и backend API порталов.

Ограничение single-VPS схемы: отказ `backend-vps-1` приводит к недоступности backend API, workers и Keycloak. Это допустимо только для первичного внедрения или порталов, где такой риск принят владельцем системы. Компенсирующие меры обязательны: backups, restore procedure, мониторинг, алерты, документированный rebuild VPS из Docker images и конфигурации.

Внутренние сотрудники аутентифицируются через Active Directory:

```text
Keycloak на backend-vps-1
   ↓ site-to-site VPN
Active Directory во внутренней сети компании
```

Подрядчики аутентифицируются через локальную базу пользователей Keycloak.

Переход к HA-архитектуре выполняется отдельным этапом и должен включать как минимум вторую VPS/VM, управляемый ingress/load balancing layer, проверку stateless runtime-сервисов и rolling deployment flow.

---

## 3. Ingress layer для single-VPS deployment

В базовой single-VPS схеме ingress layer реализуется через **nginx reverse proxy** на `backend-vps-1`.

Nginx может быть установлен как host-level сервис или запущен как отдельный инфраструктурный Docker Compose project, например:

```text
/opt/infra/nginx/
```

Nginx выполняет:

- TLS termination;
- HTTP → HTTPS redirect;
- маршрутизацию по Host;
- маршрутизацию по path, если необходимо;
- передачу корректных `X-Forwarded-*` headers;
- маршрутизацию к Keycloak;
- маршрутизацию к backend API порталов;
- ограничение доступа к административным endpoint'ам;
- basic rate-limit на публичных endpoint'ах, если требуется;
- access/error logging.

Пример маршрутизации:

```text
auth.example.com
  → keycloak:8080

auth-admin.example.com
  → keycloak:8080
  → доступ только через VPN/IP allowlist

api.portal-a.ru
  → portal-a-api:3000

api.portal-b.ru
  → portal-b-api:3000
```

Требования к single-VPS ingress:

- наружу публикуются только `80/tcp` и `443/tcp`;
- SSH доступен только через VPN, bastion или IP allowlist;
- порты backend API, workers, Keycloak management port `9000` и PostgreSQL наружу не публикуются;
- внутренние сервисы слушают localhost, private Docker network или private interface;
- TLS-сертификаты выпускаются и обновляются контролируемо;
- `auth-admin.example.com` ограничивается на уровне nginx и/или cloud security group;
- request body size, proxy timeout и upload timeout задаются явно;
- для Keycloak передаются корректные proxy headers, чтобы issuer, redirect URI и secure cookies работали через публичный HTTPS-домен;
- конфигурация nginx хранится в infra repository и версионируется.

Yandex Application Load Balancer не является обязательным компонентом первичного внедрения. Он может быть добавлен позже при переходе к HA-схеме, когда появятся две и более runtime-ноды или отдельные требования к управляемому L7-balancing, health checks и отказоустойчивому ingress.

---

## 4. Backend compute layer

Backend-сервисы размещаются на одном production VPS/VM в **Yandex Compute Cloud**.

Базовая production-схема первичного внедрения:

```text
backend-vps-1
```

`backend-vps-1` содержит runtime-сервисы порталов, workers, nginx reverse proxy и Keycloak. Портальные backend API должны оставаться stateless относительно пользовательских запросов: пользовательские файлы хранятся в S3-compatible storage, состояние приложения — в PostgreSQL, сессии и identity — в Keycloak.

На VPS/VM:

```text
/opt/portals/portal-a/
/opt/portals/portal-b/
/opt/infra/keycloak/
/opt/infra/nginx/
```

Каждый портал запускается как отдельный Docker Compose project:

```bash
docker compose -p portal-a up -d
docker compose -p portal-b up -d
```

Keycloak запускается как отдельный инфраструктурный Docker Compose project:

```bash
docker compose -p keycloak up -d
```

Nginx запускается и обновляется отдельно от порталов и Keycloak.

Deployment одного портала не должен затрагивать другие порталы, nginx и Keycloak.

Для подготовки к будущему HA-режиму приложения не должны зависеть от локального диска VPS как от постоянного хранилища пользовательских данных.

---

## 5. Backend application stack

Базовый backend-стек:

- Node.js;
- TypeScript;
- Fastify;
- Drizzle ORM;
- Drizzle Kit;
- jose;
- pino;
- zod.

Backend должен обеспечивать:

- runtime validation входных данных;
- structured JSON logging;
- redaction чувствительных данных;
- CORS allowlist при необходимости;
- CSRF-защиту для cookie-based endpoints;
- secure headers;
- rate-limit;
- health endpoints;
- graceful shutdown;
- DB connection pool limits;
- request id / correlation id.

Обязательные endpoints:

```text
GET /health/live
GET /health/ready
```

Для сервисов с метриками:

```text
GET /metrics
```

---

## 6. Frontend application stack

Базовый frontend-стек:

- React;
- TypeScript;
- Ant Design 5.

Frontend взаимодействует с `auth.example.com` для login/logout flow и с backend API портала для бизнес-операций.

Frontend не хранит долговременные секреты.

Frontend не выполняет финальную авторизацию. Проверки ролей во frontend используются только для UX.

---

## 7. Yandex Managed PostgreSQL

Основная БД: **Yandex Managed PostgreSQL**.

Требования:

- подключение только от доверенных backend-сервисов;
- TLS;
- доступ ограничен network/security rules;
- PostgreSQL не публикуется наружу, если это возможно;
- runtime-пользователь имеет минимальные права;
- migration-пользователь имеет DDL-права;
- backups включены;
- PITR используется при наличии такой возможности;
- conn_limit для каждого пользователя задаётся явно.

В single-VPS схеме доступ к PostgreSQL должен быть разрешён только от `backend-vps-1` и доверенных deployment/migration runners.

Рекомендуемая структура:

```text
portal_a_db
portal_b_db
portal_c_db
keycloak_db
```

Пользователи:

```text
portal_a_runtime
portal_a_migration
portal_b_runtime
portal_b_migration
keycloak_runtime
readonly_reporting, если нужен
```

Connection budget рассчитывается до добавления нового портала или DB user.

Пример формулы:

```text
available_user_connections = max_connections - service_reserve - admin_reserve
```

Для каждого приложения:

```text
conn_limit >= runtime_instance_count × process_count × pool.max + reserve
```

Для первичного single-VPS deployment:

```text
runtime_instance_count = 1
```

При переходе к HA-схеме `runtime_instance_count` увеличивается до количества активных VPS/VM, на которых запущены экземпляры backend API или workers.

Pool size backend, worker и Keycloak задаётся явно.

---

## 8. PostgreSQL extensions и миграции

Расширения PostgreSQL в Yandex Managed PostgreSQL включаются вручную до запуска миграций.

Типовой набор:

- `pgcrypto`;
- `citext`;
- `pg_trgm`.

SQL-миграции приложения не должны выполнять `CREATE EXTENSION`.

Миграции:

- выполняются в SQL-first подходе;
- хранятся как versioned SQL files;
- являются источником правды для production schema changes;
- не изменяются задним числом после попадания в общую ветку;
- исправляются новой миграцией;
- применяются отдельным deployment step;
- не запускаются автоматически из backend или worker контейнеров;
- `drizzle-kit push` не используется в production.

Production migrations должны быть безопасны для controlled single-VPS deployment и не должны блокировать будущий переход к rolling deployment.

---

## 9. Keycloak

Keycloak используется как корпоративный Identity Provider.

Публичный домен:

```text
auth.example.com
```

Административный домен:

```text
auth-admin.example.com
```

`auth-admin.example.com` доступен только через VPN или IP allowlist.

В single-VPS baseline Keycloak размещается на той же VPS/VM, что и backend-сервисы, но как отдельный инфраструктурный сервис:

```text
backend-vps-1: keycloak container
```

Keycloak использует отдельную БД:

```text
keycloak_db
```

Keycloak не размещается внутри compose-проектов порталов.

Обязательные требования:

- отдельный DB user;
- отдельные secrets;
- отдельные backups;
- отдельный deploy/update process;
- отдельные health checks;
- memory limit для контейнера;
- resource limits;
- logs и metrics;
- admin access restricted;
- realm export;
- documented restore procedure.

Keycloak management port `9000` не публикуется наружу.

В базовой single-VPS схеме Keycloak не кластеризуется. Недоступность `backend-vps-1` означает недоступность login/logout flow и административного доступа Keycloak. Поэтому обязательны регулярный realm export, backup `keycloak_db`, проверенная процедура восстановления и мониторинг публичного OIDC discovery endpoint.

При переходе к HA-схеме Keycloak deployment должен быть пересмотрен отдельно: добавляется вторая runtime-нода, корректная работа за load balancer, синхронизация настроек и отдельная проверка session/cluster behavior.

---

## 10. Интеграция с Active Directory

Внутренние сотрудники аутентифицируются через Active Directory.

Keycloak интегрируется с AD через LDAP/LDAPS User Federation.

Схема:

```text
Keycloak
   ↓ LDAPS 636
site-to-site VPN
   ↓
Domain Controller во внутренней сети
```

Требования:

- контроллер домена не публикуется в интернет;
- используется LDAPS;
- service account для LDAP bind имеет минимальные права;
- режим LDAP provider: read-only, если изменение пользователей должно выполняться в AD;
- AD groups мапятся в Keycloak groups / client roles;
- состояние disabled/locked пользователя должно учитываться;
- VPN availability мониторится;
- LDAP bind мониторится;
- алерты на недоступность AD обязательны.

Сотрудник вводит доменный логин и пароль на `auth.example.com`. Keycloak проверяет пароль через AD и не хранит пароль сотрудника у себя.

---

## 11. Подрядчики

Подрядчики не заводятся в Active Directory.

Подрядчики создаются как local users в Keycloak.

Для подрядчиков используются:

- Keycloak local credentials;
- Keycloak groups;
- Keycloak client roles;
- MFA при необходимости;
- срок действия доступа, если предусмотрено процессом;
- регулярная ревизия доступа.

Пример групп:

```text
/contractors
/contractors/romashka
/contractors/romashka/passdesk-viewer
/contractors/romashka/passdesk-editor
```

Пример client roles:

```text
passdesk.access
passdesk.contractor_viewer
passdesk.contractor_editor
```

---

## 12. Модель ролей и авторизации

Keycloak управляет:

- identity;
- источником пользователя;
- состоянием пользователя;
- SSO session;
- MFA;
- доступом к порталу;
- крупными ролями;
- client roles.

Backend портала управляет:

- бизнес-авторизацией;
- доступом к конкретным объектам;
- связью пользователя с отделом;
- связью пользователя с подрядчиком;
- workflow restrictions;
- временными правами;
- audit бизнес-действий.

Рекомендуемая модель:

```text
Keycloak realm:
  your-realm

Keycloak clients:
  passdesk
  finance
  warehouse
  hr

Client roles для passdesk:
  access
  admin
  manager
  hr
  contractor_viewer
  contractor_editor
```

Backend портала проверяет:

- JWT signature;
- issuer;
- audience;
- expiration;
- client roles;
- локальные бизнес-права.

---

## 13. Standalone auth mode

Для порталов, которые не подключены к Keycloak, допускается standalone auth mode.

Standalone auth использует:

- access JWT;
- opaque refresh token;
- refresh rotation;
- refresh reuse detection;
- хранение hash refresh token в БД;
- password hashing;
- password reset;
- local MFA, если используется.

Для корпоративных порталов, подключенных к `auth.example.com`, локальный password login для внутренних сотрудников отключается.

---

## 14. Machine-to-machine API

Portal-to-portal интеграции используют machine-to-machine схему.

Допускаются два варианта:

```text
1. Keycloak service accounts / client credentials flow
2. существующая machine-to-machine JWT-схема портала
```

При использовании Keycloak предпочтителен client credentials flow.

Каждый service client должен иметь:

- client id;
- secret или private key auth;
- allowed scopes;
- allowed audiences;
- минимальные права;
- audit выдачи и использования.

---

## 15. Файлы и S3-compatible storage

Файловое хранилище:

```text
S3-compatible storage
или
Cloudflare R2
```

Файлы загружаются через upload session и presigned URL.

Порядок:

```text
1. backend создаёт upload session;
2. backend генерирует object key;
3. backend выдаёт presigned URL;
4. frontend загружает файл напрямую в S3-compatible storage;
5. frontend подтверждает завершение загрузки;
6. backend проверяет объект;
7. backend создаёт или активирует file record;
8. backend создаёт фоновые задачи обработки файла.
```

Требования:

- object key генерируется backend;
- object key не строится прямой конкатенацией пользовательского ввода;
- при upload проверяются размер, тип, права пользователя;
- при download проверяются права пользователя и принадлежность файла к объекту;
- удаление выполняется через soft delete;
- физическое удаление из S3 выполняется асинхронно;
- повторное удаление отсутствующего объекта считается успешным.

---

## 16. Фоновые задачи, retries и outbox

Для простых и средних порталов используется:

- PostgreSQL-based jobs;
- transactional outbox;
- idempotency;
- retry с exponential backoff;
- jitter;
- dead-state;
- administrative retry.

Job record должен содержать:

- id;
- type;
- payload;
- status;
- attempts;
- max_attempts;
- next_run_at;
- locked_by;
- locked_until;
- last_error;
- created_at;
- updated_at.

В базовой single-VPS схеме worker-процессы запускаются на `backend-vps-1`. Допускается несколько worker-процессов на одной VPS/VM, если это укладывается в CPU/RAM/DB connection budget.

Захват задачи должен выполняться атомарно через PostgreSQL locking, чтобы без перепроектирования поддержать несколько workers и будущую HA-схему.

Все фоновые задачи должны быть идемпотентными.

Redis/BullMQ допускаются для сценариев, где PostgreSQL jobs недостаточны:

- высокая пропускная способность очередей;
- большое количество мелких задач;
- delayed jobs;
- repeatable jobs;
- priorities;
- websocket/pubsub;
- high-frequency distributed rate-limit;
- заметная нагрузка jobs на основную БД.

При использовании BullMQ Redis является обязательным runtime-компонентом.

---

## 17. Transactional email

Основной email provider: **Amazon SES**.

Amazon SES используется для transactional email:

- уведомление о входе;
- password reset;
- MFA/security events;
- приглашения подрядчиков;
- workflow notifications;
- уведомления о статусах;
- административные уведомления.

Обязательные требования:

- SPF;
- DKIM;
- DMARC;
- bounce handling;
- complaint handling;
- suppression list;
- audit отправки security-sensitive писем;
- rate-limit;
- шаблоны;
- секреты только в protected secret storage.

Допустимый alternative provider: **Yandex Cloud Postbox**.

Yandex Postbox допускается, если требуется:

- единый Yandex Cloud-контур;
- интеграция с Yandex IAM и Yandex-инфраструктурой;
- SMTP-интерфейс;
- AWS SES-compatible API;
- меньше внешних облачных зависимостей;
- отправка писем через защищённое соединение TLS 1.2+.

Приложения не должны напрямую зависеть от конкретного provider API.

Рекомендуемый общий модуль:

```text
@your-org/mail
```

---

## 18. Secrets management

Production secrets хранятся в protected runtime secret storage.

Предпочтительный вариант:

```text
Yandex Lockbox
```

Допустимые варианты:

- protected environment variables;
- Docker secrets;
- secret files с ограниченными правами;
- Vault;
- иной корпоративный secret manager.

В secret storage хранятся:

- DB connection URL;
- DB passwords;
- Keycloak DB credentials;
- Keycloak admin bootstrap secret;
- OIDC client secrets;
- Amazon SES credentials;
- Yandex Postbox credentials;
- S3/R2 credentials;
- Sentry tokens;
- log HMAC key;
- encryption keys;
- service account secrets;
- SMTP credentials;
- PostgreSQL CA certificate или путь к нему.

Файл `.env` не коммитится в git.

Production-секреты не хранятся в Docker image, frontend-коде, логах или БД.

---

## 19. Deployment

Production deployment выполняется через deploy runner или CI/CD pipeline.

Оператор запускает deployment один раз для конкретного портала и окружения.

Production VPS/VM не выполняет:

```text
git pull
npm install
npm run build
```

Production VPS/VM получает заранее собранный Docker image из registry.

Docker images хранятся в:

```text
Yandex Container Registry
```

Deployment flow для single-VPS baseline:

```text
1. deployment lock;
2. preflight checks;
3. build Docker image from exact commit;
4. push immutable image tag;
5. migration plan;
6. apply SQL migrations one time;
7. update portal API compose project on backend-vps-1;
8. health check API;
9. update/restart portal workers on backend-vps-1;
10. worker health/status check;
11. post-deploy checks;
12. deployment report.
```

На первичном этапе допускается controlled restart конкретного портала на одной VPS/VM. Нулевой downtime и rolling deployment не являются обязательными требованиями single-VPS baseline, но миграции и runtime-код должны проектироваться так, чтобы не блокировать будущий переход к rolling deployment.

Deployment должен быть portal-scoped.

Скрипт деплоя не должен изменять соседние порталы, Keycloak, nginx или другие инфраструктурные сервисы.

Запрещены глобальные destructive-команды:

```text
docker stop $(docker ps -q)
docker system prune -a
docker compose down --volumes
rm -rf /opt/portals/*
```

Keycloak и nginx обновляются отдельными infrastructure deployment процедурами, а не в рамках деплоя бизнес-портала.

Каждый deploy формирует deployment report.

---

## 20. Observability

Используется managed/SaaS-first подход.

В single-VPS baseline особое внимание уделяется мониторингу `backend-vps-1`, потому что на ней находятся backend API, workers, nginx reverse proxy и Keycloak.

Компоненты:

```text
Yandex Monitoring
Yandex Managed Service for Prometheus
Yandex Cloud Logging или Monium Logs
Sentry SaaS
Node Exporter
cAdvisor, если нужны container metrics
nginx access/error logs
Uptime Kuma или uptime-SaaS
Grafana dashboards
```

### Метрики

Yandex Monitoring используется для облачных ресурсов и базовых метрик VPS/VM.

Yandex Managed Service for Prometheus используется для:

- Node Exporter metrics;
- cAdvisor metrics;
- nginx metrics, если включены;
- Fastify application metrics;
- Keycloak metrics;
- custom technical metrics;
- optional business metrics.

### Логи

Application logs пишутся в JSON через pino.

Логи отправляются в:

```text
Yandex Cloud Logging
или
Monium Logs
```

Nginx access/error logs также должны собираться централизованно или быть доступны для диагностики инцидентов.

Из логов удаляются или маскируются:

- пароли;
- Authorization header;
- cookies;
- access tokens;
- refresh tokens;
- client secrets;
- OTP/TOTP values;
- recovery codes;
- private keys;
- presigned URLs;
- request body с ПДн.

### Sentry

Sentry используется как SaaS.

Подключается к:

- backend API;
- workers;
- frontend React.

Требования:

- `sendDefaultPii=false`;
- `beforeSend` redaction;
- server-side data scrubbing;
- source maps upload для frontend;
- release и environment tagging;
- запрет отправки request body с ПДн;
- запрет отправки токенов, cookies, presigned URLs, секретов.

### Uptime

Uptime checks:

```text
https://auth.example.com/realms/your-realm/.well-known/openid-configuration
https://api.portal-a.ru/health/live
https://api.portal-a.ru/health/ready
https://api.portal-b.ru/health/live
https://api.portal-b.ru/health/ready
```

Для single-VPS baseline дополнительно рекомендуется проверять:

```text
https://auth-admin.example.com/realms/master/.well-known/openid-configuration
```

если проверка выполняется из VPN/IP allowlist и не раскрывает административный endpoint наружу.

---

## 21. Alerts

Обязательные alerts:

- backend-vps-1 unavailable;
- nginx/reverse proxy unavailable;
- backend service down;
- Keycloak unavailable;
- AD/LDAP unavailable;
- VPN to AD unavailable;
- PostgreSQL connection errors;
- DB connections near limit;
- high 5xx rate;
- high p95/p99 latency;
- worker dead jobs;
- failed deployment;
- disk space low;
- CPU/memory pressure на backend-vps-1;
- TLS certificate expiration;
- container restarts;
- Sentry critical issue;
- SES/Postbox send failures;
- bounce/complaint rate growth;
- refresh token reuse, если используется standalone auth;
- suspicious login failures;
- admin role changes.

Используется один основной alerting control plane:

```text
Yandex Monitoring Alerts
или
Grafana Alerting
```

---

## 22. Audit

Audit log должен фиксировать:

- successful login;
- failed login;
- logout;
- role changes;
- group changes;
- service account changes;
- machine token выдачу;
- password reset;
- MFA events;
- contractor invite;
- contractor disabled;
- critical file errors;
- dead jobs;
- admin actions;
- deployment events.

Email в audit log хранится как HMAC, если хранение email в открытом виде не требуется бизнес-логикой.

---

## 23. Transport security, headers и CORS

Production-порталы доступны только по HTTPS.

В single-VPS baseline TLS termination и HTTP → HTTPS redirect выполняет nginx reverse proxy на `backend-vps-1`.

HTTP перенаправляется на HTTPS.

Базовые security headers:

- Strict-Transport-Security;
- X-Content-Type-Options;
- Referrer-Policy;
- X-Frame-Options или CSP frame-ancestors;
- Content-Security-Policy.

CORS:

- не включается, если frontend и backend находятся на одном origin;
- использует exact allowlist origins, если CORS требуется;
- authenticated API не использует wildcard origin;
- credentials допускаются только с конкретным разрешённым origin.

Порты backend API, Keycloak internal endpoints, worker-процессы и PostgreSQL не публикуются напрямую в интернет.

---

## 24. Shared skills, packages и templates

Общие технические решения не копируются вручную между проектами.

Используются:

```text
portal-template
your-org-shared packages
infra-standards repository
agent-skills, если используются AI-агенты
```

### portal-template

Шаблон нового портала:

```text
backend/
frontend/
deploy/
docs/
monitoring/
```

### internal npm packages

Общие runtime-библиотеки:

```text
@your-org/config
@your-org/logger
@your-org/fastify-security
@your-org/oidc
@your-org/mail
@your-org/s3
@your-org/jobs
@your-org/observability
```

Каждый пакет должен иметь:

- semver;
- changelog;
- tests;
- owner;
- security review для auth/mail/crypto компонентов.

### infra-standards

Хранит:

- deployment scripts;
- Yandex setup docs;
- Keycloak setup docs;
- AD integration docs;
- PostgreSQL connection budget docs;
- monitoring templates;
- runbooks;
- incident procedures.

---

## 25. Production startup checks

При старте production-сервис проверяет:

- наличие обязательных env/secrets;
- отсутствие placeholder/default значений;
- корректность DB URL;
- TLS-настройки подключения к PostgreSQL;
- корректный `NODE_ENV`;
- наличие S3 credentials;
- наличие Sentry config, если включен;
- корректность OIDC issuer/audience;
- отсутствие dev-настроек;
- доступность критичных зависимостей, если это требуется для readiness.

Если критичная настройка отсутствует или небезопасна, сервис завершает запуск с ошибкой.

---

## 26. Обязательный минимум стандарта v3.1

Для каждого production-портала в single-VPS baseline реализуются:

- HTTPS only;
- nginx reverse proxy или другой утверждённый ingress layer на `backend-vps-1`;
- один production VPS/VM для первичного внедрения;
- backend API, workers и Keycloak на одной VPS/VM, но в отдельных Docker Compose projects;
- Node.js + TypeScript + Fastify backend;
- React + TypeScript + Ant Design 5 frontend;
- Docker Compose runtime на production VPS/VM;
- Yandex Managed PostgreSQL;
- S3-compatible object storage;
- upload через presigned URL;
- SQL-first migrations;
- Drizzle ORM;
- Drizzle Kit;
- migration runner как отдельный deployment step;
- PostgreSQL-based jobs/outbox для простых и средних фоновых задач;
- idempotency для повторяемых операций;
- Keycloak integration для корпоративного SSO;
- Active Directory integration для внутренних сотрудников;
- Keycloak local users для подрядчиков;
- backend authorization для бизнес-прав;
- Amazon SES как основной transactional email provider;
- Yandex Postbox как допустимый альтернативный provider;
- pino JSON logs;
- redaction чувствительных данных;
- Sentry SaaS;
- Yandex Monitoring;
- Managed Prometheus для custom metrics при необходимости;
- Cloud Logging или Monium Logs;
- deployment runner;
- immutable Docker image tags;
- deployment report;
- Yandex Container Registry;
- protected secret storage;
- production startup checks;
- audit log критичных событий;
- alerts на VPS, reverse proxy, auth, DB, worker и deployment-события;
- documented backup/restore procedure для `backend-vps-1`, PostgreSQL, Keycloak realm и конфигурации nginx.

Yandex Application Load Balancer и вторая VPS/VM не входят в обязательный минимум первичного внедрения. Они добавляются отдельным HA-этапом при наличии требований к отказоустойчивости, горизонтальному масштабированию или rolling deployment без downtime.

