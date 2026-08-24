#!/usr/bin/env python3
r"""Синхронизация юзеров Remnawave -> standalone xray на KG-машине (C:\xray).

KG — гибрид: боевой :443 держит host-xray на Windows, а не remnanode, поэтому
панель клиентов туда НЕ пушит. Без синхронизации новый юзер получает таймаут
на плече out-kg-<user> с YC-релея.

Запуск: задача планировщика xray-sync-kg (раз в 5 минут).
Конфиг трогается только при реальных изменениях; значения uuid не печатаются.
"""
import json
import os
import shutil
import ssl
import subprocess
import sys
import time
import urllib.request

CFG = r"C:\xray\config.json"
XRAY = r"C:\xray\xray.exe"
TOKEN_FILE = r"C:\xray\panel-token.txt"
LOG = r"C:\xray\sync.log"
API = "https://dash.meridianai.ru/api/users?size=500"
TASK = "xray-kg"

MAX_REMOVE_SHARE = 0.34   # защита от битого ответа API


def log(msg):
    line = "%s  %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    print(line)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def fetch_users():
    token = open(TOKEN_FILE, encoding="utf-8").read().strip()
    req = urllib.request.Request(API, headers={"Authorization": "Bearer " + token})
    with urllib.request.urlopen(req, timeout=30, context=ssl.create_default_context()) as r:
        data = json.load(r)
    users = {}
    for u in data["response"]["users"]:
        if u.get("status") != "ACTIVE" or not (u.get("activeInternalSquads") or []):
            continue
        if u.get("vlessUuid"):
            users[u["username"]] = u["vlessUuid"]
    if not users:
        raise SystemExit("ERROR: панель вернула 0 активных юзеров — конфиг не трогаю")
    return users


def main():
    users = fetch_users()
    d = json.load(open(CFG, encoding="utf-8"))
    before = json.dumps(d, sort_keys=True)
    added, removed = [], []

    for inb in d["inbounds"]:
        clients = inb.get("settings", {}).get("clients")
        if not clients:
            continue
        # email у Remnawave: <username>-<первые 4 символа vless_uuid>
        stale = [c for c in clients if c["email"].rsplit("-", 1)[0] not in users]
        if stale and len(stale) > max(1, int(len(clients) * MAX_REMOVE_SHARE)):
            log("WARN: %s — пропускаю удаление %d из %d клиентов (похоже на сбой)"
                % (inb.get("tag"), len(stale), len(clients)))
            stale = []
        for c in stale:
            clients.remove(c)
            removed.append(c["email"].rsplit("-", 1)[0])

        tmpl = clients[0] if clients else {"flow": "xtls-rprx-vision"}
        have = {c["email"].rsplit("-", 1)[0] for c in clients}
        for name, uid in sorted(users.items()):
            if name in have:
                continue
            c = dict(tmpl)
            c["id"] = uid
            c["email"] = "%s-%s" % (name, uid[:4])
            clients.append(c)
            added.append(name)

    if json.dumps(d, sort_keys=True) == before:
        return 0

    bak = CFG + ".bak-" + time.strftime("%Y%m%d-%H%M%S")
    shutil.copy2(CFG, bak)
    tmp = CFG.replace(".json", ".new.json")   # расширение .json обязательно: xray определяет формат по нему
    json.dump(d, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    test = subprocess.run([XRAY, "-test", "-c", tmp], capture_output=True, text=True)
    if "Configuration OK" not in (test.stdout + test.stderr):
        log("ERROR: xray -test не прошёл, конфиг НЕ применён")
        tail = (test.stdout + test.stderr).strip().splitlines()
        if tail:
            log("  " + tail[-1])
        os.remove(tmp)
        return 1

    os.replace(tmp, CFG)
    subprocess.run(["schtasks", "/End", "/TN", TASK], capture_output=True)
    time.sleep(2)
    subprocess.run(["schtasks", "/Run", "/TN", TASK], capture_output=True)
    log("users=%d added=[%s] removed=[%s] backup=%s"
        % (len(users), ",".join(added), ",".join(removed), os.path.basename(bak)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
