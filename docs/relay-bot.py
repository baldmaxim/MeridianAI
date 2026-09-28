#!/usr/bin/env python3
"""Телеграм-бот VPN-релея. Работает рядом с relay-probe на Kamatera.

Зачем: алерты приходят только когда всё сломалось, а вопросы «сейчас-то нормально?»,
«как часто рвётся?», «почему у Васи не работает?» возникают постоянно. Бот отвечает
на кнопки под полем ввода: сводка, быстрая проверка входов, список юзеров с онлайном
и трафиком, история обрывов, здоровье выходной ноды, трафик YC, карточка юзера
с диагнозом и действиями (вкл/выкл, +30 дней, сброс трафика, подписка + QR, устройства),
создание юзера (/add). Раз в 10 минут сам присылает события: нода упала/вернулась,
юзер впервые подключился, срок истекает/истёк, трафик ≥90 %, conntrack переполнился.

Long polling (webhook невозможен: :443 на Kamatera занят xray). Отвечает только в чат
из TG_CHAT_ID — на чужие сообщения и callback'и молчит. Любое изменение в панели —
только после inline-подтверждения «Да».

Секреты: /etc/relay-probe/tg.env (бот), /etc/relay-probe/panel.env (API панели),
/etc/relay-probe/yc_key (ssh-ключ на YC, forced-command отчёта трафика), все 0600 root.
В ответах — username юзеров; ссылка подписки уходит только в TG_CHAT_ID по кнопке
и не логируется.
"""
import html
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone

TG_ENV = "/etc/relay-probe/tg.env"
PANEL_ENV = "/etc/relay-probe/panel.env"
RUN_LOG = "/var/lib/relay-probe/runs.jsonl"
OFFSET_FILE = "/var/lib/relay-probe/bot-offset"
WATCH_FILE = "/var/lib/relay-probe/watch.json"
PROBE = "/usr/local/bin/relay-probe.py"
YC_HOST = "ubuntu@89.169.191.175"
YC_KEY = "/etc/relay-probe/yc_key"
GIB = 1024.0 ** 3
TZ_SHIFT = 3 * 3600            # выводим время в МСК
POLL_TIMEOUT = 25
WATCH_INTERVAL = 600           # уведомления о событиях — раз в 10 мин
ONLINE_WINDOW = 5 * 60         # onlineAt свежее этого = «онлайн»
EXPIRE_WARN = 7 * 86400
EXPIRE_NOTIFY = 3 * 86400
TRAFFIC_WARN = 0.9
EXTEND_DAYS = 30
PENDING_TTL = 600
TG_LIMIT = 3900                # лимит сообщения TG 4096, оставляем запас на теги
SERVICE_USERS = {"relayprobe"} # служебные юзеры, в списках не показываем
DEFAULT_SQUAD = "External"
USERNAME_RE = re.compile(r"^[a-zA-Z0-9_-]{3,36}$")
# в панели ноды названы технически — в сводке показываем по-человечески
NODE_NAMES = {
    "YottaSRC": "🇳🇱 Yotta · NL (выход трафика)",
}

BTN_STAT, BTN_CHECK = "📊 Сводка", "🔍 Проверить сейчас"
BTN_USERS, BTN_OUTAGES = "👥 Юзеры", "📜 Обрывы"
BTN_TRAFFIC, BTN_NODE = "📈 Трафик YC", "🖥 Нода"
BTN_ADD, BTN_HELP = "➕ Новый юзер", "📖 Инструкция"
KEYBOARD = json.dumps({
    "keyboard": [[BTN_STAT, BTN_CHECK], [BTN_USERS, BTN_OUTAGES],
                 [BTN_TRAFFIC, BTN_NODE], [BTN_ADD, BTN_HELP]],
    "resize_keyboard": True,
}, ensure_ascii=False)

PENDING = {}                   # id → {"act", "user", "args", "t"} — ждут подтверждения


# ---------- низкоуровневое ----------

def read_kv(path):
    env = {}
    try:
        for line in open(path):
            line = line.strip()
            if line and "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    except Exception:
        pass
    return env


def esc(v):
    """Экранирование для config-файла curl: он читает построчно, поэтому перевод
    строки обязан уехать как escape-последовательность, иначе текст обрежется."""
    return (v.replace(chr(92), chr(92) * 2)
             .replace('"', chr(92) + '"')
             .replace(chr(13), "")
             .replace(chr(10), chr(92) + "n"))


def api(method, data=None, files=None, timeout=40):
    """Вызов Telegram API. Токен уходит в curl через stdin, а не в argv.
    files={"photo": path} → multipart (form-string для текста, чтобы curl не трактовал @ и ;)."""
    env = read_kv(TG_ENV)
    token = env.get("TG_BOT_TOKEN", "")
    if not token:
        return {}
    cfg = ['url = "https://api.telegram.org/bot%s/%s"' % (token, method), "silent",
           "max-time = %d" % timeout]
    for k, v in (data or {}).items():
        if files:
            cfg.append('form-string = "%s=%s"' % (k, esc(str(v))))
        else:
            cfg.append('data-urlencode = "%s=%s"' % (k, esc(str(v))))
    for k, path in (files or {}).items():
        cfg.append('form = "%s=@%s"' % (k, esc(path)))
    try:
        out = subprocess.run(["curl", "--config", "-"], input="\n".join(cfg),
                             capture_output=True, text=True, timeout=timeout + 15)
        return json.loads(out.stdout or "{}")
    except Exception:
        return {}


def send(chat, text, markup=None):
    """Ответ; длинный текст режем по строкам под лимит TG. markup — inline-клавиатура
    (только на последний кусок), иначе постоянная reply-клавиатура."""
    chunks, cur = [], ""
    for line in text.split("\n"):
        if cur and len(cur) + len(line) + 1 > TG_LIMIT:
            chunks.append(cur)
            cur = line
        else:
            cur = line if not cur else cur + "\n" + line
    chunks.append(cur)
    for i, chunk in enumerate(chunks):
        last = i == len(chunks) - 1
        api("sendMessage", {"chat_id": chat, "text": chunk, "parse_mode": "HTML",
                            "reply_markup": (markup if (markup and last) else KEYBOARD)})


