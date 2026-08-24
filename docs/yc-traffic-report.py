#!/usr/bin/env python3
"""Отчёт по исходящему трафику YC-релея в Telegram.

У Yandex Cloud бесплатны входящий трафик и первые 100 ГБ исходящего в месяц,
дальше тарификация. Через релей идут все хосты подписки, поэтому лимит реально
перекрывается — этот скрипт делает расход видимым до счёта.

Режимы:
  (без флагов)   ежедневный дайджест
  --check-only   молча, пишет только при пересечении порога 70/90/100 ГБ
  --dry-run      печатает сообщение, ничего не отправляет

Токен и chat id — в /etc/xray-sync/tg.env (root, 0600), в вывод не попадают.
"""
import argparse
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


def days_in_month(dt):
    nxt = dt.replace(day=28) + timedelta(days=4)
    return (nxt.replace(day=1) - timedelta(days=1)).day


def build(tx_gb, rx_gb, created):
    now = datetime.now(timezone.utc)
    total_days = days_in_month(now)
    # темп считаем по фактически измеренному окну: vnstat мог начать вести учёт
    # в середине месяца, тогда деление на «дни с 1-го числа» занижает прогноз
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp()
    window_start = max(month_start, created.get("timestamp", 0) or month_start)
    measured_days = max((now.timestamp() - window_start) / 86400.0, 0.0)
    projection = tx_gb / measured_days * total_days if measured_days > 0.25 else None
    left = FREE_GB - tx_gb

    lines = ["<b>YC-релей · трафик за %02d.%d</b>" % (now.month, now.year)]
    lines.append("Исходящий (платный): <b>%.1f ГБ</b> из 100 бесплатных" % tx_gb)
    lines.append("Остаток: %s" % ("%.1f ГБ" % left if left > 0 else "исчерпан, +%.1f ГБ сверх лимита" % -left))
    if projection:
        lines.append("Прогноз на месяц: <b>%.0f ГБ</b>%s"
                     % (projection, "" if projection <= FREE_GB else " → %.0f ГБ платных" % (projection - FREE_GB)))
    lines.append("Входящий (бесплатный): %.1f ГБ" % rx_gb)
    cd = created.get("date", {})
    if cd and (cd.get("year"), cd.get("month")) == (now.year, now.month) and cd.get("day", 1) > 1:
        lines.append("<i>учёт с %02d.%02d, начало месяца не посчитано; прогноз — по темпу за %.1f сут</i>"
                     % (cd["day"], cd["month"], measured_days))
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
        v = v.replace("\\", "\\\\").replace('"', '\\"')
        return v.replace("\n", "\n")

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

    tx_gb, rx_gb, created = vnstat()
    now = datetime.now(timezone.utc)
    month_key = "%d-%02d" % (now.year, now.month)

    state = read_state()
    if state.get("month") != month_key:
        state = {"month": month_key, "alerted": []}

    if args.check_only:
        crossed = [t for t in THRESHOLDS if tx_gb >= t and t not in state["alerted"]]
        if not crossed:
            return 0
        top = max(crossed)
        text = "⚠️ <b>YC: пройдено %d ГБ исходящего</b>\n\n%s" % (top, build(tx_gb, rx_gb, created))
        if send(text, args.dry_run) and not args.dry_run:
            state["alerted"] = sorted(set(state["alerted"]) | set(crossed))
            write_state(state)
        return 0

    send(build(tx_gb, rx_gb, created), args.dry_run)
    if not args.dry_run:
        write_state(state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
