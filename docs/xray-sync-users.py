#!/usr/bin/env python3
"""Синхронизация юзеров Remnawave -> нативный xray-релей на YC.

Панель пушит клиентов только на remnanode-ноды; YC-релей — ручной конфиг,
поэтому новый юзер без этой синхронизации не проходит VLESS-auth на входе
и в клиенте «не пингуется ни один сервер».

Делает три вещи (идемпотентно, конфиг трогает только при реальных изменениях):
  1. клиенты на всех VLESS-инбаундах = активные юзеры панели (добавляет и убирает);
  2. персональные плечи out-nl-<user> / out-kg-<user> (иначе учёт трафика сливается
     в один аккаунт) + правила роутинга с матчем "user";
  3. xray -test и рестарт сервиса, если конфиг изменился.

Запуск: systemd-таймер xray-sync-users.timer (раз в 5 минут) на YC.
Значения uuid никогда не печатаются.
"""
import copy
import json
import os
import ssl
import subprocess
import sys
import urllib.request

CFG = "/usr/local/etc/xray/config.json"
TOKEN_FILE = "/etc/xray-sync/token"
API = "https://dash.meridianai.ru/api/users?size=500"
XRAY = "/usr/local/bin/xray"

# группы инбаундов -> (шаблон выходного плеча, префикс персональных плеч)
GROUPS = [
    (["in-nl", "in-xhttp", "in-grpc", "in-nl-kamatera"], "out-nl", "out-nl-"),
    (["in-kg"], "out-kg", "out-kg-"),
]

# плечи-шаблоны и fallback: под чистку персональных плеч не попадают
PROTECTED_TAGS = {"out-nl", "out-kg", "out-nl-kamatera", "direct", "block"}

# доля клиентов, больше которой за один прогон не удаляем (защита от битого ответа API)
MAX_REMOVE_SHARE = 0.34


def log(msg):
    print(msg, flush=True)


def fetch_users():
    token = open(TOKEN_FILE).read().strip()
    req = urllib.request.Request(API, headers={"Authorization": "Bearer " + token})
    with urllib.request.urlopen(req, timeout=30, context=ssl.create_default_context()) as r:
        data = json.load(r)
    users = {}
    for u in data["response"]["users"]:
        squads = u.get("activeInternalSquads") or []
        if u.get("status") != "ACTIVE" or not squads or not u.get("vlessUuid"):
            continue
        users[u["username"]] = u["vlessUuid"]
    if not users:
        raise SystemExit("ERROR: панель вернула 0 активных юзеров — конфиг не трогаю")
    return users


def main():
    users = fetch_users()
    cfg = json.load(open(CFG))
    before = json.dumps(cfg, sort_keys=True)
    by_tag = {o.get("tag"): o for o in cfg["outbounds"]}

    # --- 1. клиенты на инбаундах ------------------------------------------
    added, removed = set(), set()
    for inb in cfg["inbounds"]:
        if inb.get("protocol") != "vless":
            continue
        clients = inb.get("settings", {}).get("clients")
        if not clients:
            continue
        stale = [c for c in clients if c.get("email") not in users]
        if stale and len(stale) > max(1, int(len(clients) * MAX_REMOVE_SHARE)):
            log("WARN: %s — пропускаю удаление %d из %d клиентов (похоже на сбой)"
                % (inb.get("tag"), len(stale), len(clients)))
            stale = []
        for c in stale:
            clients.remove(c)
            removed.add(c.get("email"))

        tmpl = clients[0] if clients else {"flow": "xtls-rprx-vision"}
        have = {c.get("email") for c in clients}
        for name, uid in sorted(users.items()):
            if name in have:
                continue
            c = copy.deepcopy(tmpl)
            c["id"] = uid
            c["email"] = name
            clients.append(c)
            added.add(name)

    # --- 2. персональные плечи + правила ----------------------------------
    new_outbounds, new_rules = [], []
    for inbound_tags, tmpl_tag, prefix in GROUPS:
        tmpl = by_tag.get(tmpl_tag)
        if tmpl is None:
            raise SystemExit("ERROR: нет шаблонного плеча %s" % tmpl_tag)
        for name in sorted(users):
            tag = prefix + name
            if tag in by_tag:
                continue
            ob = copy.deepcopy(tmpl)
            ob["tag"] = tag
            for vnext in ob["settings"]["vnext"]:
                for u in vnext["users"]:
                    u["id"] = users[name]
                    u["email"] = name
            new_outbounds.append(ob)
            new_rules.append({
                "type": "field",
                "inboundTag": list(inbound_tags),
                "user": [name],
                "outboundTag": tag,
            })
    # персональные правила должны выигрывать у общих -> в начало
    cfg["routing"]["rules"] = new_rules + cfg["routing"]["rules"]
    cfg["outbounds"].extend(new_outbounds)

    # --- 3. подчистить плечи и правила ушедших юзеров ----------------------
    prefixes = [p for _, _, p in GROUPS]
    dead = set()
    for o in cfg["outbounds"]:
        tag = o.get("tag", "")
        if tag in PROTECTED_TAGS:
            continue
        for pref in prefixes:
            if tag.startswith(pref) and tag[len(pref):] not in users:
                dead.add(tag)
    if dead:
        cfg["outbounds"] = [o for o in cfg["outbounds"] if o.get("tag") not in dead]
        cfg["routing"]["rules"] = [r for r in cfg["routing"]["rules"]
                                   if r.get("outboundTag") not in dead]

    if json.dumps(cfg, sort_keys=True) == before:
        return 0

    tmp = "/tmp/xray-sync.config.json"
    old_umask = os.umask(0o077)
    try:
        json.dump(cfg, open(tmp, "w"), ensure_ascii=False, indent=1)
    finally:
        os.umask(old_umask)

    test = subprocess.run([XRAY, "-test", "-c", tmp], capture_output=True, text=True)
    if "Configuration OK" not in (test.stdout + test.stderr):
        log("ERROR: xray -test не прошёл, конфиг НЕ применён")
        log((test.stdout + test.stderr).strip().splitlines()[-1] if (test.stdout or test.stderr) else "")
        os.remove(tmp)
        return 1

    subprocess.run(["install", "-m", "600", "-o", "root", "-g", "root", tmp, CFG], check=True)
    os.remove(tmp)
    subprocess.run(["systemctl", "restart", "xray"], check=True)

    log("users=%d added=[%s] removed=[%s] new_legs=%d dead_legs=%d"
        % (len(users), ",".join(sorted(added)), ",".join(sorted(removed)),
           len(new_outbounds), len(dead)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
