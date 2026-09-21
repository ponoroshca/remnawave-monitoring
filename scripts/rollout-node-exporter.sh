#!/usr/bin/env bash
# rollout-node-exporter.sh — поставить агент сразу на все ноды по ssh (для тех, у кого есть ключ на ноды).
#   remnawave-monitoring targets --ssh-list > hosts.txt      # «имя адрес» по нодам панели
#   ./rollout-node-exporter.sh hosts.txt [-k ~/.ssh/id_ed25519] [-p 22] [-j 4] [--allow-from IP]
# Строка файла: имя адрес [порт ssh]. Строки с # пропускаются. --allow-from по умолчанию — адрес этого сервера.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FILE=""; KEY=""; SSHPORT=22; JOBS=4; ALLOW=""; EXTRA=""
while [ $# -gt 0 ]; do
  case "$1" in
    -k) KEY="$2"; shift 2 ;; -p) SSHPORT="$2"; shift 2 ;; -j) JOBS="$2"; shift 2 ;;
    --allow-from) ALLOW="$2"; shift 2 ;; --no-firewall) EXTRA="--no-firewall"; shift ;;
    -h|--help) sed -n '2,6p' "$0"; exit 0 ;;
    *) FILE="$1"; shift ;;
  esac
done
[ -n "$FILE" ] && [ -f "$FILE" ] || { echo "нужен файл со списком нод (имя адрес [порт])"; exit 2; }
[ -n "$ALLOW" ] || ALLOW=$(python3 -c 'import socket; s=socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.connect(("1.1.1.1",53)); print(s.getsockname()[0])' 2>/dev/null || hostname -I | awk '{print $1}')
SSH=(ssh -o BatchMode=yes -o ConnectTimeout=15 -o StrictHostKeyChecking=accept-new); [ -n "$KEY" ] && SSH+=(-i "$KEY")
LOG=$(mktemp -d)
one() {
  local name=$1 ip=$2 port=${3:-$SSHPORT}
  "${SSH[@]}" -p "$port" "root@$ip" "bash -s -- --allow-from $ALLOW $EXTRA" < "$HERE/install-node-exporter.sh" > "$LOG/$name" 2>&1
  echo $? > "$LOG/$name.rc"
}
n=0
while read -r name ip port _; do
  [ -z "$name" ] || [[ "$name" == \#* ]] && continue
  one "$name" "$ip" "${port:-}" &
  n=$((n+1)); while [ "$(jobs -r | wc -l)" -ge "$JOBS" ]; do sleep 1; done
done < "$FILE"
wait
echo "═══ раскатка агента: $n нод, allow-from $ALLOW ═══"
fail=0
while read -r name ip _; do
  [ -z "$name" ] || [[ "$name" == \#* ]] && continue
  rc=$(cat "$LOG/$name.rc" 2>/dev/null || echo 255)
  if [ "$rc" = 0 ]; then printf "  ✅ %-18s %s\n" "$name" "$(grep -m1 'агент отвечает\|готово' "$LOG/$name" || tail -1 "$LOG/$name")"
  else fail=$((fail+1)); printf "  ❌ %-18s %s\n" "$name" "$(grep -v '^$' "$LOG/$name" | tail -1 | cut -c1-120)"; fi
done < "$FILE"
rm -rf "$LOG"
echo "дальше на сервере мониторинга: remnawave-monitoring targets && remnawave-monitoring doctor"
[ "$fail" = 0 ]