def send_qr(chat, payload, caption):
    """QR-код через qrencode (payload идёт в stdin, не в argv) → sendPhoto."""
    if not shutil.which("qrencode"):
        return False
    tmp = tempfile.mkdtemp(prefix="relay-bot-")
    path = os.path.join(tmp, "qr.png")
    try:
        subprocess.run(["qrencode", "-o", path, "-s", "6", "-m", "2"], input=payload,
                       capture_output=True, text=True, timeout=15)
        if not os.path.exists(path):
            return False
        r = api("sendPhoto", {"chat_id": chat, "caption": caption[:1000], "parse_mode": "HTML"},
                files={"photo": path})
        return bool(r.get("ok"))
    except Exception:
        return False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def panel_call(path, method="GET", body=None):
    """Вызов API панели. Возвращает (ok, response|текст ошибки)."""
    env = read_kv(PANEL_ENV)
    url, token = env.get("PANEL_URL"), env.get("PANEL_TOKEN")
    if not (url and token):
        return False, "нет PANEL_URL/PANEL_TOKEN"
    cfg = ['url = "%s%s"' % (url, path), 'header = "Authorization: Bearer %s"' % token,
           "silent", "max-time = 20", 'write-out = "\\n%{http_code}"']
    if method != "GET":
        cfg.append('request = "%s"' % method)
        cfg.append('header = "Content-Type: application/json"')
        cfg.append('data = "%s"' % esc(json.dumps(body if body is not None else {})))
    try:
        out = subprocess.run(["curl", "--config", "-"], input="\n".join(cfg),
                             capture_output=True, text=True, timeout=30)
        raw, _, code = (out.stdout or "").rpartition("\n")
        data = json.loads(raw or "{}")
        if code.startswith("2"):
            return True, data.get("response")
        msg = data.get("message") or data.get("error") or data
        if isinstance(msg, list):
            msg = "; ".join(str(m) for m in msg)
        return False, "HTTP %s: %s" % (code or "?", str(msg)[:200])
    except Exception as exc:
        return False, "панель не ответила (%s)" % type(exc).__name__


def panel(path):
    ok, resp = panel_call(path)
    return resp if ok else None


def flatten_user(u):
    """Поля onlineAt/usedTrafficBytes/lastConnectedNode панель кладёт в userTraffic —
    поднимаем их на верхний уровень, чтобы дальше читать плоско."""
    tr = u.get("userTraffic") or {}
    for k in ("onlineAt", "usedTrafficBytes", "lifetimeUsedTrafficBytes", "lastConnectedNode"):
        if u.get(k) is None and tr.get(k) is not None:
            u[k] = tr[k]
    return u


def panel_users():
    """Список юзеров панели без служебных. None = панель недоступна."""
    resp = panel("/api/users?size=500")
    if resp is None:
        return None
    us = resp.get("users") if isinstance(resp, dict) else resp
    return [flatten_user(u) for u in us or []
            if (u.get("username") or "").lower() not in SERVICE_USERS]


def find_user(name):
    """→ (user|None, текст ошибки|None). Точное имя, иначе подстрока."""
    if not name:
        return None, "Напиши <code>/user имя</code> — как в панели."
    users = panel_users()
    if users is None:
        return None, "Панель недоступна (см. %s)." % PANEL_ENV
    q = name.lower()
    hit = [u for u in users if (u.get("username") or "").lower() == q]
    if not hit:
        hit = [u for u in users if q in (u.get("username") or "").lower()]
    if not hit:
        return None, "Юзер <b>%s</b> в панели не найден." % html.escape(name)
    if len(hit) > 1:
        return None, "Нашёл несколько: " + ", ".join(html.escape(u["username"]) for u in hit[:10])
    return hit[0], None


def squads():
    """{имя.lower(): uuid} внутренних сквадов."""
    resp = panel("/api/internal-squads") or {}
    items = resp.get("internalSquads") if isinstance(resp, dict) else resp
    return {(s.get("name") or "").lower(): s.get("uuid") for s in items or [] if s.get("uuid")}


def hhmm(ts):
    return time.strftime("%d.%m %H:%M", time.gmtime(ts + TZ_SHIFT))


def human(seconds):
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    d, h = divmod(h, 24)
    if d:
        return "%d сут %d ч" % (d, h)
    if h:
        return "%d ч %02d мин" % (h, m)
    if m:
        return "%d мин" % m
    return "%d с" % s


def iso_ts(s):
    """ISO-дата панели (2026-08-25T10:11:12.345Z) → unix, None если пусто/битая."""
    if not s:
        return None
    try:
        s = re.sub(r"\.\d+", "", s.replace("Z", "+00:00"))
        return datetime.fromisoformat(s).timestamp()
    except Exception:
        return None


