#!/usr/bin/env bash
# Тянет последний опубликованный десктопный релиз из GitHub в папку, которую раздаёт фронтенд
# (/downloads/). Запускается systemd-таймером meridian-desktop-sync.timer.
set -euo pipefail

REPO="${REPO:-baldmaxim/MeridianAI}"
DEST="${DEST:-/opt/portals/meridian/desktop-dist}"
WIN_NAME="Meridian-Windows-x64-setup.exe"
MAC_NAME="Meridian-macOS-AppleSilicon.dmg"
MIN_SIZE=$((1024 * 1024))

mkdir -p "$DEST"

# не допускаем двух запусков одновременно
exec 9>"$DEST/.lock"
if ! flock -n 9; then
  echo "уже выполняется другой запуск, выхожу"
  exit 0
fi

cleanup() { rm -f "$DEST"/.tmp-*; }
trap cleanup EXIT

echo "запрашиваю последний релиз $REPO"
release_json="$(curl -fsSL --connect-timeout 15 --max-time 60 \
  -H 'Accept: application/vnd.github+json' \
  "https://api.github.com/repos/$REPO/releases/latest")"

# jq на сервере нет - разбираем JSON через python3; вывод: тег, url exe, url dmg (по строке)
parsed="$(printf '%s' "$release_json" | python3 -I -c '
import json, sys
d = json.load(sys.stdin)
urls = {"exe": "", "dmg": ""}
for a in d.get("assets", []):
    n = a.get("name", "")
    if n.endswith("_x64-setup.exe"):
        urls["exe"] = a.get("browser_download_url", "")
    elif n.endswith("_aarch64.dmg"):
        urls["dmg"] = a.get("browser_download_url", "")
print(d.get("tag_name", ""))
print(urls["exe"])
print(urls["dmg"])
')"
tag="$(printf '%s\n' "$parsed" | sed -n 1p)"
url_win="$(printf '%s\n' "$parsed" | sed -n 2p)"
url_mac="$(printf '%s\n' "$parsed" | sed -n 3p)"

case "$tag" in
  desktop-v*) ;;
  *)
    echo "последний релиз '$tag' не десктопный - ничего не делаю"
    exit 0
    ;;
esac

if [ -f "$DEST/VERSION" ] && [ "$(cat "$DEST/VERSION")" = "$tag" ]; then
  echo "актуально: $tag"
  exit 0
fi

if [ -z "$url_win" ] || [ -z "$url_mac" ]; then
  echo "в релизе $tag нет нужных установщиков (exe: '${url_win:+есть}', dmg: '${url_mac:+есть}')" >&2
  exit 1
fi

download() { # url, имя файла
  local url="$1" tmp="$DEST/.tmp-$2"
  echo "скачиваю $2"
  curl -fsSL --retry 3 --connect-timeout 15 --max-time 1800 -o "$tmp" "$url"
  local size
  size="$(stat -c %s "$tmp")"
  if [ "$size" -le "$MIN_SIZE" ]; then
    echo "файл $2 слишком мал ($size байт)" >&2
    exit 1
  fi
}

download "$url_win" "$WIN_NAME"
download "$url_mac" "$MAC_NAME"

for name in "$WIN_NAME" "$MAC_NAME"; do
  chmod 644 "$DEST/.tmp-$name"
  mv -f "$DEST/.tmp-$name" "$DEST/$name"
done

printf '%s\n' "$tag" > "$DEST/.tmp-VERSION"
chmod 644 "$DEST/.tmp-VERSION"
mv -f "$DEST/.tmp-VERSION" "$DEST/VERSION"
echo "обновлено до $tag"
