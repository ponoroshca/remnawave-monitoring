#!/usr/bin/env python3
"""rw_exporter — Prometheus-экспортёр панели Remnawave. Только стандартная библиотека Python 3.9+.

Раз в SCRAPE_SECONDS читает /api/system/stats и /api/nodes панели (только чтение) и отдаёт метрики
на http://LISTEN/metrics. Все настройки — переменными окружения (см. docs/reference.md):

  PANEL_URL        адрес панели, например https://panel.example.com  (обязательно)
  PANEL_TOKEN      API-токен панели                                   (обязательно)
  SCRAPE_SECONDS   период опроса панели, секунд                       (30)
  LISTEN           адрес:порт для /metrics                            (0.0.0.0:9200)
  BRIDGE_TAG       тег ноды в панели, означающий «мост»               (bridge)
  BRIDGE_REGEX     регулярное выражение по имени ноды → «мост»        ((?i)bridge)
  BRIDGE_COUNTRIES страны через запятую, чьи ноды считать мостами     (пусто)
  PANEL_INSECURE   1 — не проверять TLS-сертификат панели             (0)
  PANEL_TIMEOUT    таймаут запроса к панели, секунд                   (20)

Роль ноды (label role): bridge — если у ноды есть тег BRIDGE_TAG, или имя подходит под BRIDGE_REGEX,
или страна входит в BRIDGE_COUNTRIES; иначе node.
"""
import json
import os
import re
import ssl
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

VERSION = "1.0.0"


def env(name, default=None):
    v = os.environ.get(name)
    return v if v not in (None, "") else default


PANEL_URL = (env("PANEL_URL") or "").rstrip("/")
PANEL_TOKEN = env("PANEL_TOKEN") or ""
PERIOD = max(5, int(env("SCRAPE_SECONDS", "30")))
LISTEN = env("LISTEN", "0.0.0.0:9200")
BRIDGE_TAG = (env("BRIDGE_TAG", "bridge") or "").strip().lower()
BRIDGE_REGEX = re.compile(env("BRIDGE_REGEX", "(?i)bridge")) if env("BRIDGE_REGEX", "(?i)bridge") else None
BRIDGE_COUNTRIES = {c.strip().upper() for c in (env("BRIDGE_COUNTRIES", "") or "").split(",") if c.strip()}
TIMEOUT = int(env("PANEL_TIMEOUT", "20"))

_ctx = ssl.create_default_context()
if env("PANEL_INSECURE", "0") == "1":
    _ctx.check_hostname = False
    _ctx.verify_mode = ssl.CERT_NONE

_lock = threading.Lock()
_state = {"text": "# rw_exporter: первый опрос панели ещё не завершён\n", "ok": False,
          "scrapes": 0, "errors": 0, "last_ok": 0.0, "last_error": ""}


def api_get(path):
    """GET /api/<path> панели → поле response."""
    req = urllib.request.Request(PANEL_URL + "/api/" + path.lstrip("/"),
                                 headers={"Authorization": "Bearer " + PANEL_TOKEN,
                                          "User-Agent": "rw_exporter/" + VERSION})
    with urllib.request.urlopen(req, timeout=TIMEOUT, context=_ctx) as r:
        data = json.load(r)
    if not isinstance(data, dict) or "response" not in data:
        raise RuntimeError("неожиданный ответ панели на /api/%s: %s" % (path, str(data)[:120]))
    return data["response"]


def esc(v):
    return str(v).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def num(v, default=0):
    """Число из ответа панели: None/строки/мусор → default."""
    try:
        if v is None or isinstance(v, bool):
            return int(v) if isinstance(v, bool) else default
        return float(v) if isinstance(v, (int, float, str)) else default
    except (TypeError, ValueError):
        return default


def fmt(v):
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return repr(float(v)) if isinstance(v, float) else str(v)


def node_role(node):
    tags = [str(t).strip().lower() for t in (node.get("tags") or [])]
    if BRIDGE_TAG and BRIDGE_TAG in tags:
        return "bridge"
    if BRIDGE_REGEX and BRIDGE_REGEX.search(node.get("name") or ""):
        return "bridge"
    if (node.get("countryCode") or "").upper() in BRIDGE_COUNTRIES:
        return "bridge"
    return "node"


