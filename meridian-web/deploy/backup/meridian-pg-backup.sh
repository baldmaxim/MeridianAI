#!/usr/bin/env bash
# Ежедневный логический дамп Yandex Managed PostgreSQL (pg_dump -Fc) на хосте Selectel.
# Дополняет управляемые бэкапы YC. DATABASE_URL читается из meridian.env и НЕ печатается;
# пароль передаётся в контейнер через PGPASSWORD из окружения (не в аргументах -> не виден в ps).
#
# Переопределяемые переменные:
#   ENV_FILE    — путь к meridian.env (по умолчанию /opt/portals/meridian/meridian-web/deploy/portal/meridian.env)
#   BACKUP_DIR  — каталог дампов (/opt/backups/meridian)
#   KEEP        — сколько последних дампов хранить (7)
#   PG_IMAGE    — образ с клиентом PG (postgres:17-alpine; мажор = версии сервера YC)
set -euo pipefail
umask 077

ENV_FILE="${ENV_FILE:-/opt/portals/meridian/meridian-web/deploy/portal/meridian.env}"
BACKUP_DIR="${BACKUP_DIR:-/opt/backups/meridian}"
KEEP="${KEEP:-7}"
PG_IMAGE="${PG_IMAGE:-postgres:17-alpine}"

[ -r "$ENV_FILE" ] || { echo "ОШИБКА: нет доступа к env-файлу: $ENV_FILE" >&2; exit 1; }
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

# SQLAlchemy URL -> части libpq. Значения отдаются через NUL-разделитель, на экран не попадают.
mapfile -d '' -t PARTS < <(python3 - "$ENV_FILE" <<'PY'
import sys
from urllib.parse import urlsplit, unquote

url = ""
with open(sys.argv[1], encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if line.startswith("DATABASE_URL="):
            url = line.split("=", 1)[1].strip().strip("'\"")
if not url:
    sys.stderr.write("ОШИБКА: DATABASE_URL не найден в env-файле\n")
    sys.exit(2)
# postgresql+asyncpg:// -> postgresql://
scheme, _, rest = url.partition("://")
u = urlsplit("postgresql://" + rest)
parts = [u.hostname or "", str(u.port or 5432), unquote(u.username or ""),
         unquote(u.password or ""), unquote(u.path.lstrip("/"))]
if not all(parts):
    sys.stderr.write("ОШИБКА: в DATABASE_URL не хватает host/user/password/dbname\n")
    sys.exit(2)
sys.stdout.write("\0".join(parts) + "\0")
PY
)
[ "${#PARTS[@]}" -eq 5 ] || { echo "ОШИБКА: не удалось разобрать DATABASE_URL" >&2; exit 1; }
PGHOST="${PARTS[0]}"; PGPORT="${PARTS[1]}"; PGUSER="${PARTS[2]}"; PGDATABASE="${PARTS[4]}"
export PGPASSWORD="${PARTS[3]}"
unset PARTS

TS="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="$BACKUP_DIR/meridian-$TS.dump"
TMP="$OUT.part"
trap 'rm -f "$TMP"' EXIT

# Внешний хост (YC) -> достаточно дефолтной bridge-сети. sslmode=require — YC требует TLS.
docker run --rm \
  -e PGPASSWORD \
  -e PGSSLMODE=require \
  "$PG_IMAGE" \
  pg_dump -Fc --no-owner --no-privileges \
    -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" \
  > "$TMP"
unset PGPASSWORD

# Проверка: дамп читается и в оглавлении есть объекты
ITEMS="$(docker run --rm -i "$PG_IMAGE" pg_restore --list < "$TMP" | grep -vc '^;' || true)"
if [ "${ITEMS:-0}" -le 0 ]; then
  echo "ОШИБКА: дамп пуст или повреждён (pg_restore --list: 0 объектов), удаляю" >&2
  rm -f "$TMP"
  exit 1
fi

chmod 600 "$TMP"
mv "$TMP" "$OUT"
trap - EXIT

# Ротация: оставляем KEEP последних
ls -1t "$BACKUP_DIR"/meridian-*.dump 2>/dev/null | tail -n +"$((KEEP + 1))" | xargs -r rm -f --

echo "OK: $(basename "$OUT") $(du -h "$OUT" | cut -f1), объектов в оглавлении: $ITEMS"
