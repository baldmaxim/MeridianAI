#!/usr/bin/env python3
"""Отчёт по исходящему трафику YC-релея в Telegram.

У Yandex Cloud бесплатны входящий трафик и первые 100 ГБ исходящего в месяц,
дальше тарификация. Через релей идут все хосты подписки, поэтому лимит реально
перекрывается — этот скрипт делает расход видимым до счёта.

Вход через CDN (static.meridianai.ru) считается отдельно: релей→CDN Яндекс не
тарифицирует, а сам CDN берёт из пакета 150 ГБ/мес. vnstat видит этот трафик как
обычный исходящий, поэтому его вычитаем. Объём берём из stream-лога nginx
(SNI + sent каждой сессии), копим по дням в CDN_FILE — логи живут 14 дней.

Режимы:
  (без флагов)   ежедневный дайджест
  --check-only   молча, пишет только при пересечении порога 70/90/100 ГБ или пакета CDN
  --dry-run      печатает сообщение, ничего не отправляет (так его зовёт бот:
                 под ubuntu, только чтение vnstat и CDN_FILE)

Токен и chat id — в /etc/xray-sync/tg.env (root, 0600), в вывод не попадают.
"""
import argparse
import glob
import gzip
import json
import os
import subprocess
import sys
import time
import re
from datetime import datetime, timedelta, timezone

IFACE = "eth0"
FREE_GB = 100.0
THRESHOLDS = [70, 90, 100]
CDN_SNI = b'sni="static.meridianai.ru"'
CDN_PACKAGE_GB = 150.0
CDN_OVER_RUB = 1.054           # ₽ за ГБ сверх пакета
CDN_THRESHOLDS = [150]
CDN_KEEP_DAYS = 62
STREAM_LOGS = "/var/log/nginx/stream-sni.log*"
CDN_FILE = "/var/lib/yc-traffic/cdn.json"
CDN_LINE_RE = re.compile(rb"^(\d{4}-\d{2}-\d{2})T.* sent=(\d+) ")
ENV_FILE = "/etc/xray-sync/tg.env"
# api.telegram.org с YC напрямую недоступен (URLError) — ходим через локальный
# socks-вход самого релея, он уводит запрос на выходную ноду
SOCKS = "127.0.0.1:10808"
TOKEN_RE = re.compile(r"^\d{6,}:[A-Za-z0-9_-]{30,}$")
STATE_FILE = "/var/lib/yc-traffic/state.json"
GB = 1024.0 ** 3


def read_env():
    env = {}
    with open(ENV_FILE) as fh:
        for line in fh:
            line = line.strip()
            if line and "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env["TG_BOT_TOKEN"], env["TG_CHAT_ID"]


def read_state():
    try:
        return json.load(open(STATE_FILE))
    except Exception:
        return {}


def write_state(state):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    tmp = STATE_FILE + ".tmp"
    json.dump(state, open(tmp, "w"))
    os.replace(tmp, STATE_FILE)


def vnstat():
    out = subprocess.run(["vnstat", "--json", "m"], capture_output=True, text=True, timeout=30)
    data = json.loads(out.stdout)
    iface = [i for i in data["interfaces"] if i["name"] == IFACE][0]
    months = iface["traffic"]["month"]
    now = datetime.now(timezone.utc)
    cur = [m for m in months
           if m["date"]["year"] == now.year and m["date"]["month"] == now.month]
    m = cur[-1] if cur else {"rx": 0, "tx": 0}
    return m["tx"] / GB, m["rx"] / GB, iface.get("created", {})


def read_cdn():
    try:
        return json.load(open(CDN_FILE)).get("days", {})
    except Exception:
        return {}


def cdn_update():
    """Трафик релей→CDN по дням из stream-лога → CDN_FILE. День пересчитывается
    целиком по доступным файлам, берём максимум со старым значением — кусок,
    уехавший в ротацию или недожатый gzip, сумму не уменьшит."""
    days = {}
    for path in glob.glob(STREAM_LOGS):
        opener = gzip.open if path.endswith(".gz") else open
        try:
            with opener(path, "rb") as fh:
                for line in fh:
                    if CDN_SNI not in line:
                        continue
                    m = CDN_LINE_RE.match(line)
                    if m:
                        day = m.group(1).decode()
                        days[day] = days.get(day, 0) + int(m.group(2))
        except (OSError, EOFError):
            continue
    stored = read_cdn()
    for day, nbytes in days.items():
        stored[day] = max(stored.get(day, 0), nbytes)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=CDN_KEEP_DAYS)).strftime("%Y-%m-%d")
    stored = {d: b for d, b in stored.items() if d >= cutoff}
    os.makedirs(os.path.dirname(CDN_FILE), exist_ok=True)
    tmp = CDN_FILE + ".tmp"
    json.dump({"days": stored, "updated": int(time.time())}, open(tmp, "w"), sort_keys=True)
    os.chmod(tmp, 0o644)         # бот читает под ubuntu
    os.replace(tmp, CDN_FILE)


