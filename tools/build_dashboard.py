#!/usr/bin/env python3
"""Генератор дашбордов Grafana → stack/grafana/provisioning/dashboards/json/*.json.
Правьте панели здесь и запускайте: python3 tools/build_dashboard.py  (CI проверяет, что JSON в репозитории совпадает).
--check — только сравнить с файлами, код выхода 1 при расхождении."""
import json
import os
import sys

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "stack", "grafana", "provisioning", "dashboards", "json")
DS = {"type": "prometheus", "uid": "prometheus"}
FLAGS = {"RU": "🇷🇺", "DE": "🇩🇪", "NL": "🇳🇱", "FI": "🇫🇮", "FR": "🇫🇷", "CH": "🇨🇭", "SE": "🇸🇪", "US": "🇺🇸", "PL": "🇵🇱",
         "ES": "🇪🇸", "BG": "🇧🇬", "GR": "🇬🇷", "LV": "🇱🇻", "CZ": "🇨🇿", "GB": "🇬🇧", "IT": "🇮🇹", "TR": "🇹🇷", "KZ": "🇰🇿",
         "AM": "🇦🇲", "GE": "🇬🇪", "AT": "🇦🇹", "EE": "🇪🇪", "LT": "🇱🇹", "RO": "🇷🇴", "HU": "🇭🇺", "JP": "🇯🇵", "SG": "🇸🇬",
         "CA": "🇨🇦", "UA": "🇺🇦", "MD": "🇲🇩", "RS": "🇷🇸", "HK": "🇭🇰", "AE": "🇦🇪", "IN": "🇮🇳", "BR": "🇧🇷"}
_id = [0]


def nid():
    _id[0] += 1
    return _id[0]


def q(expr, legend="", instant=False, table=False, ref="A"):
    t = {"refId": ref, "expr": expr, "datasource": DS, "legendFormat": legend}
    if instant:
        t["instant"] = True
        t["range"] = False
    if table:
        t["format"] = "table"
    return t


def pos(x, y, w, h):
    return {"x": x, "y": y, "w": w, "h": h}


def stat(title, expr, gp, unit="short", dec=0, color="blue", steps=None, spark=False, desc=""):
    fc = {"unit": unit, "decimals": dec, "color": {"mode": "fixed", "fixedColor": color}}
    if steps:
        fc["thresholds"] = {"mode": "absolute", "steps": steps}
        fc["color"] = {"mode": "thresholds"}
    return {"id": nid(), "type": "stat", "title": title, "description": desc, "datasource": DS, "gridPos": gp,
            "targets": [q(expr, instant=True)],
            "fieldConfig": {"defaults": fc, "overrides": []},
            "options": {"colorMode": "value", "graphMode": "area" if spark else "none", "textMode": "value",
                        "justifyMode": "center", "reduceOptions": {"calcs": ["lastNotNull"], "fields": ""}}}


def timeseries(title, targets, gp, unit="short", dec=None, stack=False, desc="", fill=12, max_=None):
    fc = {"unit": unit, "custom": {"fillOpacity": fill, "lineWidth": 2, "showPoints": "never", "gradientMode": "opacity",
                                   "stacking": {"mode": "normal" if stack else "none"}}}
    if dec is not None:
        fc["decimals"] = dec
    if max_ is not None:
        fc["max"] = max_
        fc["min"] = 0
    return {"id": nid(), "type": "timeseries", "title": title, "description": desc, "datasource": DS, "gridPos": gp,
            "targets": targets, "fieldConfig": {"defaults": fc, "overrides": []},
            "options": {"legend": {"displayMode": "list", "placement": "bottom", "showLegend": True}, "tooltip": {"mode": "multi", "sort": "desc"}}}


