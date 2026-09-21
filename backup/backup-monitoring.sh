#!/usr/bin/env bash
# backup-monitoring.sh — бэкап сервера мониторинга: база Uptime Kuma, база Grafana (через sqlite .backup —
# консистентно на работающей системе) и папка стека (/opt/remnawave-monitoring/stack: .env, цели, provisioning).
# История Prometheus НЕ сохраняется (велика и восстановима из жизни). Шифруется age, как и панель.
set -uo pipefail
. "$(dirname "$(readlink -f "$0")")/common.sh"
load_conf
MON_DIR="${MONITORING_DIR:-/opt/remnawave-monitoring}"; KEEP_DAYS="${MON_KEEP_DAYS:-7}"
OUT="$OUT_DIR/monitoring"; mkdir -p "$OUT" && chmod 700 "$OUT"
TS=$(date +%F_%H%M)
[ -d "$MON_DIR/stack" ] || fail "нет $MON_DIR/stack (MONITORING_DIR в $CONF)"
TMP=$(mktemp -d "$OUT_DIR/.tmp.XXXXXX"); trap 'rm -rf "$TMP"' EXIT
got=""
vol() { docker volume inspect -f '{{.Mountpoint}}' "remnawave-monitoring_$1" 2>/dev/null || true; }
KVOL=$(vol kuma-data); GVOL=$(vol grafana-data)
if [ -n "$KVOL" ] && [ -f "$KVOL/kuma.db" ]; then sqlite_backup "$KVOL/kuma.db" "$TMP/kuma.db" || fail "sqlite backup базы Kuma"; got="$got kuma"; fi
if [ -n "$GVOL" ] && [ -f "$GVOL/grafana.db" ]; then sqlite_backup "$GVOL/grafana.db" "$TMP/grafana.db" || fail "sqlite backup базы Grafana"; got="$got grafana"; fi
tar czf "$TMP/stack.tgz" -C "$MON_DIR" stack --warning=no-file-changed 2>/dev/null || [ $? -eq 1 ] || fail "tar $MON_DIR/stack"
printf 'host=%s\ndate=%s\nparts=%s stack\n' "$(hostname)" "$TS" "$got" > "$TMP/MANIFEST"
encrypt_dir "$TMP" "$OUT/monitoring-$TS.tar.age"
rotate "$OUT" 'monitoring-*.tar.age'
log "OK monitoring-$TS.tar.age $(human "$(fsize "$OUT/monitoring-$TS.tar.age")") части:${got:- } stack копий=$(ls "$OUT" | grep -c '^monitoring-.*\.tar\.age$')"
