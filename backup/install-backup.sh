#!/usr/bin/env bash
# install-backup.sh — установка зашифрованных бэкапов (панель Remnawave и/или сервер мониторинга). root.
#   curl -fsSL https://raw.githubusercontent.com/ponoroshca/remnawave-monitoring/main/backup/install-backup.sh | sudo bash
#   из клона: sudo ./backup/install-backup.sh        флаги: --uninstall, NO_SETUP=1, --offsite-receiver (см. ниже)
# Пишет только в /opt/remnawave-backup, /etc/remnawave-backup, /var/backups/remnawave и юниты remnawave-backup.*.
#   --offsite-receiver /root/remnawave-offsite   режим ПРИНИМАЮЩЕГО сервера: папка + rrsync + снимки; ключ отправителя
#                                                 добавляется в authorized_keys с ограничением «только rsync в эту папку»
set -euo pipefail
OPT=/opt/remnawave-backup; ETC=/etc/remnawave-backup; CONF=$ETC/backup.env; OUT=/var/backups/remnawave
SRC_URL="${RWMON_SRC_URL:-https://github.com/ponoroshca/remnawave-monitoring/archive/refs/heads/main.tar.gz}"
[ "$(id -u)" = 0 ] || { echo "нужен root (sudo)"; exit 1; }

if [ "${1:-}" = "--uninstall" ]; then
  systemctl disable --now remnawave-backup.timer remnawave-snapshot.timer 2>/dev/null || true
  rm -f /etc/systemd/system/remnawave-backup.{service,timer} /etc/systemd/system/remnawave-snapshot.{service,timer}; systemctl daemon-reload 2>/dev/null || true
  rm -rf "$OPT"; echo "скрипты и таймеры сняты. Конфиг $CONF и копии в $OUT ОСТАВЛЕНЫ — удалите сами, если нужно."; exit 0
fi

for u in remnawave-backup.service remnawave-backup.timer remnawave-snapshot.service remnawave-snapshot.timer; do
  f="/etc/systemd/system/$u"
  if [ -f "$f" ] && ! grep -q "remnawave-backup" "$f"; then echo "СТОП: $f уже существует и это не наш юнит. Ничего не изменено."; exit 1; fi
done
for t in curl tar rsync; do command -v "$t" >/dev/null || { apt-get update -qq >/dev/null && apt-get install -y -qq "$t" >/dev/null 2>&1 || { echo "не удалось поставить $t"; exit 1; }; }; done
if ! command -v age >/dev/null; then
  apt-get update -qq && apt-get install -y -qq age >/dev/null 2>&1 || { echo "не удалось поставить age из apt — https://github.com/FiloSottile/age/releases (нужны age и age-keygen в PATH)"; exit 1; }
fi
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." 2>/dev/null && pwd || true)"; WORK=""
if [ -n "$HERE" ] && [ -f "$HERE/backup/common.sh" ] && [ "$HERE" != "$OPT" ]; then SRC="$HERE/backup"; else
  WORK=$(mktemp -d); echo "исходники: $SRC_URL"
  curl -fsSL --retry 3 -o "$WORK/src.tar.gz" "$SRC_URL"; tar -xzf "$WORK/src.tar.gz" -C "$WORK"
  SRC=$(dirname "$(find "$WORK" -path '*/backup/common.sh' | head -1)")