def iso_from(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def gb(nbytes):
    try:
        return "%.1f ГБ" % (float(nbytes) / 1e9)
    except Exception:
        return "?"


def runs(since):
    out = []
    try:
        for line in open(RUN_LOG):
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if rec.get("t", 0) >= since:
                out.append(rec)
    except Exception:
        pass
    return out


def outage_stats(window, label):
    now = time.time()
    rs = runs(now - window)
    if not rs:
        return "• %s: нет данных" % label
    bad = [r for r in rs if r.get("f")]
    streak = best = 0
    for r in rs:
        streak = streak + 1 if r.get("f") else 0
        best = max(best, streak)
    tun = len([r for r in bad if any("туннель" in f for f in r["f"])])
    line = ("• %s: прогонов %d, с провалами %d (%.1f%%), туннель падал %d, "
            "макс. подряд %d" % (label, len(rs), len(bad), 100.0 * len(bad) / len(rs), tun, best))
    if bad:
        last = bad[-1]
        line += "\n  последний провал %s — %s" % (hhmm(last["t"]), ", ".join(last["f"])[:90])
    return line


def probe_now():
    try:
        out = subprocess.run([PROBE, "--dry-run"], capture_output=True, text=True, timeout=90)
        lines = [l for l in (out.stdout or "").splitlines()
                 if l.startswith(("OK", "FAIL", "SKIP"))]
        return lines or ["пробник не ответил"]
    except Exception as exc:
        return ["пробник упал: %s" % type(exc).__name__]


def probe_lines():
    out = []
    for l in probe_now():
        mark = "✅" if l.startswith("OK") else ("⏭" if l.startswith("SKIP") else "❌")
        out.append("%s <code>%s</code>" % (mark, html.escape(l[4:].strip())))
    return out


def sh(cmd):
    try:
        return subprocess.run(cmd, shell=True, capture_output=True, text=True,
                              timeout=10).stdout.strip()
    except Exception:
        return "?"


def conntrack_full():
    v = sh("dmesg -T 2>/dev/null | grep -c 'table full'")
    return int(v) if v.isdigit() else None


def local_health():
    ct = sh("sysctl -n net.netfilter.nf_conntrack_count net.netfilter.nf_conntrack_max "
            "2>/dev/null | paste -sd/")
    load = sh("cut -d' ' -f1-3 /proc/loadavg")
    mem = sh("free -m | awk '/^Mem:/ {print $3\"/\"$2\" МБ\"}'")
    up = sh("cut -d. -f1 /proc/uptime")
    dockr = sh("docker ps --format '{{.Names}}' 2>/dev/null | tr '\\n' ' '")
    return ["• conntrack: %s" % (ct or "?"),
            "• load: %s | память: %s" % (load, mem),
            "• аптайм ноды: %s" % human(int(up) if up.isdigit() else 0),
            "• контейнеры: %s" % (dockr or "?")]


# ---------- разделы ----------

def build_stat():
    lines = ["<b>VPN-релей · сводка</b>", "<i>%s МСК</i>" % hhmm(time.time()), ""]
    lines.append("<b>Сейчас</b>")
    lines += probe_lines()
    lines.append("")
    lines.append("<b>Обрывы по истории пробника</b>")
    lines.append(outage_stats(24 * 3600, "24 ч"))
    lines.append(outage_stats(7 * 24 * 3600, "7 дней"))

    nodes = panel("/api/nodes")
    if nodes is not None:
        lines.append("")
        lines.append("<b>Ноды</b>")
        for n in nodes or []:
            name = NODE_NAMES.get(n.get("name"), n.get("name"))
            mark = "✅" if n.get("isConnected") else "❌"
            lines.append("%s %s — онлайн %s" % (mark, html.escape(str(name)), n.get("usersOnline")))
    users = panel_users()
    if users is not None:
        now = time.time()
        online = [u for u in users if (iso_ts(u.get("onlineAt")) or 0) > now - ONLINE_WINDOW]
        by = {}
        for u in users:
            by[u.get("status")] = by.get(u.get("status"), 0) + 1
        lines.append("")
        lines.append("<b>Юзеры</b>: онлайн %d · " % len(online)
                     + ", ".join("%s %d" % (k, v) for k, v in sorted(by.items())))

    lines.append("")
    lines.append("<b>Выходная нода</b>")
    lines += local_health()
    return "\n".join(lines)


def build_check():
    return "\n".join(["<b>Входы релея сейчас</b> <i>(%s МСК)</i>" % hhmm(time.time()), ""]
                     + probe_lines())


def user_line(u, now):
    name = html.escape(u.get("username") or "?")
    st = u.get("status")
    on = iso_ts(u.get("onlineAt"))
    if st != "ACTIVE":
        mark, when = "❌", st
    elif not u.get("activeInternalSquads"):
        mark, when = "❌", "без сквада"
    elif on and on > now - ONLINE_WINDOW:
        mark, when = "🟢", "онлайн"
    elif on:
        mark, when = "⚪", "был %s назад" % human(now - on)
    else:
        mark, when = "⚪", "не подключался"
    parts = ["%s <b>%s</b> · %s" % (mark, name, when)]
    tr = gb(u.get("usedTrafficBytes") or 0)
    lim = u.get("trafficLimitBytes") or 0
    parts.append(tr + (" / " + gb(lim) if lim else ""))
    exp = iso_ts(u.get("expireAt"))
    if exp:
        left = exp - now
        flag = " ⚠️" if 0 < left < EXPIRE_WARN else (" ⛔" if left <= 0 else "")
        parts.append("до %s%s" % (time.strftime("%d.%m.%y", time.gmtime(exp + TZ_SHIFT)), flag))
    return " · ".join(parts)


def build_users():
    users = panel_users()
    if users is None:
        return "Панель недоступна (см. %s)." % PANEL_ENV
    now = time.time()

    def key(u):
        on = iso_ts(u.get("onlineAt")) or 0
        return (0 if on > now - ONLINE_WINDOW else 1, -on, (u.get("username") or "").lower())

    users.sort(key=key)
    online = sum(1 for u in users if (iso_ts(u.get("onlineAt")) or 0) > now - ONLINE_WINDOW)
    lines = ["<b>Юзеры</b> — %d, онлайн %d <i>(%s МСК)</i>" % (len(users), online, hhmm(now)), ""]
    lines += [user_line(u, now) for u in users]
    lines += ["", "<i>Карточка и действия: /user имя</i>"]
    return "\n".join(lines)


def card_markup(u):
    """Inline-кнопки под карточкой юзера. callback_data ≤ 64 байт: a:<act>:<username>."""
    name = u.get("username") or ""
    toggle = ("🟢 Включить", "en") if u.get("status") != "ACTIVE" else ("🔴 Отключить", "dis")
    rows = [[{"text": toggle[0], "callback_data": "a:%s:%s" % (toggle[1], name)},
             {"text": "📅 +%d дней" % EXTEND_DAYS, "callback_data": "a:ext:%s" % name}],
            [{"text": "♻️ Сбросить трафик", "callback_data": "a:rst:%s" % name},
             {"text": "🔗 Подписка", "callback_data": "a:sub:%s" % name}],
            [{"text": "📱 Устройства", "callback_data": "a:dev:%s" % name}]]
    return json.dumps({"inline_keyboard": rows}, ensure_ascii=False)


def user_card(u):
    now = time.time()
    st = u.get("status")
    sq = [s.get("name") if isinstance(s, dict) else str(s)
          for s in u.get("activeInternalSquads") or []]
    on = iso_ts(u.get("onlineAt"))
    exp = iso_ts(u.get("expireAt"))
    node = u.get("lastConnectedNode") or {}
    node_name = node.get("nodeName") if isinstance(node, dict) else node
    lim = u.get("trafficLimitBytes") or 0
    lines = ["<b>%s</b>" % html.escape(u.get("username") or "?"),
             "• статус: %s" % st,
             "• сквады: %s" % (", ".join(html.escape(s) for s in sq) or "—"),
             "• онлайн: %s" % ("сейчас" if on and on > now - ONLINE_WINDOW
                               else ("%s (%s назад)" % (hhmm(on), human(now - on)) if on
                                     else "никогда")),
             "• трафик: %s%s" % (gb(u.get("usedTrafficBytes") or 0), " / " + gb(lim) if lim else ""),
             "• срок: %s" % (("до %s (%s)" % (hhmm(exp), "истёк" if exp <= now
                                               else "осталось " + human(exp - now)))
                             if exp else "бессрочно")]
    if node_name:
        lines.append("• последняя нода: %s" % html.escape(str(NODE_NAMES.get(node_name, node_name))))
    if u.get("description"):
        lines.append("• заметка: %s" % html.escape(str(u["description"])[:120]))
    lines.append("")
    lines.append("<b>Диагноз</b>")
    if st != "ACTIVE" or not sq:
        lines.append("⛔ Не ACTIVE или без сквада — синк снял клиента с релея. "
                     "Включить (кнопка ниже или панель), доступ вернётся за ~5 мин.")
    elif exp and exp <= now:
        lines.append("⛔ Срок истёк — продлить кнопкой ниже.")
    elif lim and (u.get("usedTrafficBytes") or 0) >= lim:
        lines.append("⛔ Лимит трафика исчерпан — сбросить кнопкой ниже или поднять в панели.")
    elif on and on > now - ONLINE_WINDOW:
        lines.append("🟢 Сервер его видит прямо сейчас — если «не работает», проблема на "
                     "телефоне/у оператора: обновить подписку, выключить второй VPN, "
                     "попробовать XHTTP 6443 / gRPC 9444.")
    elif on and on > now - 24 * 3600:
        lines.append("⚪ Был %s назад, сервер в порядке. Чеклист на телефоне: обновить "
                     "подписку, выключить второй VPN (OpenVPN), порт 6443/9444, "
                     "проверить с Wi-Fi." % human(now - on))
    else:
        lines.append("⚪ Давно не подключался — до релея не доходит. Обновить подписку в "
                     "приложении; если и после этого нет строк по юзеру на релее "
                     "(<code>journalctl -u xray | grep email</code>) — оператор/DPI или "
                     "второй туннель на телефоне.")
    return "\n".join(lines), card_markup(u)


def build_user(name):
    u, err = find_user(name)
    if err:
        return err
    return user_card(u)


def episodes(window):
    """Подряд идущие провалы пробника → эпизоды (начало, конец, число прогонов,
    множество целей, «всё мертво» хотя бы раз)."""
    eps, cur = [], None
    for r in runs(time.time() - window):
        if r.get("f"):
            if cur is None:
                cur = {"start": r["t"], "end": r["t"], "n": 0, "what": set(), "all": False}
            cur["end"] = r["t"]
            cur["n"] += 1
            cur["what"].update(r["f"])
            if r.get("n") and len(r["f"]) >= r["n"]:
                cur["all"] = True
        elif cur is not None:
            eps.append(cur)
            cur = None
    if cur is not None:
        cur["open"] = True
        eps.append(cur)
    return eps


def build_outages():
    window = 7 * 24 * 3600
    eps = episodes(window)
    now = time.time()
    lines = ["<b>Обрывы за 7 дней</b> <i>(%s МСК)</i>" % hhmm(now), ""]
    if not eps:
        lines.append("Провалов не было 🎉")
    else:
        total = 0
        for e in eps:
            dur = e["end"] - e["start"] + 180          # прогон раз в 3 мин
            total += dur
            tag = ""
            if e["all"] and e["n"] <= 3:
                tag = " · суточный стоп ВМ (норма)"
            elif e["all"]:
                tag = " · мертво всё"
            what = "" if e["all"] else ", ".join(sorted(e["what"]))
            lines.append("• %s — %s%s%s%s" % (
                hhmm(e["start"]), human(dur), " ⏳ идёт" if e.get("open") else "", tag,
                (" — " + html.escape(what[:80])) if what else ""))
        lines.append("")
        lines.append("Эпизодов: %d, суммарно ~%s (%.2f%% недели)."
                     % (len(eps), human(total), 100.0 * total / window))
    lines += ["", outage_stats(24 * 3600, "24 ч"), outage_stats(window, "7 дней")]
    if len(lines) > 60:
        lines = lines[:2] + ["<i>показаны последние 40</i>"] + lines[-52:]
    return "\n".join(lines)


def build_node():
    full = conntrack_full()
    last = sh(r"dmesg -T 2>/dev/null | grep 'table full' | tail -1 | sed 's/^\[\(.*\)\].*/\1/'")
    lines = ["<b>Выходная нода (Kamatera)</b> <i>(%s МСК)</i>" % hhmm(time.time()), ""]
    lines += local_health()
    lines.append("• conntrack «table full» с загрузки: %s%s"
                 % ("?" if full is None else full,
                    (" (последний: %s)" % html.escape(last)) if last else ""))
    if full:
        lines.append("  ⚠️ если дата новее фикса conntrack (19.08.2026) — таблица снова мала, "
                     "поднимать nf_conntrack_max")
    return "\n".join(lines)


def yc_report():
    """Готовый отчёт с релея: ключ бота там заперт forced-command'ом на
    yc-traffic-report.py --dry-run (vnstat + трафик в CDN). → текст|None."""
    try:
        out = subprocess.run(["ssh", "-i", YC_KEY, "-o", "BatchMode=yes",
                              "-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=8",
                              YC_HOST, "yc-traffic-report.py --dry-run"],
                             capture_output=True, text=True, timeout=25)
    except Exception:
        return None
    text = (out.stdout or "").strip()
    return text if out.returncode == 0 and text else None


def build_traffic():
    report = yc_report()
    if report is None:
        lines = ["<b>Трафик YC-релея</b> <i>(%s МСК)</i>" % hhmm(time.time()), "",
                 "Релей не ответил по ssh — возможно, суточный стоп ВМ (~5 мин), "
                 "или нет ключа %s." % YC_KEY]
    else:
        head, _, rest = report.partition("\n")
        lines = ["%s <i>(%s МСК)</i>" % (head, hhmm(time.time())), rest]
    users = panel_users()
    if users:
        top = sorted(users, key=lambda u: -(u.get("usedTrafficBytes") or 0))[:5]
        total = sum((u.get("usedTrafficBytes") or 0) for u in users) or 1
        lines.append("")
        lines.append("<b>Топ юзеров</b> <i>(с последнего сброса в панели)</i>")
        for u in top:
            used = u.get("usedTrafficBytes") or 0
            if not used:
                break
            lines.append("• %s — %s (%.0f%%)" % (html.escape(u["username"]), gb(used), 100.0 * used / total))
    return "\n".join(lines)


def build_help():
    return ("<b>📖 Инструкция к боту VPN-релея</b>\n\n"
            "<b>Кнопки</b>\n"
            "%(stat)s — всё сразу: входы релея, обрывы, ноды, юзеры, выходная нода\n"
            "%(check)s — только входы релея и сквозной туннель (~10 с)\n"
            "%(users)s — список: 🟢 онлайн (&lt;5 мин) · ⚪ был N назад · ❌ отключён; трафик; "
            "срок (⚠️ &lt;7 дн, ⛔ истёк)\n"
            "%(outages)s — эпизоды простоев за 7 дней; «суточный стоп ВМ» — норма\n"
            "%(traffic)s — сколько из 100 ГБ/мес YC съедено и из пакета CDN 150 ГБ, остаток, прогноз, топ-5 юзеров\n"
            "%(node)s — conntrack, load, память, аптайм, контейнеры Kamatera\n"
            "%(add)s — опросник: имя → срок → лимит → сквад → подтверждение\n\n"
            "<b>Команды</b>\n"
            "<code>/user имя</code> — карточка юзера (можно часть имени) с диагнозом и кнопками:\n"
            "  🔴 Отключить / 🟢 Включить — доступ снимается/возвращается за ≤5 мин\n"
            "  📅 +%(days)d дней — продлить от текущего срока (истёкший — от сегодня)\n"
            "  ♻️ Сбросить трафик — обнулить счётчик лимита\n"
            "  🔗 Подписка — ссылка + QR, переслать человеку\n"
            "  📱 Устройства — с каких телефонов забирали подписку (HWID)\n"
            "<code>/add имя [дней=%(days)d] [ГБ=0] [сквад=%(squad)s]</code> — новый юзер одной "
            "строкой, без опросника. Пример: <code>/add Ivan 90 200</code>\n"
            "Любое изменение — только после кнопки «✅ Да» (живёт 10 мин).\n\n"
            "<b>Сценарии</b>\n"
            "• <i>Подключить человека</i>: %(add)s → ответить на 4 вопроса → Да → переслать ему ссылку/QR → "
            "он ставит Happ/INCY/v2rayTun и вставляет подписку. Через 5 мин работает.\n"
            "• <i>«У меня не работает»</i>: <code>/user Имя</code> — читать «Диагноз». Если он "
            "онлайн — виноват телефон (обновить подписку, выключить второй VPN, порт 6443/9444). "
            "Если у всех сразу — %(check)s: мёртво всё ≈ суточный стоп ВМ, ждать 5 мин.\n"
            "• <i>Продлить / отключить</i>: <code>/user Имя</code> → кнопка → Да.\n"
            "• <i>Кто жрёт трафик</i>: %(traffic)s.\n\n"
            "<b>Само приходит</b>: аварии релея (пробник каждые 3 мин, алерт после 9 мин), "
            "нода пропала/вернулась, юзер впервые подключился, срок ≤3 дн / истёк (кнопка продлить), "
            "трафик ≥90 %% (кнопка сброса), переполнение conntrack. Проверка раз в 10 мин."
            % {"stat": BTN_STAT, "check": BTN_CHECK, "users": BTN_USERS, "outages": BTN_OUTAGES,
               "traffic": BTN_TRAFFIC, "node": BTN_NODE, "add": BTN_ADD,
               "days": EXTEND_DAYS, "squad": DEFAULT_SQUAD})


def build_add_hint():
    return ("Формат: <code>/add имя [дней=%d] [ГБ=0] [сквад=%s]</code>\n"
            "Имя — латиница/цифры/_/-, 3–36 символов. Пример: <code>/add Ivan 90 200</code>"
            % (EXTEND_DAYS, DEFAULT_SQUAD))


# ---------- действия (через подтверждение) ----------

ACTION_LABEL = {"en": "включить", "dis": "отключить", "ext": "продлить на %d дней" % EXTEND_DAYS,
                "rst": "сбросить трафик", "add": "создать юзера"}


def pending_add(act, user, args=None):
    """Регистрирует действие, возвращает inline-клавиатуру Да/Отмена."""
    now = time.time()
    for k in [k for k, v in PENDING.items() if now - v["t"] > PENDING_TTL]:
        PENDING.pop(k, None)
    pid = secrets.token_hex(4)
    PENDING[pid] = {"act": act, "user": user, "args": args or {}, "t": now}
    return json.dumps({"inline_keyboard": [[
        {"text": "✅ Да", "callback_data": "c:%s:y" % pid},
        {"text": "✖ Отмена", "callback_data": "c:%s:n" % pid}]]}, ensure_ascii=False)


def confirm_text(act, user, args):
    if act == "add":
        return ("Создать юзера <b>%s</b>: %d дн., лимит %s, сквад %s?"
                % (html.escape(user), args["days"], gb(args["bytes"]) if args["bytes"] else "без",
                   html.escape(args["squad"])))
    return "Точно <b>%s</b> юзера <b>%s</b>?" % (ACTION_LABEL[act], html.escape(user))


def do_action(act, name, args):
    """Выполнение подтверждённого действия. → (текст, markup|None, sub_payload|None)."""
    if act == "add":
        return do_add(name, args)
    u, err = find_user(name)
    if err:
        return err, None, None
    uuid = u.get("uuid")
    if act in ("en", "dis"):
        ok, resp = panel_call("/api/users/%s/actions/%s" % (uuid, "enable" if act == "en" else "disable"),
                              "POST")
    elif act == "rst":
        ok, resp = panel_call("/api/users/%s/actions/reset-traffic" % uuid, "POST")
    elif act == "ext":
        base = max(time.time(), iso_ts(u.get("expireAt")) or 0)
        ok, resp = panel_call("/api/users", "PATCH",
                              {"uuid": uuid, "expireAt": iso_from(base + EXTEND_DAYS * 86400)})
        if ok and u.get("status") == "EXPIRED":
            u2, _ = find_user(name)
            if u2 and u2.get("status") == "EXPIRED":
                ok, resp = panel_call("/api/users/%s/actions/enable" % uuid, "POST")
    else:
        return "Неизвестное действие.", None, None
    if not ok:
        return "❌ Панель отказала: %s" % html.escape(str(resp)), None, None
    u2, err = find_user(name)
    if err:
        return "✅ Сделано, но карточку не перечитал: %s" % err, None, None
    text, markup = user_card(u2)
    note = "" if act == "rst" else "\n<i>На релее применится за ≤5 мин (синк).</i>"
    return "✅ %s — %s.%s\n\n%s" % (html.escape(name), ACTION_LABEL[act], note, text), markup, None


def do_add(name, args):
    sq = squads()
    suuid = sq.get(args["squad"].lower())
    if not suuid:
        return "Сквад <b>%s</b> не найден. Есть: %s" % (html.escape(args["squad"]),
                                                        ", ".join(sq) or "—"), None, None
    body = {"username": name, "expireAt": iso_from(time.time() + args["days"] * 86400),
            "trafficLimitBytes": int(args["bytes"]), "trafficLimitStrategy": "NO_RESET",
            "activeInternalSquads": [suuid],
            "description": "создан ботом %s" % time.strftime("%d.%m.%Y")}
    ok, resp = panel_call("/api/users", "POST", body)
    if not ok:
        return "❌ Панель отказала: %s" % html.escape(str(resp)), None, None
    u = flatten_user(resp if isinstance(resp, dict) else {})
    if not u.get("username"):
        u, _ = find_user(name)
    text, markup = user_card(u)
    return ("✅ Юзер <b>%s</b> создан. Ссылка подписки — следующим сообщением; на релее доступ "
            "появится за ≤5 мин (синк).\n\n%s" % (html.escape(name), text), markup,
            u.get("subscriptionUrl"))


def sub_message(u):
    url = u.get("subscriptionUrl")
    if not url:
        return None, None
    text = ("🔗 Подписка <b>%s</b>:\n<code>%s</code>\n<i>Вставить в Happ/INCY/v2rayTun "
            "как ссылку подписки или отсканировать QR.</i>" % (html.escape(u["username"]), html.escape(url)))
    return text, url


def build_devices(u):
    ok, resp = panel_call("/api/hwid/devices/%s" % u.get("uuid"))
    if not ok:
        return "❌ %s" % html.escape(str(resp))
    devs = (resp or {}).get("devices") if isinstance(resp, dict) else resp
    lines = ["📱 Устройства <b>%s</b> — %d" % (html.escape(u["username"]), len(devs or []))]
    if u.get("hwidDeviceLimit"):
        lines[0] += " / лимит %s" % u["hwidDeviceLimit"]
    for d in devs or []:
        seen = iso_ts(d.get("updatedAt"))
        lines.append("• %s %s (%s) — %s, активность %s" % (
            html.escape(str(d.get("platform") or "?")), html.escape(str(d.get("deviceModel") or "")),
            html.escape(str(d.get("osVersion") or "")),
            html.escape(str(d.get("userAgent") or "")[:40]),
            hhmm(seen) if seen else "?"))
    if not devs:
        lines.append("<i>ни одного — приложение ещё не забирало подписку с HWID</i>")
    return "\n".join(lines)


def parse_add(rest):
    """'/add имя [дней] [ГБ] [сквад]' → (args|None, ошибка|None)."""
    parts = rest.split()
    if not parts:
        return None, build_add_hint()
    name = parts[0]
    if not USERNAME_RE.match(name):
        return None, "Имя <b>%s</b> не подходит: латиница/цифры/_/-, 3–36 символов." % html.escape(name)
    days, gbs, squad = EXTEND_DAYS, 0.0, DEFAULT_SQUAD
    try:
        if len(parts) > 1:
            days = int(parts[1])
        if len(parts) > 2:
            gbs = float(parts[2].replace(",", "."))
        if len(parts) > 3:
            squad = parts[3]
    except ValueError:
        return None, build_add_hint()
    if not (1 <= days <= 3650) or gbs < 0:
        return None, "Дней 1–3650, ГБ ≥ 0."
    return {"name": name, "days": days, "bytes": int(gbs * GIB), "squad": squad}, None


def handle_add(rest):
    args, err = parse_add(rest)
    if err:
        return err
    users = panel_users()
    if users is None:
        return "Панель недоступна (см. %s)." % PANEL_ENV
    if any((u.get("username") or "").lower() == args["name"].lower() for u in users):
        return "Юзер <b>%s</b> уже есть — смотри <code>/user %s</code>." % (
            html.escape(args["name"]), html.escape(args["name"]))
    return confirm_text("add", args["name"], args), pending_add("add", args["name"], args)


# ---------- опросник создания юзера ----------

WIZ = {}                       # состояние опросника (один чат): step, name, days, bytes, squad, t
WIZ_TTL = 600
DAYS_CHOICES = [(30, "30 дней"), (90, "90 дней"), (180, "180 дней"), (365, "1 год"),
                (3650, "10 лет (бессрочно)")]
GB_CHOICES = [(0, "Без лимита"), (50, "50 ГБ"), (100, "100 ГБ"), (200, "200 ГБ"), (500, "500 ГБ")]


def wiz_markup(rows):
    rows = list(rows) + [[{"text": "✖ Отмена", "callback_data": "w:x:0"}]]
    return json.dumps({"inline_keyboard": rows}, ensure_ascii=False)


def wiz_active():
    return bool(WIZ) and time.time() - WIZ.get("t", 0) < WIZ_TTL


def wiz_start():
    WIZ.clear()
    WIZ.update({"step": "name", "t": time.time()})
    return ("<b>Новый юзер · шаг 1/4</b>\nНапиши имя: латиница, цифры, <code>_</code> или "
            "<code>-</code>, 3–36 символов (например <code>Ivan_2026</code>).", wiz_markup([]))


def wiz_ask_days():
    WIZ["step"] = "days"
    rows = [[{"text": l, "callback_data": "w:d:%d" % d} for d, l in DAYS_CHOICES[:3]],
            [{"text": l, "callback_data": "w:d:%d" % d} for d, l in DAYS_CHOICES[3:]],
            [{"text": "✏️ Свой срок (дней)", "callback_data": "w:d:custom"}]]
    return "<b>%s · шаг 2/4</b>\nСрок доступа:" % html.escape(WIZ["name"]), wiz_markup(rows)


def wiz_ask_gb():
    WIZ["step"] = "gb"
    rows = [[{"text": l, "callback_data": "w:g:%d" % g} for g, l in GB_CHOICES[:3]],
            [{"text": l, "callback_data": "w:g:%d" % g} for g, l in GB_CHOICES[3:]],
            [{"text": "✏️ Свой лимит (ГБ)", "callback_data": "w:g:custom"}]]
    return ("<b>%s · шаг 3/4</b>\nЛимит трафика (без сброса по периоду):" % html.escape(WIZ["name"]),
            wiz_markup(rows))


def wiz_ask_squad():
    WIZ["step"] = "squad"
    names = sorted(squads()) or [DEFAULT_SQUAD.lower()]
    rows = [[{"text": n.capitalize(), "callback_data": "w:s:%s" % n}] for n in names]
    return ("<b>%s · шаг 4/4</b>\nСквад (External — все юзеры):"
            % html.escape(WIZ["name"]), wiz_markup(rows))


def wiz_finish():
    args = {"name": WIZ["name"], "days": WIZ["days"], "bytes": WIZ["bytes"], "squad": WIZ["squad"]}
    WIZ.clear()
    return confirm_text("add", args["name"], args), pending_add("add", args["name"], args)


def wiz_text(text):
    """Текстовый ответ на шаг опросника. → (текст, markup) | None если шаг не ждёт текста."""
    step = WIZ.get("step")
    WIZ["t"] = time.time()
    t = text.strip()
    if step == "name":
        if not USERNAME_RE.match(t):
            return ("Имя <b>%s</b> не подходит: латиница/цифры/_/-, 3–36 символов. Попробуй ещё."
                    % html.escape(t), wiz_markup([]))
        users = panel_users()
        if users is None:
            WIZ.clear()
            return "Панель недоступна (см. %s)." % PANEL_ENV, None
        if any((u.get("username") or "").lower() == t.lower() for u in users):
            return ("Юзер <b>%s</b> уже есть — другое имя (или <code>/user %s</code>)."
                    % (html.escape(t), html.escape(t)), wiz_markup([]))
        WIZ["name"] = t
        return wiz_ask_days()
    if step == "days_custom":
        if not t.isdigit() or not (1 <= int(t) <= 3650):
            return "Число дней от 1 до 3650.", wiz_markup([])
        WIZ["days"] = int(t)
        return wiz_ask_gb()
    if step == "gb_custom":
        try:
            g = float(t.replace(",", "."))
            assert g >= 0
        except Exception:
            return "Число ГБ ≥ 0 (0 — без лимита).", wiz_markup([])
        WIZ["bytes"] = int(g * GIB)
        return wiz_ask_squad()
    return None


def wiz_cb(field, value):
    """Кнопка шага. → ((текст следующего шага, markup), подпись выбора для старого сообщения)."""
    WIZ["t"] = time.time()
    if field == "x":
        WIZ.clear()
        return ("Создание отменено.", None), "отменено"
    if not wiz_active() or "name" not in WIZ:
        WIZ.clear()
        return ("Опросник устарел — нажми «%s» заново." % BTN_ADD, None), "устарело"
    if field == "d":
        if value == "custom":
            WIZ["step"] = "days_custom"
            return ("Напиши число дней (1–3650):", wiz_markup([])), "свой срок"
        WIZ["days"] = int(value)
        return wiz_ask_gb(), dict(DAYS_CHOICES).get(int(value), value)
    if field == "g":
        if value == "custom":
            WIZ["step"] = "gb_custom"
            return ("Напиши лимит в ГБ (0 — без лимита):", wiz_markup([])), "свой лимит"
        WIZ["bytes"] = int(int(value) * GIB)
        return wiz_ask_squad(), dict(GB_CHOICES).get(int(value), value)
    if field == "s":
        WIZ["squad"] = value.capitalize()
        return wiz_finish(), value.capitalize()
    return ("Не понял кнопку.", None), "?"


# ---------- маршрутизация ----------

ALL_BUTTONS = {b.lower() for b in (BTN_STAT, BTN_CHECK, BTN_USERS, BTN_OUTAGES,
                                   BTN_TRAFFIC, BTN_NODE, BTN_ADD, BTN_HELP)}

ROUTES = [
    ((BTN_STAT.lower(), "/stat", "/stats", "стат", "статистика", "status"), build_stat),
    ((BTN_CHECK.lower(), "/check", "проверить", "проверка", "чек"), build_check),
    ((BTN_USERS.lower(), "/users", "юзеры", "юзера", "пользователи"), build_users),
    ((BTN_OUTAGES.lower(), "/outages", "обрывы", "простои", "история"), build_outages),
    ((BTN_TRAFFIC.lower(), "/traffic", "трафик"), build_traffic),
    ((BTN_NODE.lower(), "/node", "нода", "сервер"), build_node),
    ((BTN_ADD.lower(),), wiz_start),
    ((BTN_HELP.lower(), "/start", "/help", "help", "хелп", "помощь", "инструкция", "?"), build_help),
]


def handle(text):
    """Текст сообщения → ответ: str или (str, inline_markup)."""
    t = text.strip()
    low = t.lower()
    if wiz_active() and not low.startswith("/") and low not in ALL_BUTTONS:
        r = wiz_text(t)
        if r is not None:
            return r
    elif WIZ:
        WIZ.clear()                            # команда или кнопка прерывает опросник
    m = re.match(r"^(?:/user|юзер|user)(?:@\w+)?\s*(.*)$", low)
    if m and not low.startswith(("/users", "юзеры")):
        return build_user(t[m.start(1):].strip())
    m = re.match(r"^(?:/add|добавить|новый)(?:@\w+)?\s*(.*)$", low)
    if m:
        rest = t[m.start(1):].strip()
        return handle_add(rest) if rest else wiz_start()
    word = re.sub(r"@\w+$", "", low.split()[0]) if low.split() else ""
    for keys, fn in ROUTES:
        if low in keys or word in keys or any(low.startswith(k) for k in keys if len(k) > 3):
            return fn()
    return "Не понял. Жми кнопки, <code>/user имя</code> или <code>/add имя</code>."


def handle_callback(chat, cq):
    """Нажатие inline-кнопки. Отвечает сам (несколько сообщений), ничего не возвращает."""
    data = cq.get("data") or ""
    msg = cq.get("message") or {}
    api("answerCallbackQuery", {"callback_query_id": cq.get("id", "")})
    parts = data.split(":", 2)
    if parts[0] == "a" and len(parts) == 3:
        act, name = parts[1], parts[2]
        if act in ACTION_LABEL:
            send(chat, confirm_text(act, name, {}), pending_add(act, name))
            return
        u, err = find_user(name)
        if err:
            send(chat, err)
            return
        if act == "sub":
            text, url = sub_message(u)
            if not text:
                send(chat, "У юзера нет ссылки подписки.")
                return
            send(chat, text)
            send_qr(chat, url, "QR подписки <b>%s</b>" % html.escape(u["username"]))
        elif act == "dev":
            send(chat, build_devices(u))
        return
    if parts[0] == "w" and len(parts) == 3:
        (text, markup), chosen = wiz_cb(parts[1], parts[2])
        if msg.get("message_id"):
            api("editMessageText", {"chat_id": chat, "message_id": msg["message_id"],
                                    "parse_mode": "HTML",
                                    "text": (msg.get("text") or "…") + "\n→ %s" % html.escape(str(chosen))})
        send(chat, text, markup)
        return
    if parts[0] == "c" and len(parts) == 3:
        pid, yes = parts[1], parts[2] == "y"
        p = PENDING.pop(pid, None)
        if msg.get("message_id"):
            api("editMessageText", {"chat_id": chat, "message_id": msg["message_id"],
                                    "parse_mode": "HTML",
                                    "text": (msg.get("text") or "…") + ("\n\n→ выполняю" if (yes and p)
                                                                        else "\n\n→ отменено")})
        if not p:
            send(chat, "Кнопка устарела (10 мин) — повтори команду.")
            return
        if not yes:
            return
        try:
            text, markup, sub_url = do_action(p["act"], p["user"], p["args"])
        except Exception as exc:
            text, markup, sub_url = "Ошибка: %s" % type(exc).__name__, None, None
        send(chat, text, markup)
        if sub_url:
            u = {"username": p["user"], "subscriptionUrl": sub_url}
            stext, _ = sub_message(u)
            send(chat, stext)
            send_qr(chat, sub_url, "QR подписки <b>%s</b>" % html.escape(p["user"]))


# ---------- уведомления о событиях ----------

def read_watch():
    try:
        return json.load(open(WATCH_FILE))
    except Exception:
        return {}


def write_watch(state):
    try:
        os.makedirs(os.path.dirname(WATCH_FILE), exist_ok=True)
        tmp = WATCH_FILE + ".tmp"
        json.dump(state, open(tmp, "w"))
        os.replace(tmp, WATCH_FILE)
    except Exception:
        pass


def watch_once():
    """Сравнивает панель/ноду с прошлым состоянием. → [(текст, markup|None)].
    Первый прогон только запоминает состояние — без шквала уведомлений."""
    state = read_watch()
    first = not state
    now = time.time()
    events = []
    notified = state.get("notified", [])

    nodes = panel("/api/nodes")
    if nodes is not None:
        prev = state.get("nodes", {})
        cur = {}
        for n in nodes:
            name, up = n.get("name"), bool(n.get("isConnected"))
            cur[name] = up
            if not first and name in prev and prev[name] != up:
                label = html.escape(str(NODE_NAMES.get(name, name)))
                events.append(("✅ Нода %s снова на связи с панелью." % label if up else
                               "❌ Нода %s пропала из панели (isConnected=false). Трафик может "
                               "идти, но панель её не видит — remnanode на :2222." % label, None))
        state["nodes"] = cur

    users = panel_users()
    if users is not None:
        seen = set(state.get("seen_online", []))
        status = state.get("status", {})
        cur_status = {}
        for u in users:
            name = u.get("username") or ""
            cur_status[name] = u.get("status")
            on = iso_ts(u.get("onlineAt"))
            if on and name not in seen:
                seen.add(name)
                if not first:
                    events.append(("🎉 <b>%s</b> впервые подключился (%s)."
                                   % (html.escape(name), hhmm(on)), None))
            exp = iso_ts(u.get("expireAt"))
            if exp and u.get("status") == "ACTIVE" and 0 < exp - now <= EXPIRE_NOTIFY:
                key = "exp:%s:%s" % (name, u.get("expireAt"))
                if key not in notified:
                    notified.append(key)
                    if not first:
                        events.append(("⏳ У <b>%s</b> срок истекает %s (через %s)."
                                       % (html.escape(name), hhmm(exp), human(exp - now)),
                                       json.dumps({"inline_keyboard": [[{
                                           "text": "📅 +%d дней" % EXTEND_DAYS,
                                           "callback_data": "a:ext:%s" % name}]]})))
            if not first and status.get(name) not in (None, "EXPIRED") and u.get("status") == "EXPIRED":
                events.append(("⛔ <b>%s</b> — срок истёк, панель перевела в EXPIRED." % html.escape(name),
                               json.dumps({"inline_keyboard": [[{
                                   "text": "📅 +%d дней" % EXTEND_DAYS,
                                   "callback_data": "a:ext:%s" % name}]]})))
            lim = u.get("trafficLimitBytes") or 0
            used = u.get("usedTrafficBytes") or 0
            if lim and used >= lim * TRAFFIC_WARN:
                key = "tr:%s:%s" % (name, u.get("lastTrafficResetAt"))
                if key not in notified:
                    notified.append(key)
                    if not first:
                        events.append(("📶 <b>%s</b> использовал %s из %s (%.0f%%)."
                                       % (html.escape(name), gb(used), gb(lim), 100.0 * used / lim),
                                       json.dumps({"inline_keyboard": [[{
                                           "text": "♻️ Сбросить трафик",
                                           "callback_data": "a:rst:%s" % name}]]})))
        state["seen_online"] = sorted(seen)
        state["status"] = cur_status

    full = conntrack_full()
    if full is not None:
        prev = state.get("ctfull")
        if not first and prev is not None and full > prev:
            events.append(("🧱 conntrack на выходной ноде: +%d «table full» — пакеты дропаются "
                           "молча, у всех рвётся. Поднять nf_conntrack_max "
                           "(/etc/sysctl.d/99-conntrack.conf)." % (full - prev), None))
        state["ctfull"] = full

    state["notified"] = notified[-500:]
    state["t"] = now
    write_watch(state)
    return events


# ---------- main ----------

def read_offset():
    try:
        return int(open(OFFSET_FILE).read().strip())
    except Exception:
        return 0


def write_offset(v):
    try:
        os.makedirs(os.path.dirname(OFFSET_FILE), exist_ok=True)
        tmp = OFFSET_FILE + ".tmp"
        open(tmp, "w").write(str(v))
        os.replace(tmp, OFFSET_FILE)
    except Exception:
        pass


def main():
    # для проверки и рунбука: разделы в stdout без Telegram
    cli = {"--stat": build_stat, "--check": build_check, "--users": build_users,
           "--outages": build_outages, "--node": build_node, "--traffic": build_traffic,
           "--help": build_help}
    for flag, fn in cli.items():
        if flag in sys.argv:
            print(fn())
            return 0
    if "--user" in sys.argv:
        i = sys.argv.index("--user")
        r = build_user(sys.argv[i + 1] if len(sys.argv) > i + 1 else "")
        print(r[0] if isinstance(r, tuple) else r)
        return 0
    if "--watch-once" in sys.argv:            # ничего не шлёт, но состояние пишет
        for text, _ in watch_once():
            print(text)
            print("--")
        return 0
    allowed = read_kv(TG_ENV).get("TG_CHAT_ID", "")
    if not allowed:
        print("нет TG_CHAT_ID в %s" % TG_ENV, file=sys.stderr)
        return 1
    offset = read_offset()
    last_watch = 0
    print("бот запущен, отвечаю чату %s" % allowed, flush=True)
    while True:
        upd = api("getUpdates", {"offset": offset, "timeout": POLL_TIMEOUT},
                  timeout=POLL_TIMEOUT + 10)
        if not upd.get("ok"):
            time.sleep(5)
            continue
        for u in upd.get("result", []):
            offset = max(offset, u.get("update_id", 0) + 1)
            cq = u.get("callback_query")
            if cq:
                chat = str(((cq.get("message") or {}).get("chat") or {}).get("id", ""))
                if chat == allowed:
                    try:
                        handle_callback(chat, cq)
                    except Exception as exc:
                        send(chat, "Ошибка: %s" % type(exc).__name__)
                else:
                    api("answerCallbackQuery", {"callback_query_id": cq.get("id", "")})
                continue
            msg = u.get("message") or u.get("edited_message") or {}
            chat = str((msg.get("chat") or {}).get("id", ""))
            text = (msg.get("text") or "").strip()
            if chat != allowed or not text:
                continue
            try:
                reply = handle(text)
            except Exception as exc:
                reply = "Ошибка: %s" % type(exc).__name__
            if isinstance(reply, tuple):
                send(chat, reply[0], reply[1])
            else:
                send(chat, reply)
        write_offset(offset)
        if time.time() - last_watch > WATCH_INTERVAL:
            last_watch = time.time()
            try:
                for text, markup in watch_once():
                    send(allowed, text, markup)
            except Exception as exc:
                print("watch: %s" % type(exc).__name__, file=sys.stderr, flush=True)


if __name__ == "__main__":
    sys.exit(main())