def bargauge(title, expr, gp, unit="percent", steps=None, max_=100, dec=1, desc="", legend="{{node}}"):
    return {"id": nid(), "type": "bargauge", "title": title, "description": desc, "datasource": DS, "gridPos": gp,
            "targets": [q(expr, legend, instant=True)],
            "fieldConfig": {"defaults": {"unit": unit, "min": 0, "max": max_, "decimals": dec,
                                         "thresholds": {"mode": "absolute", "steps": steps or [{"color": "green", "value": None}]}},
                            "overrides": []},
            "options": {"orientation": "horizontal", "displayMode": "gradient", "valueMode": "color", "showUnfilled": True,
                        "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False}}}


def country_mapping():
    return {"id": "mappings", "value": [{"type": "value", "options": {k: {"text": "%s %s" % (v, k), "index": i} for i, (k, v) in enumerate(FLAGS.items())}}]}


def fleet_dashboard():
    _id[0] = 0
    y = 0
    panels = [
        stat("👥 Онлайн", "remnawave_online_now", pos(0, y, 4, 4), color="blue", spark=True, unit="locale",
             desc="Уникальных пользователей онлайн по данным панели"),
        stat("🔌 Сессий", "remnawave_sessions_total", pos(4, y, 4, 4), color="purple", spark=True, unit="locale",
             desc="Подключений на всех нодах; пользователь с двух устройств — две сессии"),
        stat("👤 Активных", 'remnawave_users_by_status{status="ACTIVE"}', pos(8, y, 4, 4), color="green", unit="locale"),
        stat("🖥️ Нод на связи", "remnawave_nodes_connected", pos(12, y, 3, 4), color="green"),
        stat("⚠️ Отвалилось", "remnawave_nodes_total - remnawave_nodes_connected - remnawave_nodes_disabled", pos(15, y, 3, 4),
             steps=[{"color": "green", "value": None}, {"color": "red", "value": 1}], desc="Не на связи и при этом не выключены в панели"),
        stat("⬇️ Вход, флот", "sum(remnawave_node_rx_bytes_per_second) * 8", pos(18, y, 3, 4), unit="bps", dec=1, color="blue"),
        stat("⬆️ Выход, флот", "sum(remnawave_node_tx_bytes_per_second) * 8", pos(21, y, 3, 4), unit="bps", dec=1, color="purple"),
    ]
    y += 4
    panels += [
        timeseries("📈 Онлайн — динамика", [q("remnawave_sessions_total", "сессий на нодах"), q("remnawave_online_now", "уникальных пользователей", ref="B")],
                   pos(0, y, 12, 8)),
        timeseries("📶 Полоса нод, вход", [q("remnawave_node_rx_bytes_per_second * 8", "{{node}}")], pos(12, y, 12, 8), unit="bps", dec=1,
                   desc="Входящая скорость интерфейса каждой ноды по данным панели"),
    ]
    y += 8
    table = {"id": nid(), "type": "table", "title": "🌍 Ноды: состояние", "datasource": DS, "gridPos": pos(0, y, 16, 11),
             "description": "Статус, сессии, load на ядро, свободная память и скорость — всё из панели, обновляется каждые SCRAPE_SECONDS",
             "targets": [q("remnawave_node_users_online", instant=True, table=True, ref="A"),
                         q("remnawave_node_load1 / remnawave_node_cpus", instant=True, table=True, ref="B"),
                         q("remnawave_node_memory_free_bytes / remnawave_node_memory_total_bytes * 100", instant=True, table=True, ref="C"),
                         q("remnawave_node_rx_bytes_per_second * 8", instant=True, table=True, ref="D"),
                         q("remnawave_node_tx_bytes_per_second * 8", instant=True, table=True, ref="E"),
                         q("remnawave_node_connected", instant=True, table=True, ref="F")],
             "transformations": [
                 {"id": "joinByField", "options": {"byField": "node", "mode": "outer"}},
                 {"id": "organize", "options": {
                     "excludeByName": {"Time": True, "Time 1": True, "Time 2": True, "Time 3": True, "Time 4": True, "Time 5": True, "Time 6": True,
                                       "__name__": True, "__name__ 1": True, "job": True, "job 1": True, "job 2": True, "job 3": True, "job 4": True, "job 5": True, "job 6": True,
                                       "instance": True, "instance 1": True, "instance 2": True, "instance 3": True, "instance 4": True, "instance 5": True, "instance 6": True,
                                       "role 2": True, "role 3": True, "role 4": True, "role 5": True, "role 6": True,
                                       "country 2": True, "country 3": True, "country 4": True, "country 5": True, "country 6": True},
                     "renameByName": {"node": "Нода", "role 1": "Роль", "country 1": "Страна", "Value #A": "Сессий", "Value #B": "Load/ядро",
                                      "Value #C": "Память своб.", "Value #D": "⬇️", "Value #E": "⬆️", "Value #F": "Связь"},
                     "indexByName": {"node": 0, "Value #F": 1, "country 1": 2, "role 1": 3, "Value #A": 4, "Value #B": 5, "Value #C": 6, "Value #D": 7, "Value #E": 8}}},
                 {"id": "sortBy", "options": {"sort": [{"field": "Сессий", "desc": True}]}}],
             "fieldConfig": {"defaults": {"custom": {"align": "left", "cellOptions": {"type": "auto"}}}, "overrides": [
                 {"matcher": {"id": "byName", "options": "Страна"}, "properties": [country_mapping(), {"id": "custom.width", "value": 80}]},
                 {"matcher": {"id": "byName", "options": "Связь"}, "properties": [
                     {"id": "mappings", "value": [{"type": "value", "options": {"1": {"text": "● в строю", "color": "green", "index": 0},
                                                                                 "0": {"text": "● отвалилась", "color": "red", "index": 1}}}]},
                     {"id": "custom.cellOptions", "value": {"type": "color-text"}}, {"id": "custom.width", "value": 110}]},
                 {"matcher": {"id": "byName", "options": "Сессий"}, "properties": [
                     {"id": "custom.cellOptions", "value": {"type": "gauge", "mode": "gradient"}}, {"id": "min", "value": 0}, {"id": "max", "value": 300},
                     {"id": "color", "value": {"mode": "continuous-BlPu"}}, {"id": "custom.width", "value": 150}]},
                 {"matcher": {"id": "byName", "options": "Load/ядро"}, "properties": [
                     {"id": "decimals", "value": 2}, {"id": "custom.width", "value": 95}, {"id": "custom.cellOptions", "value": {"type": "color-text"}},
                     {"id": "thresholds", "value": {"mode": "absolute", "steps": [{"color": "green", "value": None}, {"color": "orange", "value": 0.7}, {"color": "red", "value": 0.9}]}}]},
                 {"matcher": {"id": "byName", "options": "Память своб."}, "properties": [
                     {"id": "unit", "value": "percent"}, {"id": "decimals", "value": 0}, {"id": "custom.width", "value": 110}, {"id": "custom.cellOptions", "value": {"type": "color-text"}},
                     {"id": "thresholds", "value": {"mode": "absolute", "steps": [{"color": "red", "value": None}, {"color": "orange", "value": 12}, {"color": "green", "value": 25}]}}]},
                 {"matcher": {"id": "byName", "options": "⬇️"}, "properties": [{"id": "unit", "value": "bps"}, {"id": "decimals", "value": 0}]},
                 {"matcher": {"id": "byName", "options": "⬆️"}, "properties": [{"id": "unit", "value": "bps"}, {"id": "decimals", "value": 0}]},
                 {"matcher": {"id": "byName", "options": "Роль"}, "properties": [{"id": "custom.width", "value": 65}]},
                 {"matcher": {"id": "byName", "options": "Нода"}, "properties": [{"id": "custom.width", "value": 130}]}]},
             "options": {"cellHeight": "sm", "footer": {"show": False}, "showHeader": True}}
    pie = {"id": nid(), "type": "piechart", "title": "🥧 Сессии по странам", "datasource": DS, "gridPos": pos(16, y, 8, 11),
           "targets": [q('sum by (country) (remnawave_node_users_online{role="node"})', "{{country}}", instant=True)],
           "fieldConfig": {"defaults": {"unit": "short"}, "overrides": []},
           "options": {"pieType": "donut", "displayLabels": ["name", "percent"],
                       "legend": {"displayMode": "table", "placement": "right", "values": ["value", "percent"], "showLegend": True},
                       "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False}, "tooltip": {"mode": "single"}}}
    panels += [table, pie]
    y += 11
    panels += [
        bargauge("📊 Трафик к лимиту в панели", "remnawave_node_traffic_used_percent > 0", pos(0, y, 8, 8),
                 steps=[{"color": "green", "value": None}, {"color": "orange", "value": 70}, {"color": "red", "value": 85}],
                 desc="Только ноды, у которых в панели задан лимит трафика. Счётчик панели считает трафик пользователей; хостер считает по интерфейсу — обычно на 10–15% больше"),
        bargauge("🧮 Load на ядро (панель)", "remnawave_node_load1 / remnawave_node_cpus", pos(8, y, 8, 8), unit="none", max_=1.5, dec=2,
                 steps=[{"color": "green", "value": None}, {"color": "orange", "value": 0.7}, {"color": "red", "value": 0.9}],
                 desc="load1 / число ядер: > 0.9 — нода упирается в CPU"),
        bargauge("🧠 Память свободно (панель)", "remnawave_node_memory_free_bytes / remnawave_node_memory_total_bytes * 100", pos(16, y, 8, 8),
                 steps=[{"color": "red", "value": None}, {"color": "orange", "value": 12}, {"color": "green", "value": 25}]),
    ]
    y += 8
    panels += [
        timeseries("🖥️ CPU, % (агент node-exporter)", [q('100 - avg by (node) (rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100', "{{node}}")],
                   pos(0, y, 8, 8), unit="percent", dec=0, max_=100, desc="Есть только у серверов с установленным агентом (scripts/install-node-exporter.sh)"),
        bargauge("💽 Диск /, свободно (агент)", 'node_filesystem_avail_bytes{mountpoint="/",fstype!~"tmpfs|overlay"} / node_filesystem_size_bytes{mountpoint="/",fstype!~"tmpfs|overlay"} * 100',
                 pos(8, y, 8, 8), steps=[{"color": "red", "value": None}, {"color": "orange", "value": 10}, {"color": "green", "value": 20}]),
        bargauge("🧷 conntrack, % таблицы (агент)", "node_nf_conntrack_entries / node_nf_conntrack_entries_limit * 100", pos(16, y, 8, 8),
                 steps=[{"color": "green", "value": None}, {"color": "orange", "value": 60}, {"color": "red", "value": 80}],
                 desc="При 100% ядро отбрасывает новые соединения — для мостов с тысячами клиентов это главный тихий убийца"),
    ]
    y += 8
    ports = {"id": nid(), "type": "table", "title": "🔌 Порты нод с сервера мониторинга (blackbox)", "datasource": DS, "gridPos": pos(0, y, 12, 9),
             "description": "TCP-соединение к порту инбаунда каждой ноды. «закрыт» при живой ноде = блокировка/файрвол между серверами",
             "targets": [q('probe_success{job="blackbox-tcp"}', instant=True, table=True)],
             "transformations": [{"id": "organize", "options": {"excludeByName": {"Time": True, "__name__": True, "job": True, "role": True},
                                                                 "renameByName": {"node": "Нода", "instance": "Адрес:порт", "country": "Страна", "Value": "Состояние"},
                                                                 "indexByName": {"node": 0, "Value": 1, "instance": 2, "country": 3}}},
                                 {"id": "sortBy", "options": {"sort": [{"field": "Состояние", "desc": False}]}}],
             "fieldConfig": {"defaults": {"custom": {"align": "left"}}, "overrides": [
                 {"matcher": {"id": "byName", "options": "Состояние"}, "properties": [
                     {"id": "mappings", "value": [{"type": "value", "options": {"1": {"text": "● открыт", "color": "green", "index": 0},
                                                                                 "0": {"text": "● закрыт", "color": "red", "index": 1}}}]},
                     {"id": "custom.cellOptions", "value": {"type": "color-text"}}, {"id": "custom.width", "value": 110}]},
                 {"matcher": {"id": "byName", "options": "Страна"}, "properties": [country_mapping(), {"id": "custom.width", "value": 90}]}]},
             "options": {"cellHeight": "sm", "footer": {"show": False}}}
    daily = {"id": nid(), "type": "table", "title": "📦 Трафик интерфейса за 24 часа (как считает хостер)", "datasource": DS, "gridPos": pos(12, y, 12, 9),
             "description": "increase() по сырым счётчикам интерфейса из панели: вход и выход за последние сутки; перезагрузки учтены",
             "targets": [q("increase(remnawave_node_rx_bytes_total[24h])", instant=True, table=True, ref="A"),
                         q("increase(remnawave_node_tx_bytes_total[24h])", instant=True, table=True, ref="B")],
             "transformations": [{"id": "joinByField", "options": {"byField": "node", "mode": "outer"}},
                                 {"id": "organize", "options": {"excludeByName": {"Time 1": True, "Time 2": True, "job 1": True, "job 2": True, "instance 1": True, "instance 2": True,
                                                                                   "role 1": True, "role 2": True, "country 2": True},
                                                                 "renameByName": {"node": "Нода", "country 1": "Страна", "Value #A": "⬇️ за сутки", "Value #B": "⬆️ за сутки"},
                                                                 "indexByName": {"node": 0, "country 1": 1, "Value #A": 2, "Value #B": 3}}},
                                 {"id": "sortBy", "options": {"sort": [{"field": "⬇️ за сутки", "desc": True}]}}],
             "fieldConfig": {"defaults": {"custom": {"align": "left"}, "unit": "bytes", "decimals": 2}, "overrides": [
                 {"matcher": {"id": "byName", "options": "Страна"}, "properties": [country_mapping(), {"id": "custom.width", "value": 90}]}]},
             "options": {"cellHeight": "sm", "footer": {"show": False}}}
    panels += [ports, daily]
    return {"uid": "remnawave-fleet", "title": "Remnawave — флот", "tags": ["remnawave"], "timezone": "browser", "editable": True,
            "refresh": "30s", "time": {"from": "now-6h", "to": "now"}, "schemaVersion": 39, "version": 1, "panels": panels,
            "templating": {"list": []}, "annotations": {"list": []}, "links": [
                {"title": "Нода подробно", "type": "dashboards", "tags": ["remnawave-node"], "asDropdown": False, "icon": "external link", "includeVars": False, "keepTime": True}]}


def node_dashboard():
    _id[0] = 0
    var = {"name": "node", "label": "Нода", "type": "query", "datasource": DS, "query": {"query": "label_values(remnawave_node_connected, node)", "refId": "v"},
           "definition": "label_values(remnawave_node_connected, node)", "refresh": 2, "includeAll": False, "multi": False, "sort": 1,
           "current": {"selected": False, "text": "", "value": ""}, "options": []}
    s = '{node="$node"}'
    y = 0
    panels = [
        stat("Связь с панелью", "remnawave_node_connected" + s, pos(0, y, 4, 4), steps=[{"color": "red", "value": None}, {"color": "green", "value": 1}]),
        stat("Сессий", "remnawave_node_users_online" + s, pos(4, y, 4, 4), color="purple", spark=True),
        stat("Load на ядро", "remnawave_node_load1%s / remnawave_node_cpus%s" % (s, s), pos(8, y, 4, 4), dec=2,
             steps=[{"color": "green", "value": None}, {"color": "orange", "value": 0.7}, {"color": "red", "value": 0.9}]),
        stat("Аптайм xray", "remnawave_node_xray_uptime_seconds" + s, pos(12, y, 4, 4), unit="dtdurations", color="blue"),
        stat("Аптайм сервера", "remnawave_node_system_uptime_seconds" + s, pos(16, y, 4, 4), unit="dtdurations", color="blue"),
        stat("Лимит трафика, %", "remnawave_node_traffic_used_percent" + s, pos(20, y, 4, 4), unit="percent",
             steps=[{"color": "green", "value": None}, {"color": "orange", "value": 70}, {"color": "red", "value": 85}]),
    ]
    y += 4
    panels += [
        timeseries("Сессии", [q("remnawave_node_users_online" + s, "сессий")], pos(0, y, 12, 8)),
        timeseries("Полоса интерфейса (панель)", [q("remnawave_node_rx_bytes_per_second%s * 8" % s, "вход"), q("remnawave_node_tx_bytes_per_second%s * 8" % s, "выход", ref="B")],
                   pos(12, y, 12, 8), unit="bps", dec=1),
    ]
    y += 8
    panels += [
        timeseries("Load average (панель)", [q("remnawave_node_load1" + s, "1 мин"), q("remnawave_node_load5" + s, "5 мин", ref="B"), q("remnawave_node_load15" + s, "15 мин", ref="C"),
                                             q("remnawave_node_cpus" + s, "ядер", ref="D")], pos(0, y, 12, 8), dec=2),
        timeseries("Память (панель)", [q("remnawave_node_memory_total_bytes" + s, "всего"), q("remnawave_node_memory_free_bytes" + s, "свободно", ref="B")],
                   pos(12, y, 12, 8), unit="bytes"),
    ]
    y += 8
    panels += [
        timeseries("CPU, % (агент)", [q('100 - avg by (node) (rate(node_cpu_seconds_total{node="$node",mode="idle"}[5m])) * 100', "cpu %")], pos(0, y, 8, 8),
                   unit="percent", dec=0, max_=100, desc="Только если на ноде установлен node-exporter"),
        timeseries("conntrack (агент)", [q("node_nf_conntrack_entries" + s, "записей"), q("node_nf_conntrack_entries_limit" + s, "предел", ref="B")], pos(8, y, 8, 8)),
        timeseries("Диск /, свободно (агент)", [q('node_filesystem_avail_bytes{node="$node",mountpoint="/",fstype!~"tmpfs|overlay"}', "свободно")], pos(16, y, 8, 8), unit="bytes"),
    ]
    y += 8
    panels += [
        timeseries("Трафик интерфейса за сутки, скользящее (панель)", [q("increase(remnawave_node_rx_bytes_total%s[24h])" % s, "вход за 24 ч"),
                                                                        q("increase(remnawave_node_tx_bytes_total%s[24h])" % s, "выход за 24 ч", ref="B")],
                   pos(0, y, 12, 8), unit="bytes"),
        timeseries("Порт ноды с сервера мониторинга (blackbox)", [q('probe_success{job="blackbox-tcp",node="$node"}', "{{instance}}")], pos(12, y, 8, 8), max_=1,
                   desc="1 — порт открыт, 0 — соединение не установилось"),
        timeseries("Задержка TCP до ноды", [q('probe_duration_seconds{job="blackbox-tcp",node="$node"}', "{{instance}}")], pos(20, y, 4, 8), unit="s", dec=3),
    ]
    return {"uid": "remnawave-node", "title": "Remnawave — нода", "tags": ["remnawave", "remnawave-node"], "timezone": "browser", "editable": True,
            "refresh": "30s", "time": {"from": "now-6h", "to": "now"}, "schemaVersion": 39, "version": 1, "panels": panels,
            "templating": {"list": [var]}, "annotations": {"list": []}, "links": [
                {"title": "Флот", "type": "link", "url": "/d/remnawave-fleet", "icon": "dashboard", "keepTime": True}]}


def main():
    check = "--check" in sys.argv
    os.makedirs(OUT, exist_ok=True)
    rc = 0
    for name, build in (("remnawave-fleet.json", fleet_dashboard), ("remnawave-node.json", node_dashboard)):
        text = json.dumps(build(), ensure_ascii=False, indent=1) + "\n"
        path = os.path.join(OUT, name)
        if check:
            cur = open(path, encoding="utf-8").read() if os.path.exists(path) else ""
            if cur != text:
                print("расходится: %s — запустите python3 tools/build_dashboard.py" % path)
                rc = 1
            else:
                print("совпадает: %s" % name)
        else:
            open(path, "w", encoding="utf-8").write(text)
            print("записан: %s (%d панелей)" % (path, len(json.loads(text)["panels"])))
    return rc


if __name__ == "__main__":
    sys.exit(main())