fi
trap '[ -n "$WORK" ] && rm -rf "$WORK"' EXIT
mkdir -p "$OPT" "$ETC"; chmod 700 "$ETC"
install -m 755 "$SRC"/*.sh "$OPT/"; chmod 644 "$OPT/common.sh"
mkdir -p /etc/systemd/system; install -m 644 "$SRC"/systemd/*.service "$SRC"/systemd/*.timer /etc/systemd/system/
command -v systemctl >/dev/null && systemctl daemon-reload 2>/dev/null || true
echo "скрипты: $OPT"

# ── режим принимающего сервера ──
if [ "${1:-}" = "--offsite-receiver" ]; then
  DIR="${2:-/root/remnawave-offsite}"; mkdir -p "$DIR/current" "$DIR/snapshots"; chmod 700 "$DIR"
  RR=$(command -v rrsync || ls /usr/share/doc/rsync/scripts/rrsync 2>/dev/null || true)
  [ -n "$RR" ] || { echo "нет rrsync (идёт с rsync ≥ 3.2.4; apt install rsync)"; exit 1; }
  [ -x "$RR" ] || { cp "$RR" /usr/local/bin/rrsync; chmod 755 /usr/local/bin/rrsync; RR=/usr/local/bin/rrsync; }
  sed -i "s#ExecStart=.*#ExecStart=$OPT/snapshot.sh $DIR 14#" /etc/systemd/system/remnawave-snapshot.service
  { command -v systemctl >/dev/null && systemctl daemon-reload 2>/dev/null && systemctl enable --now remnawave-snapshot.timer >/dev/null 2>&1; } || echo "  ⚠️  systemd недоступен — таймер снимков не включён"
  echo "принимающая папка: $DIR/current, снимки раз в сутки в $DIR/snapshots (14 шт.)"
  echo "Теперь на ОТПРАВЛЯЮЩЕМ сервере возьмите содержимое /root/.ssh/remnawave-backup.pub и добавьте сюда в /root/.ssh/authorized_keys строкой:"
  echo "  restrict,command=\"$RR $DIR/current\" <содержимое .pub>"
  echo "и в его конфиге $CONF: OFFSITE=root@$(hostname -I | awk '{print $1}'):$DIR/current"
  exit 0
fi

[ "${NO_SETUP:-0}" = 1 ] && { echo "NO_SETUP=1 — мастер не запущен. Конфиг: $CONF (пример в docs/reference.md)"; exit 0; }
[ -r /dev/tty ] || { echo "нет терминала для мастера — запустите позже: $OPT/install-backup.sh"; exit 0; }
exec </dev/tty
declare -A C; if [ -f "$CONF" ]; then while IFS='=' read -r k v; do [[ "$k" =~ ^[A-Z_]+$ ]] && C[$k]="$v"; done < "$CONF"; echo "найден прежний конфиг — значения предложены по умолчанию"; fi
ask() { local v; read -r -p "$1${2:+ [$2]}: " v; echo "${v:-$2}"; }

echo "── 1/4 Ключ шифрования (age) ──"
if [ -n "${C[RECIPIENT]:-}" ]; then echo "  уже задан: ${C[RECIPIENT]}"; REC="${C[RECIPIENT]}"; else
  echo "  Копии шифруются публичным ключом; расшифровать может только секретный ключ — храните его НЕ на этом сервере"
  echo "  (менеджер паролей + бумага). Потеряете секретный ключ — бэкапы бесполезны. Утечёт сервер — бэкапы не читаемы."
  echo "   1) сгенерировать пару сейчас, секретный ключ показать один раз и с сервера стереть"
  echo "   2) вставить публичный ключ, сгенерированный на вашем компьютере (age-keygen)"
  case "$(ask "выбор" 1)" in
    2) REC=$(ask "публичный ключ age1…"); [[ "$REC" =~ ^age1[a-z0-9]{58}$ ]] || { echo "не похоже на публичный ключ age"; exit 1; } ;;
    *) KEYD=$(mktemp -d); KEYF="$KEYD/key"; age-keygen -o "$KEYF" 2>/dev/null || { echo "age-keygen не отработал"; exit 1; }
       REC=$(grep -oE 'age1[a-z0-9]{58}' "$KEYF" | head -1); SEC=$(grep -oE 'AGE-SECRET-KEY-1[A-Z0-9]{58}' "$KEYF")
       [ -n "$REC" ] && [ -n "$SEC" ] || { echo "не разобрал вывод age-keygen"; exit 1; }
       echo; echo "  ════════ СЕКРЕТНЫЙ КЛЮЧ — сохраните сейчас в менеджер паролей и на бумагу ════════"; echo "  $SEC"; echo "  ═══════════════════════════════════════════════════════════════════════════════"
       while :; do V=$(ask "  вставьте секретный ключ обратно для проверки"); [ "$V" = "$SEC" ] && break; echo "  не совпадает — скопируйте целиком, без пробелов"; done
       shred -u "$KEYF" 2>/dev/null || rm -f "$KEYF"; rm -rf "$KEYD"; unset SEC V; echo "  ✅ ключ проверен, с сервера стёрт. Публичный: $REC" ;;
  esac
fi
echo "── 2/4 Что бэкапить на этом сервере ──"
P=0; M=0
if docker inspect remnawave-db >/dev/null 2>&1; then P=1; echo "  найдена панель (контейнер remnawave-db, папка ${C[PANEL_DIR]:-/opt/remnawave})"; else echo "  панели здесь нет (нет контейнера remnawave-db)"; fi
if [ -d "${C[MONITORING_DIR]:-/opt/remnawave-monitoring}/stack" ]; then M=1; echo "  найден стек мониторинга (${C[MONITORING_DIR]:-/opt/remnawave-monitoring})"; fi
[ "$P" = 1 ] || [ "$M" = 1 ] || { echo "  бэкапить нечего: ни панели, ни мониторинга. Конфиг не записан."; exit 1; }
HOUR=$(ask "во сколько делать (часы:минуты, по времени сервера — $(date +%Z))" "${C[HOUR]:-03:30}")
[[ "$HOUR" =~ ^[0-2]?[0-9]:[0-5][0-9]$ ]] || { echo "формат ЧЧ:ММ"; exit 1; }
echo "── 3/4 Telegram об ошибках ──"
TGT="${C[TELEGRAM_BOT_TOKEN]:-}"; TGC="${C[TELEGRAM_CHAT_ID]:-}"
MENV="${C[MONITORING_DIR]:-/opt/remnawave-monitoring}/stack/.env"
if [ -z "$TGT" ] && [ -f "$MENV" ] && grep -q '^TELEGRAM_BOT_TOKEN=.\+' "$MENV"; then
  case "$(ask "нашёл Telegram в настройках мониторинга — использовать его? [Y/n]" Y)" in [Nn]*) ;; *) TGT=$(grep '^TELEGRAM_BOT_TOKEN=' "$MENV" | cut -d= -f2-); TGC=$(grep '^TELEGRAM_CHAT_ID=' "$MENV" | cut -d= -f2-);; esac
fi
if [ -z "$TGT" ]; then read -r -s -p "токен бота (Enter — без Telegram): " TGT; echo; fi
if [ -n "$TGT" ] && [ -z "$TGC" ]; then
  TGC=$(python3 - "$TGT" <<'PY' || true
import json, sys, time, urllib.request, urllib.parse
tok = sys.argv[1]
def api(m, p=None, t=30):
    d = urllib.parse.urlencode(p).encode() if p else None
    return json.load(urllib.request.urlopen(urllib.request.Request("https://api.telegram.org/bot%s/%s" % (tok, m), data=d), timeout=t))
try:
    me = api("getMe")["result"]["username"]
except Exception as e:
    print("токен не принят: %s" % e, file=sys.stderr); sys.exit(1)
print("  откройте https://t.me/%s и нажмите Start — жду до 90 с…" % me, file=sys.stderr)
t0, off = time.time(), None
while time.time() - t0 < 90:
    try:
        r = api("getUpdates", {"timeout": 15, **({"offset": off} if off else {})})
    except Exception:
        time.sleep(2); continue
    for u in r.get("result", []):
        off = u["update_id"] + 1; ch = (u.get("message") or {}).get("chat") or {}
        if ch.get("id"):
            print(ch["id"]); sys.exit(0)
print("сообщение не пришло", file=sys.stderr); sys.exit(1)
PY
)
  [ -n "$TGC" ] && echo "  ✅ chat_id $TGC" || TGC=$(ask "chat_id вручную (пусто — без Telegram)")
fi
echo "── 4/4 Копия на другой сервер (offsite) ──"
echo "  Второй сервер (лучше в другой стране) получает копии по rsync. Там: install-backup.sh --offsite-receiver"
OFF=$(ask "OFFSITE как user@host:/root/remnawave-offsite/current (Enter — пока без него)" "${C[OFFSITE]:-}")
if [ -n "$OFF" ]; then
  KEY=/root/.ssh/remnawave-backup
  [ -f "$KEY" ] || { ssh-keygen -q -t ed25519 -N "" -C remnawave-backup -f "$KEY"; echo "  создан ключ $KEY"; }
  echo "  на принимающем сервере в /root/.ssh/authorized_keys должна быть строка:"
  echo "    restrict,command=\"rrsync ${OFF#*:}\" $(cat $KEY.pub)"
  echo "  (rrsync и папку создаёт там install-backup.sh --offsite-receiver ${OFF#*:} без /current)"
fi
mkdir -p "$OUT"; chmod 700 "$OUT"
umask 077
cat > "$CONF" <<EOF
# remnawave-backup — конфиг (права 600). Справочник: docs/reference.md
RECIPIENT=$REC
OUT_DIR=$OUT
KEEP_DAYS=14
MON_KEEP_DAYS=7
KEEP_MIN=3
BACKUP_PANEL=$P
BACKUP_MONITORING=$M
DB_CONTAINER=${C[DB_CONTAINER]:-remnawave-db}
PANEL_DIR=${C[PANEL_DIR]:-/opt/remnawave}
MONITORING_DIR=${C[MONITORING_DIR]:-/opt/remnawave-monitoring}
HOUR=$HOUR
TELEGRAM_BOT_TOKEN=$TGT
TELEGRAM_CHAT_ID=$TGC
TELEGRAM_PROXY=${C[TELEGRAM_PROXY]:-}
OFFSITE=$OFF
OFFSITE_KEY=/root/.ssh/remnawave-backup
OFFSITE_PORT=${C[OFFSITE_PORT]:-22}
EOF
chmod 600 "$CONF"; echo "  ✅ конфиг: $CONF"
sed -i "s/^OnCalendar=.*/OnCalendar=*-*-* $(printf '%02d:%02d' "$((10#${HOUR%%:*}))" "$((10#${HOUR##*:}))"):00/" /etc/systemd/system/remnawave-backup.timer
if command -v systemctl >/dev/null && systemctl daemon-reload 2>/dev/null && systemctl enable --now remnawave-backup.timer >/dev/null 2>&1; then
  echo "  ✅ таймер: ежедневно в $HOUR (systemctl list-timers remnawave-backup.timer)"
else
  echo "  ⚠️  systemd недоступен (контейнер?) — таймер не включён; запускайте $OPT/run.sh из cron"
fi
[ -n "$TGT" ] && [ -n "$TGC" ] && curl -s -m 15 "https://api.telegram.org/bot$TGT/sendMessage" --data-urlencode "chat_id=$TGC" --data-urlencode "text=✅ remnawave-backup на $(hostname): бэкапы включены, ежедневно в $HOUR. Сюда придёт сообщение, если бэкап не удастся." >/dev/null && echo "  telegram: отправлено"
echo "── Первый бэкап прямо сейчас ──"
if "$OPT/run.sh"; then echo "  ✅ $(tail -1 "$OUT/backup.log")"; ls -la "$OUT"/panel "$OUT"/monitoring 2>/dev/null | grep -E '\.tar\.age$' | awk '{print "    "$NF" ("$5" байт)"}'
else echo "  ❌ первый бэкап не удался — см. $OUT/backup.log"; exit 1; fi
echo
echo "Готово. Раз в месяц проверяйте на своём компьютере: backup/verify-restore.sh <архив> <секретный ключ> (docs/RECOVERY.md)."
