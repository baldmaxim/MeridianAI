# Добавление пользователя в VPN (Remnawave)

**Обычный сценарий — только панель.** Создать юзера и включить в сквад (`External` / `Home`).
Дальше всё подхватывается автоматически в течение ~5 минут.

Так сделано потому, что все 8 хостов подписки идут на **один вход — YC-релей
`89.169.191.175`**, а панель пушит клиентов только remnanode-нодам (Kamatera).
YC-релей и KG-нода — нативные xray с ручными конфигами, их закрывают два синка.

## Что работает автоматически

| Где | Что делает | Механизм | Логи |
|---|---|---|---|
| YC-релей | клиенты на 8 VLESS-инбаундах + персональные плечи `out-nl-<user>`/`out-kg-<user>` + правила роутинга | `xray-sync-users.timer` (5 мин) → `/usr/local/bin/xray-sync-users.py` | `journalctl -u xray-sync-users` |
| KG-нода (Windows) | клиенты в `C:\xray\config.json` (host-xray :443) | задача `xray-sync-kg` (5 мин) → `C:\xray\xray-sync-kg-clients.py` | `C:\xray\sync.log` |
| Kamatera | клиенты на ноде | сама панель (remnanode) | — |

Оба скрипта:

- берут список из API панели (`GET /api/users`), токен в `/etc/xray-sync/token` (root, 0600)
  и `C:\xray\panel-token.txt` (ACL: только SYSTEM + Administrators);
- доступ дают **только юзерам со статусом `ACTIVE` и хотя бы одним сквадом** — снятие галки
  или `DISABLED`/`EXPIRED` в панели убирает клиента с релея тем же таймером;
- идемпотентны: конфиг переписывается и xray рестартится **только при реальном изменении**,
  перед применением всегда `xray -test`, на KG остаётся бэкап `config.json.bak-*`;
- при пустом/битом ответе API конфиг не трогают, за один прогон не удаляют больше трети
  клиентов инбаунда;
- значения uuid не печатают и не логируют.

Исходники в репозитории: [`xray-sync-users.py`](xray-sync-users.py),
[`xray-sync-kg-clients.py`](xray-sync-kg-clients.py).

## Если нужно прямо сейчас, не дожидаясь таймера

```bash
ssh yc "sudo /usr/local/bin/xray-sync-users.py"          # релей
```
```powershell
schtasks /Run /TN xray-sync-kg                            # KG-нода
```

## Проверка

```bash
scp docs/xray-testleg.sh yc:/tmp/testleg.sh
ssh yc "chmod +x /tmp/testleg.sh && /tmp/testleg.sh out-nl-<user> out-kg-<user>"
# ожидаемо: 194.37.81.38 (Kamatera) и 217.177.47.128 (KG)
```

Полный e2e — прогнать все 8 конфигов из `https://sub.meridianai.ru/sub/<short_uuid>`
через локальный xray и curl'ить `api.ipify.org`.

## Частые причины «не пингуется ни один сервер»

| Симптом | Причина | Где чинить |
|---|---|---|
| Новый юзер — мертвы все хосты | не отработал синк релея | `journalctl -u xray-sync-users`, запустить руками |
| Мертвы только KG-хосты (у всех) | сменился IP KG-машины / не отработал синк KG | `out-kg*` адрес в конфиге YC, `C:\xray\sync.log` |
| Нода красная в панели, но трафик идёт | нет/лежит remnanode-агент на :2222 | поднять контейнер `remnawave/node` с `.env` (`NODE_PORT`, `SECRET_KEY`) |

## Трафик YC (100 ГБ/мес бесплатно)

Через релей идёт весь трафик подписки, а у Yandex Cloud тарифицируется исходящий сверх
100 ГБ в месяц. Учёт: `vnstat` на YC + `yc-traffic-report.py`.

- ежедневный дайджест — `yc-traffic-report.timer` (09:00 МСК)
- пороги 70/90/100 ГБ — `yc-traffic-alert.timer` (раз в час, `--check-only`)
- вручную: `ssh yc "vnstat -m"` или `sudo /usr/local/bin/yc-traffic-report.py --dry-run`

Готча: **api.telegram.org с YC напрямую недоступен**, поэтому скрипт шлёт через локальный
socks-вход самого релея (`127.0.0.1:10808` → выходная нода), с фолбэком на прямой запрос.

Секреты бота — в `/etc/xray-sync/tg.env` (root, 0600), формат:

```
TG_BOT_TOKEN=<токен от @BotFather>
TG_CHAT_ID=<id чата>
```

`sudo /usr/local/bin/yc-traffic-report.py --find-chat` покажет chat_id из апдейтов бота
(токен при этом не печатается).