def cdn_month(days, now):
    """→ (ГБ за текущий месяц, первый день с данными | None)."""
    prefix = "%d-%02d-" % (now.year, now.month)
    cur = {d: b for d, b in days.items() if d.startswith(prefix)}
    return sum(cur.values()) / GB, (min(cur) if cur else None)


def days_in_month(dt):
    nxt = dt.replace(day=28) + timedelta(days=4)
    return (nxt.replace(day=1) - timedelta(days=1)).day


def build(tx_gb, rx_gb, created, cdn_days):
    now = datetime.now(timezone.utc)
    total_days = days_in_month(now)
    cdn_gb, cdn_first = cdn_month(cdn_days, now)
    paid_gb = max(tx_gb - cdn_gb, 0.0)
    # темп считаем по фактически измеренному окну: vnstat мог начать вести учёт
    # в середине месяца, тогда деление на «дни с 1-го числа» занижает прогноз
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp()
    window_start = max(month_start, created.get("timestamp", 0) or month_start)
    measured_days = max((now.timestamp() - window_start) / 86400.0, 0.0)
    projection = paid_gb / measured_days * total_days if measured_days > 0.25 else None
    left = FREE_GB - paid_gb

    lines = ["<b>YC-релей · трафик за %02d.%d</b>" % (now.month, now.year)]
    lines.append("Исходящий (платный): <b>%.1f ГБ</b> из 100 бесплатных" % paid_gb)
    if cdn_gb:
        lines.append("<i>всего %.1f ГБ, из них %.1f ГБ в CDN — Яндекс его не тарифицирует</i>"
                     % (tx_gb, cdn_gb))
    lines.append("Остаток: %s" % ("%.1f ГБ" % left if left > 0 else "исчерпан, +%.1f ГБ сверх лимита" % -left))
    if projection:
        lines.append("Прогноз на месяц: <b>%.0f ГБ</b>%s"
                     % (projection, "" if projection <= FREE_GB else " → %.0f ГБ платных" % (projection - FREE_GB)))
    lines.append("Входящий (бесплатный): %.1f ГБ" % rx_gb)
    cd = created.get("date", {})
    if cd and (cd.get("year"), cd.get("month")) == (now.year, now.month) and cd.get("day", 1) > 1:
        lines.append("<i>учёт с %02d.%02d, начало месяца не посчитано; прогноз — по темпу за %.1f сут</i>"
                     % (cd["day"], cd["month"], measured_days))

    lines.append("")
    lines.append("<b>CDN</b> (static.meridianai.ru): <b>%.1f ГБ</b> из пакета %.0f" % (cdn_gb, CDN_PACKAGE_GB))
    over = cdn_gb - CDN_PACKAGE_GB
    lines.append("Остаток пакета: %s" % ("%.1f ГБ" % -over if over < 0 else
                                          "исчерпан, +%.1f ГБ ≈ %.0f ₽" % (over, over * CDN_OVER_RUB)))
    if cdn_first:
        # учёт CDN начался 25.09.2026 — в первый месяц темп считаем от первого дня с данными
        first_ts = datetime.strptime(cdn_first, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()
        cdn_days_measured = (now.timestamp() - max(month_start, first_ts)) / 86400.0
        if cdn_days_measured > 0.25:
            cdn_proj = cdn_gb / cdn_days_measured * total_days
            extra = cdn_proj - CDN_PACKAGE_GB
            lines.append("Прогноз на месяц: <b>%.0f ГБ</b>%s"
                         % (cdn_proj, "" if extra <= 0 else " → сверх пакета %.0f ГБ ≈ %.0f ₽"
                            % (extra, extra * CDN_OVER_RUB)))
        if cdn_first > now.strftime("%Y-%m-01"):
            lines.append("<i>учёт CDN с %s.%s</i>" % (cdn_first[8:10], cdn_first[5:7]))
    return "\n".join(lines)


def send(text, dry):
    if dry:
        print(text)
        return True
    token, chat = read_env()
    if not TOKEN_RE.match(token):
        print("ERROR: в %s лежит не бот-токен (в панельном .env заглушка) — отчёт не отправлен"
              % ENV_FILE, file=sys.stderr)
        return False

    def esc(v):
        # config-файл curl читается построчно: перевод строки обязан уехать как
        # escape-последовательность, иначе в Telegram улетит только первая строка
        return (v.replace("\\", "\\\\").replace('"', '\\"')
                 .replace("\r", "").replace("\n", "\\n"))

    cfg = "\n".join([
        'url = "https://api.telegram.org/bot%s/sendMessage"' % esc(token),
        'data-urlencode = "chat_id=%s"' % esc(chat),
        'data-urlencode = "text=%s"' % esc(text),
        'data-urlencode = "parse_mode=HTML"',
        'silent',
        'max-time = 25',
    ])
    # токен уходит в curl через stdin, а не в argv — иначе виден в ps
    for attempt, extra in enumerate((["--socks5-hostname", SOCKS], [])):
        try:
            out = subprocess.run(["curl", "--config", "-"] + extra, input=cfg,
                                 capture_output=True, text=True, timeout=40)
            if out.stdout:
                resp = json.loads(out.stdout)
                if resp.get("ok"):
                    return True
                print("ERROR: telegram отказал: %s" % resp.get("description", "?"),
                      file=sys.stderr)
                return False
        except Exception:
            pass
        if attempt == 0:
            time.sleep(2)
    print("ERROR: telegram недоступен ни через socks, ни напрямую", file=sys.stderr)
    return False


def find_chat():
    """Печатает chat_id из последних апдейтов бота (сам токен не печатается)."""
    token, _ = read_env()
    if not TOKEN_RE.match(token):
        print("В %s нет валидного бот-токена — сначала впиши TG_BOT_TOKEN" % ENV_FILE)
        return 1
    cfg = 'url = "https://api.telegram.org/bot%s/getUpdates"\nsilent\nmax-time = 25' % token
    out = subprocess.run(["curl", "--config", "-", "--socks5-hostname", SOCKS],
                         input=cfg, capture_output=True, text=True, timeout=40)
    try:
        data = json.loads(out.stdout)
    except Exception:
        print("Telegram не ответил (проверь, что xray на релее жив)")
        return 1
    if not data.get("ok"):
        print("Telegram отказал: %s" % data.get("description", "?"))
        return 1
    seen = {}
    for upd in data.get("result", []):
        msg = upd.get("message") or upd.get("channel_post") or {}
        chat = msg.get("chat") or {}
        if chat.get("id"):
            seen[chat["id"]] = chat.get("title") or chat.get("username") or chat.get("type")
    if not seen:
        print("Апдейтов нет — напиши боту любое сообщение и повтори")
        return 1
    for cid, title in seen.items():
        print("TG_CHAT_ID=%s   (%s)" % (cid, title))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check-only", action="store_true", help="только пороги, молча если не пересечены")
    ap.add_argument("--dry-run", action="store_true", help="напечатать, не отправлять")
    ap.add_argument("--find-chat", action="store_true", help="показать chat_id из апдейтов бота")
    args = ap.parse_args()

    if args.find_chat:
        return find_chat()

    if os.geteuid() == 0:        # логи nginx читает только root; бот под ubuntu берёт готовый CDN_FILE
        try:
            cdn_update()
        except Exception as exc:
            print("WARNING: учёт CDN не обновлён: %s" % type(exc).__name__, file=sys.stderr)
    tx_gb, rx_gb, created = vnstat()
    cdn_days = read_cdn()
    now = datetime.now(timezone.utc)
    month_key = "%d-%02d" % (now.year, now.month)

    state = read_state()
    if state.get("month") != month_key:
        state = {"month": month_key, "alerted": []}

    if args.check_only:
        cdn_gb = cdn_month(cdn_days, now)[0]
        paid_gb = tx_gb - cdn_gb
        crossed = [t for t in THRESHOLDS if paid_gb >= t and t not in state["alerted"]]
        cdn_crossed = [t for t in CDN_THRESHOLDS
                       if cdn_gb >= t and t not in state.get("cdn_alerted", [])]
        if not (crossed or cdn_crossed):
            return 0
        titles = []
        if crossed:
            titles.append("⚠️ <b>YC: пройдено %d ГБ исходящего</b>" % max(crossed))
        if cdn_crossed:
            titles.append("⚠️ <b>CDN: пройдено %d ГБ — пакет исчерпан, дальше %.3f ₽/ГБ</b>"
                          % (max(cdn_crossed), CDN_OVER_RUB))
        text = "%s\n\n%s" % ("\n".join(titles), build(tx_gb, rx_gb, created, cdn_days))
        if send(text, args.dry_run) and not args.dry_run:
            state["alerted"] = sorted(set(state["alerted"]) | set(crossed))
            state["cdn_alerted"] = sorted(set(state.get("cdn_alerted", [])) | set(cdn_crossed))
            write_state(state)
        return 0

    send(build(tx_gb, rx_gb, created, cdn_days), args.dry_run)
    if not args.dry_run:
        write_state(state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
