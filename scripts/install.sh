#!/usr/bin/env bash
# install.sh — установка remnawave-monitoring на сервер мониторинга (Debian/Ubuntu, root).
#   одной строкой: curl -fsSL https://raw.githubusercontent.com/ponoroshca/remnawave-monitoring/main/scripts/install.sh | sudo bash
#   из клона:      sudo ./scripts/install.sh
#   NO_SETUP=1     только скопировать файлы, мастер не запускать
#   INSTALL_DOCKER=1  поставить Docker без вопроса, если его нет
# Пишет только в /opt/remnawave-monitoring и /usr/local/bin/remnawave-monitoring. При повторном запуске
# обновляет скрипты и конфиги стека, но НЕ трогает .env, prometheus/targets/*.yml и telegram.yml.
set -euo pipefail
OPT=/opt/remnawave-monitoring
SRC_URL="${RWMON_SRC_URL:-https://github.com/ponoroshca/remnawave-monitoring/archive/refs/heads/main.tar.gz}"
[ "$(id -u)" = 0 ] || { echo "нужен root (sudo)"; exit 1; }
command -v python3 >/dev/null || { apt-get update -qq && apt-get install -y -qq python3; }
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' || { echo "нужен Python 3.9+"; exit 1; }
for t in curl tar; do command -v "$t" >/dev/null || { apt-get update -qq && apt-get install -y -qq "$t"; }; done

# ── Docker ──
if ! command -v docker >/dev/null || ! docker compose version >/dev/null 2>&1; then
  echo "Docker с compose v2 не найден — он нужен для стека (Prometheus, Grafana, Kuma работают в контейнерах)."
  ans="${INSTALL_DOCKER:-}"
  if [ -z "$ans" ] && [ -r /dev/tty ]; then read -r -p "Установить Docker сейчас? [Y/n]: " ans </dev/tty || true; fi
  case "${ans:-y}" in
    [Yy]*|1)
      if apt-get install -y -qq docker.io docker-compose-v2 >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
        echo "  docker из репозитория дистрибутива"
      else
        echo "  ставлю с get.docker.com (официальный скрипт Docker)…"
        curl -fsSL https://get.docker.com | sh >/dev/null
      fi
      systemctl enable --now docker >/dev/null 2>&1 || true
      docker compose version >/dev/null 2>&1 || { echo "docker compose так и не появился — установите Docker вручную и повторите"; exit 1; }
      ;;
    *) echo "без Docker продолжать нечем. Установите его и повторите."; exit 1 ;;
  esac
fi

# ── чужие файлы ──
f=/usr/local/bin/remnawave-monitoring
if [ -e "$f" ] && { [ ! -L "$f" ] || [[ "$(readlink -f "$f")" != $OPT/* ]]; }; then
  echo "СТОП: $f уже существует и это не наша ссылка. Ничего не изменено."; exit 1
fi
if [ -d "$OPT" ] && [ ! -f "$OPT/scripts/rwmon.py" ] && [ -n "$(ls -A "$OPT" 2>/dev/null)" ]; then
  echo "СТОП: $OPT существует и это не наша установка. Ничего не изменено."; exit 1
fi

# ── исходники ──
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." 2>/dev/null && pwd || true)"; WORK=""
if [ -n "$HERE" ] && [ -f "$HERE/scripts/rwmon.py" ] && [ "$HERE" != "$OPT" ]; then SRC="$HERE"; else
  WORK=$(mktemp -d); echo "исходники: $SRC_URL"
  curl -fsSL --retry 3 -o "$WORK/src.tar.gz" "$SRC_URL"; tar -xzf "$WORK/src.tar.gz" -C "$WORK"
  SRC=$(dirname "$(dirname "$(find "$WORK" -path '*/scripts/rwmon.py' | head -1)")"); [ -d "$SRC/stack" ] || { echo "в архиве нет stack/"; exit 1; }
fi
trap '[ -n "$WORK" ] && rm -rf "$WORK"' EXIT

# ── копирование: скрипты и конфиги обновляем, пользовательские файлы сохраняем ──
mkdir -p "$OPT"
KEEP=$(mktemp -d)
for k in stack/.env stack/prometheus/targets/nodes.yml stack/prometheus/targets/blackbox.yml stack/prometheus/targets/http.yml stack/grafana/provisioning/alerting/telegram.yml; do
  [ -f "$OPT/$k" ] && { mkdir -p "$KEEP/$(dirname "$k")"; cp -p "$OPT/$k" "$KEEP/$k"; }
done
for d in exporter scripts backup tools docs; do
  [ -d "$SRC/$d" ] || continue
  rm -rf "$OPT/$d"; cp -R "$SRC/$d" "$OPT/$d"
done
mkdir -p "$OPT/stack"; cp -R "$SRC/stack/." "$OPT/stack/"      # поверх: .env и цели не удаляются ни на миг
for x in README.md LICENSE CHANGELOG.md; do [ -f "$SRC/$x" ] && cp "$SRC/$x" "$OPT/$x"; done
(cd "$KEEP" && find . -type f | while read -r k; do mkdir -p "$OPT/$(dirname "$k")"; cp -p "$k" "$OPT/$k"; done)
rm -rf "$KEEP"
chmod 755 "$OPT"/scripts/*.sh "$OPT"/scripts/rwmon.py "$OPT"/backup/*.sh "$OPT"/exporter/rw_exporter.py
[ -f "$OPT/stack/.env" ] && chmod 600 "$OPT/stack/.env"
ln -sf "$OPT/scripts/rwmon.py" /usr/local/bin/remnawave-monitoring
echo "установлено: $OPT (в PATH: remnawave-monitoring)"
if [ -f "$OPT/stack/.env" ]; then
  echo "найден прежний .env — применяю обновление стека: docker compose up -d"
  (cd "$OPT/stack" && docker compose up -d --remove-orphans 2>&1 | tail -3) || true
fi
if [ "${NO_SETUP:-0}" != 1 ] && [ -t 1 ] && [ -r /dev/tty ]; then
  echo; echo "Запускаю мастер (Ctrl+C — прервать; позже: remnawave-monitoring setup)…"; echo
  remnawave-monitoring setup </dev/tty || true
else
  echo "Дальше: remnawave-monitoring setup"
fi
