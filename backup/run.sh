#!/usr/bin/env bash
# run.sh — то, что запускает таймер: бэкап панели и/или мониторинга (по конфигу), затем разнос копий.
# Части независимы: провал одной не отменяет остальные; код выхода ≠ 0, если что-то упало.
set -uo pipefail
HERE="$(dirname "$(readlink -f "$0")")"
. "$HERE/common.sh"; load_conf
rc=0
[ "${BACKUP_PANEL:-0}" = 1 ] && { "$HERE/backup-panel.sh" || rc=1; }
[ "${BACKUP_MONITORING:-0}" = 1 ] && { "$HERE/backup-monitoring.sh" || rc=1; }
[ -n "${OFFSITE:-}" ] && { "$HERE/sync-offsite.sh" || rc=1; }
exit $rc