class Metrics:
    """Накопитель строк в формате Prometheus text exposition 0.0.4 с HELP/TYPE."""

    def __init__(self):
        self.lines = []
        self.described = set()

    def add(self, name, value, help_text, mtype="gauge", **labels):
        if name not in self.described:
            self.lines.append("# HELP %s %s" % (name, help_text))
            self.lines.append("# TYPE %s %s" % (name, mtype))
            self.described.add(name)
        if labels:
            lbl = ",".join('%s="%s"' % (k, esc(v)) for k, v in labels.items())
            self.lines.append("%s{%s} %s" % (name, lbl, fmt(value)))
        else:
            self.lines.append("%s %s" % (name, fmt(value)))

    def text(self):
        return "\n".join(self.lines) + "\n"


def collect():
    m = Metrics()
    stats = api_get("system/stats")
    online = stats.get("onlineStats") or {}
    users = stats.get("users") or {}
    m.add("remnawave_online_now", num(online.get("onlineNow")), "Уникальных пользователей онлайн сейчас (по данным панели)")
    m.add("remnawave_online_last_day", num(online.get("lastDay")), "Пользователей, выходивших онлайн за последние сутки")
    m.add("remnawave_online_last_week", num(online.get("lastWeek")), "Пользователей, выходивших онлайн за последнюю неделю")
    m.add("remnawave_online_never", num(online.get("neverOnline")), "Пользователей, ни разу не подключавшихся")
    m.add("remnawave_users_total", num(users.get("totalUsers")), "Всего пользователей в панели")
    for status, count in (users.get("statusCounts") or {}).items():
        m.add("remnawave_users_by_status", num(count), "Пользователей по статусу (ACTIVE, DISABLED, LIMITED, EXPIRED)", status=status)
    m.add("remnawave_sessions_total", num((stats.get("nodes") or {}).get("totalOnline")),
          "Сессий (подключений) на всех нодах сейчас; один пользователь с двух устройств — две сессии")
    m.add("remnawave_panel_uptime_seconds", num(stats.get("uptime")), "Аптайм сервера панели, секунд")
    mem = stats.get("memory") or {}
    m.add("remnawave_panel_memory_total_bytes", num(mem.get("total")), "Память сервера панели, всего")
    m.add("remnawave_panel_memory_used_bytes", num(mem.get("used")), "Память сервера панели, занято")
    m.add("remnawave_panel_cpu_cores", num((stats.get("cpu") or {}).get("cores")), "Ядер CPU на сервере панели")

    nodes = api_get("nodes")
    if not isinstance(nodes, list):
        raise RuntimeError("панель вернула /api/nodes не списком")
    connected = disabled = 0
    for n in nodes:
        name = n.get("name") or n.get("uuid") or "?"
        lbl = dict(node=name, role=node_role(n), country=(n.get("countryCode") or "").upper())
        is_conn = 1 if n.get("isConnected") else 0
        is_dis = 1 if n.get("isDisabled") else 0
        connected += is_conn
        disabled += is_dis
        m.add("remnawave_node_connected", is_conn, "1 — нода на связи с панелью", **lbl)
        m.add("remnawave_node_disabled", is_dis, "1 — нода выключена в панели (не считается проблемой)", **lbl)
        m.add("remnawave_node_users_online", num(n.get("usersOnline")), "Сессий на ноде сейчас", **lbl)
        used = num(n.get("trafficUsedBytes"))
        limit = num(n.get("trafficLimitBytes"))
        m.add("remnawave_node_traffic_used_bytes", used, "Трафик пользователей ноды, накопленный панелью (счётчик панели, не хостера)", **lbl)
        m.add("remnawave_node_traffic_limit_bytes", limit, "Лимит трафика ноды в панели; 0 — лимита нет", **lbl)
        m.add("remnawave_node_traffic_used_percent", round(used / limit * 100, 2) if limit > 0 else 0,
              "Процент лимита трафика ноды; 0 — если лимита нет", **lbl)
        m.add("remnawave_node_traffic_reset_day", num(n.get("trafficResetDay")), "День месяца, когда панель сбрасывает счётчик трафика ноды", **lbl)
        m.add("remnawave_node_xray_uptime_seconds", num(n.get("xrayUptime")), "Аптайм xray на ноде, секунд", **lbl)
        sysinfo = (n.get("system") or {}).get("info") or {}
        st = (n.get("system") or {}).get("stats") or {}
        m.add("remnawave_node_system_uptime_seconds", num(st.get("uptime")), "Аптайм сервера ноды, секунд", **lbl)
        m.add("remnawave_node_cpus", num(sysinfo.get("cpus")), "Ядер CPU на ноде", **lbl)
        m.add("remnawave_node_memory_total_bytes", num(sysinfo.get("memoryTotal")), "Память ноды, всего", **lbl)
        m.add("remnawave_node_memory_free_bytes", num(st.get("memoryFree")), "Память ноды, свободно", **lbl)
        load = st.get("loadAvg") or []
        for i, key in enumerate(("load1", "load5", "load15")):
            if i < len(load):
                m.add("remnawave_node_" + key, num(load[i]), "Load average ноды за 1/5/15 минут", **lbl)
        iface = st.get("interface") or {}
        m.add("remnawave_node_rx_bytes_per_second", num(iface.get("rxBytesPerSec")), "Входящая скорость интерфейса ноды, байт/с (умножьте на 8 — биты)", **lbl)
        m.add("remnawave_node_tx_bytes_per_second", num(iface.get("txBytesPerSec")), "Исходящая скорость интерфейса ноды, байт/с", **lbl)
        m.add("remnawave_node_rx_bytes_total", num(iface.get("rxTotal")), "Счётчик интерфейса ноды с загрузки сервера, входящие байты (так считает хостер)", "counter", **lbl)
        m.add("remnawave_node_tx_bytes_total", num(iface.get("txTotal")), "Счётчик интерфейса ноды с загрузки сервера, исходящие байты", "counter", **lbl)
        versions = n.get("versions") or {}
        m.add("remnawave_node_info", 1, "Версии xray и remnanode на ноде (всегда 1, данные — в метках)",
              xray_version=versions.get("xray") or "", node_version=versions.get("node") or "", **lbl)
    m.add("remnawave_nodes_total", len(nodes), "Нод в панели, всего")
    m.add("remnawave_nodes_connected", connected, "Нод на связи с панелью")
    m.add("remnawave_nodes_disabled", disabled, "Нод, выключенных в панели")
    return m


