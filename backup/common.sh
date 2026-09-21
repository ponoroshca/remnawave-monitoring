#!/usr/bin/env bash
# common.sh — общее для скриптов бэкапа: конфиг, лог, Telegram. Подключается через source.
CONF="${REMNAWAVE_BACKUP_CONF:-/etc/remnawave-backup/backup.env}"
load_conf() {
  [ -f "$CONF" ] || { echo "нет конфига $CONF — сначала backup/install-backup.sh"; exit 2; }
  # shellcheck disable=SC1090
  set -a; . "$CONF"; set +a
  OUT_DIR="${OUT_DIR:-/var/backups/remnawave}"; KEEP_DAYS="${KEEP_DAYS:-14}"; KEEP_MIN="${KEEP_MIN:-3}"
  LOG="${LOG:-$OUT_DIR/backup.log}"
  mkdir -p "$OUT_DIR" && chmod 700 "$OUT_DIR"
}
log() { echo "$(date +'%F %T') $*" | tee -a "$LOG" >&2; }
tg() {  # tg "текст" — молча, если Telegram не настроен; через прокси, если задан; 3 попытки
  [ -n "${TELEGRAM_BOT_TOKEN:-}" ] && [ -n "${TELEGRAM_CHAT_ID:-}" ] || return 0
  local i; for i in 1 2 3; do
    curl -s -m 20 ${TELEGRAM_PROXY:+--proxy "$TELEGRAM_PROXY"} "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
      --data-urlencode "chat_id=${TELEGRAM_CHAT_ID}" --data-urlencode "text=$1" --data-urlencode "disable_web_page_preview=true" >/dev/null 2>&1 && return 0
    [ -n "${TELEGRAM_PROXY:-}" ] && curl -s -m 20 "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
      --data-urlencode "chat_id=${TELEGRAM_CHAT_ID}" --data-urlencode "text=$1" >/dev/null 2>&1 && return 0
    sleep $((i * 3))
  done
  return 1
}
fail() { log "FAIL $1"; tg "💾❌ бэкап ($(hostname)): $1"; exit 1; }
fsize() { stat -c %s "$1" 2>/dev/null || stat -f %z "$1"; }
human() { numfmt --to=iec --suffix=B "$1" 2>/dev/null || echo "$1 B"; }
rotate() {  # rotate <папка> <маска> — удалить старше KEEP_DAYS, но оставить не меньше KEEP_MIN самых новых
  local dir=$1 mask=$2 n
  n=$(find "$dir" -maxdepth 1 -name "$mask" -type f | wc -l)
  [ "$n" -le "$KEEP_MIN" ] && return 0
  find "$dir" -maxdepth 1 -name "$mask" -type f -mtime +"$KEEP_DAYS" -printf '%T@ %p\n' | sort -n | head -n "$((n - KEEP_MIN))" | cut -d' ' -f2- | xargs -r rm -f
}
sqlite_backup() {  # sqlite_backup <db> <копия> — консистентная копия работающей базы (python sqlite3 backup API)
  python3 - "$1" "$2" <<'PY'
import sqlite3, sys
src = sqlite3.connect("file:%s?mode=ro" % sys.argv[1], uri=True); dst = sqlite3.connect(sys.argv[2]); src.backup(dst); dst.close(); src.close()
PY
}
encrypt_dir() {  # encrypt_dir <папка с файлами> <файл .tar.age> — tar | age публичным ключом
  [ -n "${RECIPIENT:-}" ] || fail "в конфиге нет RECIPIENT (публичный ключ age)"
  command -v age >/dev/null || fail "не установлен age (apt install age)"
  tar cf - -C "$1" . | age -r "$RECIPIENT" -o "$2" || fail "age не зашифровал $2"
  head -c 21 "$2" | grep -q "age-encryption.org/v1" || fail "архив $2 не похож на age"
}
