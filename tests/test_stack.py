#!/usr/bin/env python3
"""Дымовой тест поднятого стека (после `docker compose up -d` с tests/ci-override.yml и .env из CI):
Prometheus видит экспортёр и получает метрики заглушки, Grafana отдала дашборды, правила и точку доставки.
Порты берутся из stack/.env (GRAFANA_PORT, PROMETHEUS_PORT), пароль — GRAFANA_ADMIN_PASSWORD."""
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
env = {}
for line in open(os.path.join(ROOT, "stack", ".env"), encoding="utf-8"):
    if "=" in line and not line.startswith("#"):
        k, v = line.strip().split("=", 1)
        env[k] = v
GP, PP, PW = env.get("GRAFANA_PORT", "3000"), env.get("PROMETHEUS_PORT", "9090"), env.get("GRAFANA_ADMIN_PASSWORD", "")
AUTH = "Basic " + base64.b64encode(("admin:" + PW).encode()).decode()


def get(url, auth=False, timeout=5):
    h = {"Authorization": AUTH} if auth else {}
    with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=timeout) as r:
        return json.loads(r.read().decode())


def wait(fn, what, tries=90):
    for _ in range(tries):
        try:
            v = fn()
            if v:
                return v
        except Exception:  # noqa: BLE001
            pass
        time.sleep(2)
    raise SystemExit("не дождался: " + what)


fails = []


def check(cond, msg):
    print("  " + ("✅ " if cond else "❌ ") + msg)
    if not cond:
        fails.append(msg)


targets = wait(lambda: [t for t in get("http://127.0.0.1:%s/api/v1/targets" % PP)["data"]["activeTargets"]
                        if t["labels"].get("job") == "remnawave" and t["health"] == "up"], "экспортёр в Prometheus")
check(len(targets) == 1, "Prometheus опрашивает экспортёр")
res = wait(lambda: get("http://127.0.0.1:%s/api/v1/query?%s" % (PP, urllib.parse.urlencode({"query": "remnawave_users_total"})))["data"]["result"], "метрики заглушки")
check(res and res[0]["value"][1] == "2088", "remnawave_users_total = 2088 (данные заглушки дошли)")
res = get("http://127.0.0.1:%s/api/v1/query?%s" % (PP, urllib.parse.urlencode({"query": 'remnawave_node_connected{node="US-1"}'})))["data"]["result"]
check(res and res[0]["value"][1] == "0", "US-1 отвалилась (по заглушке)")
up = get("http://127.0.0.1:%s/api/v1/query?%s" % (PP, urllib.parse.urlencode({"query": 'up{job="node"}'})))["data"]["result"]
check(any(r["value"][1] == "1" for r in up), "node-exporter сервера мониторинга отвечает")
wait(lambda: get("http://127.0.0.1:%s/api/health" % GP)["database"] == "ok", "Grafana")
dash = wait(lambda: get("http://127.0.0.1:%s/api/search?type=dash-db" % GP, auth=True), "дашборды")
check({d["uid"] for d in dash} >= {"remnawave-fleet", "remnawave-node"}, "дашборды флот и нода провизионированы")
rules = wait(lambda: get("http://127.0.0.1:%s/api/v1/provisioning/alert-rules" % GP, auth=True), "правила")
check(len(rules) == 11, "правил тревог: %d" % len(rules))
check(all("$labels" in r["annotations"].get("summary", "") or r["uid"] == "rw-exporter-down" for r in rules), "в аннотациях остались шаблоны $labels (не раскрыты как переменные окружения)")
cps = get("http://127.0.0.1:%s/api/v1/provisioning/contact-points" % GP, auth=True)
tg = next((c for c in cps if c["name"] == "telegram"), None)
check(tg is not None and str(tg["settings"].get("chatid")) == env.get("TELEGRAM_CHAT_ID"), "точка доставки telegram с chat_id из .env")
pol = get("http://127.0.0.1:%s/api/v1/provisioning/policies" % GP, auth=True)
check(pol.get("receiver") == "telegram", "политика доставки → telegram")
ds = get("http://127.0.0.1:%s/api/datasources/uid/prometheus" % GP, auth=True)
check(ds.get("type") == "prometheus", "datasource uid=prometheus")
# правила реально вычисляются: через минуту у rw-node-down есть инстанс US-1
def evaluated():
    groups = get("http://127.0.0.1:%s/api/prometheus/grafana/api/v1/rules" % GP, auth=True)["data"]["groups"]
    for g in groups:
        for r in g["rules"]:
            if "отвалилась" in r["name"] and any(a["labels"].get("node") == "US-1" for a in r.get("alerts") or []):
                return True
    return False
check(wait(evaluated, "вычисление правила rw-node-down", tries=60), "правило «нода отвалилась» вычислилось для US-1")
if fails:
    print("ПРОВАЛЕНО:", fails)
    sys.exit(1)
print("стек: все проверки прошли")