def loop():
    while True:
        started = time.time()
        try:
            m = collect()
            ok, err = True, ""
        except Exception as e:  # noqa: BLE001 — любая ошибка панели/сети = метрика ошибки, экспортёр живёт
            m = Metrics()
            ok, err = False, "%s: %s" % (type(e).__name__, e)
        dur = time.time() - started
        with _lock:
            _state["scrapes"] += 1
            if ok:
                _state["last_ok"] = time.time()
            else:
                _state["errors"] += 1
                _state["last_error"] = err
                print("ошибка опроса панели: %s" % err, file=sys.stderr, flush=True)
            _state["ok"] = ok
            m.add("remnawave_exporter_up", 1 if ok else 0, "1 — последний опрос панели удался")
            m.add("remnawave_exporter_scrape_duration_seconds", round(dur, 3), "Длительность последнего опроса панели")
            m.add("remnawave_exporter_last_success_timestamp_seconds", int(_state["last_ok"]), "Unix-время последнего удачного опроса")
            m.add("remnawave_exporter_scrapes_total", _state["scrapes"], "Опросов панели с запуска экспортёра", "counter")
            m.add("remnawave_exporter_errors_total", _state["errors"], "Неудачных опросов с запуска экспортёра", "counter")
            m.add("remnawave_exporter_info", 1, "Версия экспортёра", version=VERSION)
            _state["text"] = m.text()
        time.sleep(max(1.0, PERIOD - dur))


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="text/plain; charset=utf-8"):
        b = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(b)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        with _lock:
            text, ok, err = _state["text"], _state["ok"], _state["last_error"]
        if path == "/metrics":
            self._send(200, text, "text/plain; version=0.0.4; charset=utf-8")
        elif path in ("/healthz", "/health"):
            self._send(200 if ok else 503, "ok\n" if ok else "panel scrape failed: %s\n" % err)
        else:
            self._send(200, "rw_exporter %s — метрики панели Remnawave: /metrics, здоровье: /healthz\n" % VERSION)

    do_HEAD = do_GET

    def log_message(self, *args):
        pass


def main():
    if "--version" in sys.argv:
        print(VERSION)
        return 0
    if not PANEL_URL or not PANEL_TOKEN:
        print("нужны переменные окружения PANEL_URL и PANEL_TOKEN (см. docs/reference.md)", file=sys.stderr)
        return 2
    if not PANEL_URL.startswith(("http://", "https://")):
        print("PANEL_URL должен начинаться с http:// или https://", file=sys.stderr)
        return 2
    host, _, port = LISTEN.rpartition(":")
    try:
        port = int(port)
    except ValueError:
        print("LISTEN должен быть вида адрес:порт, например 0.0.0.0:9200", file=sys.stderr)
        return 2
    threading.Thread(target=loop, daemon=True).start()
    print("rw_exporter %s: панель %s, опрос раз в %d с, слушаю %s:%d" % (VERSION, PANEL_URL, PERIOD, host or "0.0.0.0", port), flush=True)
    try:
        ThreadingHTTPServer((host or "0.0.0.0", port), Handler).serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
