#!/usr/bin/env bash
# sync-offsite.sh — отвезти зашифрованные копии на другой сервер (rsync по ssh, без --delete: удалённое
# здесь там остаётся). Ключ OFFSITE_KEY на той стороне ограничен rrsync своей папкой — см. install-backup.sh.
set -uo pipefail
. "$(dirname "$(readlink -f "$0")")/common.sh"
load_conf
[ -n "${OFFSITE:-}" ] || { echo "OFFSITE не задан в $CONF — разнос копий выключен"; exit 0; }
KEY="${OFFSITE_KEY:-/root/.ssh/remnawave-backup}"; PORT="${OFFSITE_PORT:-22}"
[ -f "$KEY" ] || fail "нет ключа $KEY для offsite"
command -v rsync >/dev/null || fail "не установлен rsync (apt install rsync)"
SSH="ssh -i $KEY -p $PORT -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=20"
if ! rsync -a --timeout=900 -e "$SSH" --include='panel/' --include='monitoring/' --include='*.tar.age' --include='backup.log' --exclude='*' \
     "$OUT_DIR/" "$OFFSITE" 2> "$OUT_DIR/.sync.err"; then
  fail "offsite $OFFSITE: $(tail -1 "$OUT_DIR/.sync.err" | cut -c1-150)"
fi
log "OK sync → $OFFSITE ($(find "$OUT_DIR" -name '*.tar.age' | wc -l) файлов)"
