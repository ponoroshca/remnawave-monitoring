#!/usr/bin/env bash
# backup-panel.sh — ночной бэкап панели Remnawave: Postgres (pg_dump -Fc) + папка панели (/opt/remnawave:
# docker-compose.yml, .env, ключи). Шифруется ПУБЛИЧНЫМ ключом age (RECIPIENT) — расшифровать может только
# владелец секретного ключа, которого на сервере нет. Ошибка любого шага → Telegram.
#   backup-panel.sh            сделать бэкап
#   backup-panel.sh --dry-run  показать, что будет сделано
# Восстановление: docs/RECOVERY.md (backup/restore-panel.sh, проверка — backup/verify-restore.sh).
set -uo pipefail
. "$(dirname "$(readlink -f "$0")")/common.sh"
load_conf
DB_CONTAINER="${DB_CONTAINER:-remnawave-db}"; PANEL_DIR="${PANEL_DIR:-/opt/remnawave}"; MIN_DUMP_BYTES="${MIN_DUMP_BYTES:-2000}"
OUT="$OUT_DIR/panel"; mkdir -p "$OUT" && chmod 700 "$OUT"
TS=$(date +%F_%H%M)
if [ "${1:-}" = "--dry-run" ]; then
  echo "контейнер базы: $DB_CONTAINER ($(docker inspect -f '{{.State.Status}}' "$DB_CONTAINER" 2>/dev/null || echo 'НЕ НАЙДЕН'))"
  echo "папка панели:   $PANEL_DIR ($( [ -d "$PANEL_DIR" ] && du -sh "$PANEL_DIR" | cut -f1 || echo 'НЕТ'))"
  echo "куда:           $OUT/panel-$TS.tar.age, хранить $KEEP_DAYS дн. (не меньше $KEEP_MIN копий)"
  echo "ключ:           ${RECIPIENT:-НЕ ЗАДАН}"
  echo "telegram:       $([ -n "${TELEGRAM_BOT_TOKEN:-}" ] && echo "chat $TELEGRAM_CHAT_ID" || echo нет)"
  echo "сейчас копий:   $(ls "$OUT" 2>/dev/null | grep -c '^panel-.*\.tar\.age$')"
  exit 0
fi
docker inspect "$DB_CONTAINER" >/dev/null 2>&1 || fail "нет контейнера базы $DB_CONTAINER (DB_CONTAINER в $CONF)"
[ -d "$PANEL_DIR" ] || fail "нет папки панели $PANEL_DIR (PANEL_DIR в $CONF)"
TMP=$(mktemp -d "$OUT_DIR/.tmp.XXXXXX"); trap 'rm -rf "$TMP"' EXIT
docker exec "$DB_CONTAINER" sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$TMP/panel.pgdump" 2> "$TMP/pg.err" \
  || fail "pg_dump не отработал: $(tail -1 "$TMP/pg.err" | cut -c1-150)"
SZ=$(fsize "$TMP/panel.pgdump")
[ "$SZ" -ge "$MIN_DUMP_BYTES" ] || fail "дамп подозрительно мал: $SZ байт (< $MIN_DUMP_BYTES)"
PREV=$(cat "$OUT/.last-dump-size" 2>/dev/null || echo 0)
[ "$PREV" -gt 0 ] && [ "$SZ" -lt $((PREV / 2)) ] && fail "дамп вдвое меньше вчерашнего ($SZ < $PREV / 2) — база пустая или неполная? Бэкап НЕ записан"
tar czf "$TMP/panel-dir.tgz" -C "$(dirname "$PANEL_DIR")" "$(basename "$PANEL_DIR")" --warning=no-file-changed 2>/dev/null || [ $? -eq 1 ] || fail "tar $PANEL_DIR не отработал"
USERS=$(docker exec "$DB_CONTAINER" sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "select count(*) from users"' 2>/dev/null | tr -d ' ')
NODES=$(docker exec "$DB_CONTAINER" sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "select count(*) from nodes"' 2>/dev/null | tr -d ' ')
printf 'host=%s\ndate=%s\ndump_bytes=%s\nusers=%s\nnodes=%s\npanel_dir=%s\n' "$(hostname)" "$TS" "$SZ" "${USERS:-?}" "${NODES:-?}" "$PANEL_DIR" > "$TMP/MANIFEST"
encrypt_dir "$TMP" "$OUT/panel-$TS.tar.age"
echo "$SZ" > "$OUT/.last-dump-size"
rotate "$OUT" 'panel-*.tar.age'
log "OK panel-$TS.tar.age $(human "$(fsize "$OUT/panel-$TS.tar.age")") users=${USERS:-?} nodes=${NODES:-?} копий=$(ls "$OUT" | grep -c '^panel-.*\.tar\.age$')"
