#!/usr/bin/env bash
# restore-panel.sh — восстановление панели из бэкапа НА НОВОМ СЕРВЕРЕ (docker уже стоит).
#   restore-panel.sh panel-2026-09-22_0330.tar.age /path/age-backup.key
# Что делает: расшифровывает → кладёт папку панели в /opt/remnawave → поднимает только базу → pg_restore →
# поднимает панель целиком. ОТКАЗЫВАЕТСЯ работать, если /opt/remnawave уже есть и не пуст (живая панель!).
# Дальше по docs/RECOVERY.md: DNS панели и подписки на новый IP, ноды переподключатся сами.
set -uo pipefail
ARCH="${1:-}"; IDENT="${2:-}"; PANEL_DIR="${PANEL_DIR:-/opt/remnawave}"
[ -f "$ARCH" ] && [ -f "$IDENT" ] || { sed -n '2,7p' "$0"; exit 2; }
[ "$(id -u)" = 0 ] || { echo "нужен root"; exit 1; }
for t in docker age tar; do command -v $t >/dev/null || { echo "нужен $t (apt install age)"; exit 1; }; done
if [ -d "$PANEL_DIR" ] && [ -n "$(ls -A "$PANEL_DIR" 2>/dev/null)" ]; then
  echo "СТОП: $PANEL_DIR уже существует и не пуст. Этот скрипт — для НОВОГО сервера."
  echo "Если это точно не живая панель — переименуйте папку (mv $PANEL_DIR ${PANEL_DIR}.old) и повторите."; exit 1
fi
if docker inspect remnawave-db >/dev/null 2>&1; then echo "СТОП: контейнер remnawave-db уже есть на этом сервере."; exit 1; fi
echo "Восстановление из $ARCH в $PANEL_DIR. Напечатайте: восстановить"
read -r ans </dev/tty; [ "$ans" = "восстановить" ] || { echo "отменено"; exit 1; }
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
age -d -i "$IDENT" "$ARCH" | tar xf - -C "$TMP" || { echo "❌ не расшифровалось"; exit 1; }
[ -f "$TMP/panel.pgdump" ] && [ -f "$TMP/panel-dir.tgz" ] || { echo "❌ в архиве нет panel.pgdump/panel-dir.tgz"; exit 1; }
echo "MANIFEST: $(tr '\n' ' ' < "$TMP/MANIFEST" 2>/dev/null)"
mkdir -p "$(dirname "$PANEL_DIR")"; tar xzf "$TMP/panel-dir.tgz" -C "$(dirname "$PANEL_DIR")"
[ -f "$PANEL_DIR/docker-compose.yml" ] || { echo "❌ в папке панели нет docker-compose.yml"; exit 1; }
cd "$PANEL_DIR"
echo "поднимаю базу…"; docker compose up -d remnawave-db || exit 1
# при первом старте образ postgres поднимает ВРЕМЕННЫЙ сервер для инициализации и потом перезапускается —
# pg_isready ловит и его; ждём, пока select 1 проходит дважды с паузой
pg_ok() { docker exec remnawave-db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "select 1"' 2>/dev/null | grep -q 1; }
for i in $(seq 1 120); do pg_ok && sleep 4 && pg_ok && break; sleep 1; done
pg_ok || { echo "❌ база не поднялась"; docker logs remnawave-db 2>&1 | tail -5; exit 1; }
docker cp "$TMP/panel.pgdump" remnawave-db:/tmp/panel.pgdump
echo "pg_restore…"
docker exec remnawave-db sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner --no-privileges /tmp/panel.pgdump' 2> "$TMP/restore.err" || true
grep -i "error" "$TMP/restore.err" | grep -viE "does not exist|already exists" | head -5
U=$(docker exec remnawave-db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "select count(*) from users"' 2>/dev/null | tr -d ' ')
echo "пользователей в восстановленной базе: ${U:-?}"
docker exec remnawave-db rm -f /tmp/panel.pgdump
echo "поднимаю панель…"; docker compose up -d
echo "✅ готово. Дальше: DNS панели/подписки → этот сервер; проверьте вход в панель и что ноды подключились (docs/RECOVERY.md)."
