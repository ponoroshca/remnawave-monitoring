#!/usr/bin/env bash
# snapshot.sh — на offsite-сервере: ежедневный снимок папки, куда приезжают копии (cp -al: место занимают
# только новые файлы). Если основной сервер когда-нибудь зальёт мусор или пустоту — вчерашние снимки целы.
#   snapshot.sh /root/remnawave-offsite [сколько хранить, по умолчанию 14]
set -uo pipefail
O="${1:-/root/remnawave-offsite}"; KEEP="${2:-14}"; D=$(date +%F)
[ -d "$O/current" ] || { echo "нет $O/current — сюда должен приезжать rsync (OFFSITE=user@host:$O/current)"; exit 0; }
mkdir -p "$O/snapshots"; rm -rf "$O/snapshots/$D"; cp -al "$O/current" "$O/snapshots/$D"
ls -1d "$O"/snapshots/20* 2>/dev/null | sort | head -n -"$KEEP" | xargs -r rm -rf
echo "$(date +'%F %T') snapshot $D: $(find "$O/snapshots/$D" -type f | wc -l) файлов, всего $(du -sh "$O" | cut -f1)" >> "$O/snapshot.log"
