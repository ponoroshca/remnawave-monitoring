#!/usr/bin/env bash
# verify-restore.sh — ПРОВЕРКА бэкапа панели на любом компьютере с docker и age: расшифровать, поднять
# временный Postgres, восстановить дамп, посчитать таблицы/пользователей/ноды, всё убрать.
# Ничего живого не трогает. Делайте раз в месяц — бэкап, который ни разу не восстанавливали, не бэкап.
#   verify-restore.sh panel-2026-09-22_0330.tar.age ~/keys/age-backup.key [--pg-image postgres:17]
set -uo pipefail
ARCH="${1:-}"; IDENT="${2:-}"; PG="postgres:17"
[ "${3:-}" = "--pg-image" ] && PG="${4:-$PG}"
[ -f "$ARCH" ] && [ -f "$IDENT" ] || { sed -n '2,6p' "$0"; exit 2; }
for t in docker age tar; do command -v $t >/dev/null || { echo "нужен $t"; exit 1; }; done
TMP=$(mktemp -d); C="rw-verify-$$"
cleanup() { docker rm -f "$C" >/dev/null 2>&1; rm -rf "$TMP"; }
trap cleanup EXIT
echo "1/4 расшифровываю…"; age -d -i "$IDENT" "$ARCH" | tar xf - -C "$TMP" || { echo "❌ не расшифровалось: не тот ключ или битый файл"; exit 1; }
[ -f "$TMP/panel.pgdump" ] || { echo "❌ в архиве нет panel.pgdump (это не бэкап панели?)"; ls "$TMP"; exit 1; }
echo "   MANIFEST: $(tr '\n' ' ' < "$TMP/MANIFEST" 2>/dev/null)"
echo "2/4 временный Postgres ($PG)…"
docker run -d --name "$C" -e POSTGRES_PASSWORD=verify -e POSTGRES_DB=verify "$PG" >/dev/null || exit 1
# образ postgres при инициализации поднимает временный сервер и перезапускается — ждём, пока select 1 проходит дважды
pg_ok() { docker exec "$C" psql -U postgres -d verify -tAc "select 1" 2>/dev/null | grep -q 1; }
for i in $(seq 1 90); do pg_ok && sleep 3 && pg_ok && break; sleep 1; done
pg_ok || { echo "❌ Postgres не поднялся"; docker logs "$C" | tail -5; exit 1; }
echo "3/4 pg_restore…"
docker cp "$TMP/panel.pgdump" "$C:/tmp/panel.pgdump"
if ! docker exec "$C" pg_restore -U postgres -d verify --no-owner --no-privileges /tmp/panel.pgdump 2> "$TMP/restore.err"; then
  # pg_restore часто возвращает 1 из-за предупреждений (роли/расширения) — смотрим по факту
  grep -viE "warning|already exists|must be owner|role .* does not exist" "$TMP/restore.err" | grep -i error | head -5
fi
echo "4/4 проверяю…"
Q() { docker exec "$C" psql -U postgres -d verify -tAc "$1" 2>/dev/null | tr -d ' '; }
TABLES=$(Q "select count(*) from information_schema.tables where table_schema='public'")
USERS=$(Q "select count(*) from users"); NODES=$(Q "select count(*) from nodes"); HOSTS=$(Q "select count(*) from hosts")
echo "   таблиц: ${TABLES:-0}  пользователей: ${USERS:-?}  нод: ${NODES:-?}  хостов: ${HOSTS:-?}"
if [ "${TABLES:-0}" -ge 1 ] && [ -n "$USERS" ]; then echo "✅ бэкап восстанавливается: $ARCH (сравните число пользователей с панелью)"; else echo "❌ восстановление неполное — см. вывод pg_restore:"; tail -20 "$TMP/restore.err"; trap - EXIT; docker rm -f "$C" >/dev/null; rm -rf "$TMP"; exit 1; fi
