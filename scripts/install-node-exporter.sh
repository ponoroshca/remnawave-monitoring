#!/usr/bin/env bash
# install-node-exporter.sh — агент метрик (prom/node-exporter) на ноде. Запускать НА НОДЕ, root.
#   curl -fsSL https://raw.githubusercontent.com/ponoroshca/remnawave-monitoring/main/scripts/install-node-exporter.sh | sudo bash -s -- --allow-from 203.0.113.5
#   --allow-from IP   адрес сервера мониторинга — только ему открывается порт (обязательно)
#   --port N          порт агента (9100)
#   --no-firewall     ставить, даже если ufw выключен (порт будет открыт всем — метрики системы без секретов, но всё же)
#   --uninstall       снять агент и правило ufw
# Что делает: docker run prom/node-exporter в host-сети (нужно для сетевых счётчиков и conntrack) + ufw allow from IP.
# Ничего другого на ноде не трогает; remnanode/xray не перезапускает.
set -euo pipefail
ALLOW=""; PORT=9100; NOFW=0; UNINSTALL=0
while [ $# -gt 0 ]; do
  case "$1" in
    --allow-from) ALLOW="$2"; shift 2 ;;
    --port) PORT="$2"; shift 2 ;;
    --no-firewall) NOFW=1; shift ;;
    --uninstall) UNINSTALL=1; shift ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
    *) echo "неизвестный флаг: $1"; exit 2 ;;
  esac
done
[ "$(id -u)" = 0 ] || { echo "нужен root (sudo)"; exit 1; }
command -v docker >/dev/null || { echo "на ноде нет docker — агент работает в контейнере (remnanode тоже в docker; установите его сначала)"; exit 1; }

if [ "$UNINSTALL" = 1 ]; then
  docker rm -f node-exporter >/dev/null 2>&1 && echo "контейнер node-exporter удалён" || echo "контейнера node-exporter не было"
  if command -v ufw >/dev/null; then
    while read -r n; do [ -n "$n" ] && ufw --force delete "$n" >/dev/null; done < <(ufw status numbered 2>/dev/null | grep -F "node-exporter" | grep -oE '^\[ *[0-9]+\]' | tr -d '[] ' | sort -rn)
    echo "правила ufw с пометкой node-exporter удалены"
  fi
  exit 0
fi

[ -n "$ALLOW" ] || { echo "укажите --allow-from <IP сервера мониторинга> (порт $PORT откроется только ему)"; exit 2; }
[[ "$ALLOW" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "--allow-from: нужен IPv4-адрес, получено «$ALLOW»"; exit 2; }

# чужой контейнер с таким именем — не трогаем
if docker inspect node-exporter >/dev/null 2>&1; then
  img=$(docker inspect -f '{{.Config.Image}}' node-exporter)
  case "$img" in *node-exporter*) ;; *) echo "СТОП: контейнер node-exporter уже есть и это не наш образ ($img). Ничего не изменено."; exit 1 ;; esac
fi

# файрвол — ДО запуска, чтобы порт ни секунды не был открыт всем
if command -v ufw >/dev/null && ufw status 2>/dev/null | grep -q "Status: active"; then
  ufw allow from "$ALLOW" to any port "$PORT" proto tcp comment node-exporter >/dev/null
  echo "ufw: порт $PORT открыт только для $ALLOW"
elif [ "$NOFW" = 1 ]; then
  echo "ВНИМАНИЕ: ufw не активен, порт $PORT будет доступен всем (--no-firewall)"
else
  echo "СТОП: ufw не активен — порт $PORT оказался бы открыт всему интернету."
  echo "  Включите файрвол (например, install-node.sh из remnawave-node-kit делает это безопасно: ssh + порты нод),"
  echo "  или запустите с --no-firewall, если сознательно готовы отдавать метрики системы всем."
  exit 1
fi

docker rm -f node-exporter >/dev/null 2>&1 || true
docker run -d --name node-exporter --restart unless-stopped --net host --pid host \
  -v /:/host:ro prom/node-exporter:latest \
  --path.rootfs=/host --web.listen-address=":$PORT" \
  --collector.filesystem.mount-points-exclude='^/(host/)?(sys|proc|dev|run|var/lib/docker/.+|var/lib/containers/.+)($|/)' >/dev/null
sleep 2
if ! docker ps --format '{{.Names}}' | grep -qx node-exporter; then
  echo "контейнер не поднялся:"; docker logs node-exporter 2>&1 | tail -5; exit 1
fi
# ответ агента без curl: bash /dev/tcp
if exec 3<>"/dev/tcp/127.0.0.1/$PORT" 2>/dev/null; then
  printf 'GET /metrics HTTP/1.0\r\nHost: localhost\r\n\r\n' >&3
  if head -c 4000 <&3 | grep -q "node_cpu_seconds_total\|node_exporter_build_info"; then echo "агент отвечает на :$PORT"; else echo "агент поднят, но /metrics пуст — docker logs node-exporter"; fi
  exec 3<&- 3>&-
fi
echo "готово. На сервере мониторинга: remnawave-monitoring targets  (нода появится в job=node)"
