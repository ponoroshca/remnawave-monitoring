#!/usr/bin/env bash
# uninstall.sh — снять стек мониторинга с этого сервера.
#   sudo /opt/remnawave-monitoring/scripts/uninstall.sh            спросит про данные и папку (нужен терминал)
#   … --keep-data     остановить контейнеры, тома с историей/Grafana/Kuma и папку оставить (без вопросов)
#   … --data          удалить и тома с данными
#   … --all           удалить тома и /opt/remnawave-monitoring вместе с .env
set -uo pipefail
OPT=/opt/remnawave-monitoring
[ "$(id -u)" = 0 ] || { echo "нужен root (sudo)"; exit 1; }
DATA=""; DIR=""
case "${1:-}" in
  --keep-data) DATA=n; DIR=n ;;
  --data) DATA=y; DIR=n ;;
  --all) DATA=y; DIR=y ;;
  "") if [ -r /dev/tty ]; then
        read -r -p "Удалить и данные (история метрик, настройки Grafana и Kuma)? [y/N]: " DATA </dev/tty 2>/dev/null || DATA=n
        read -r -p "Удалить $OPT вместе с .env (токены, пароль Grafana)? [y/N]: " DIR </dev/tty 2>/dev/null || DIR=n
      else DATA=n; DIR=n; echo "нет терминала — оставляю данные и папку (флаги: --keep-data, --data, --all)"; fi ;;
  *) sed -n '2,6p' "$0"; exit 2 ;;
esac
if [ -f "$OPT/stack/docker-compose.yml" ] && command -v docker >/dev/null; then
  # переменные-заглушки: compose требует их даже для down, а .env может уже не быть
  export GRAFANA_ADMIN_PASSWORD="${GRAFANA_ADMIN_PASSWORD:-x}" PANEL_URL="${PANEL_URL:-http://x}" PANEL_TOKEN="${PANEL_TOKEN:-x}"
  case "$DATA" in
    [Yy]*) (cd "$OPT/stack" && docker compose down -v --remove-orphans 2>&1 | tail -2); echo "контейнеры и тома удалены" ;;
    *)     (cd "$OPT/stack" && docker compose down --remove-orphans 2>&1 | tail -2); echo "контейнеры остановлены, тома с данными оставлены (docker volume ls | grep remnawave-monitoring)" ;;
  esac
fi
[ -L /usr/local/bin/remnawave-monitoring ] && rm -f /usr/local/bin/remnawave-monitoring
case "$DIR" in [Yy]*) rm -rf "$OPT"; echo "удалено $OPT" ;; *) echo "оставлено $OPT" ;; esac
echo "Агенты на нодах снимаются на самих нодах: install-node-exporter.sh --uninstall. Бэкапы — backup/install-backup.sh --uninstall."
