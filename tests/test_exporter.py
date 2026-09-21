#!/usr/bin/env python3
"""Проверка экспортёра против заглушки панели: метрики есть и правильные, ошибка панели видна,
/healthz отражает состояние. Запуск: python3 tests/test_exporter.py (нужен только python3)."""
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def wait_http(url, want=200, tries=50):
    for _ in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status == want:
                    return r.read().decode()
        except urllib.error.HTTPError as e:
            if e.code == want:
                return e.read().decode()
        except Exception:
            pass
        time.sleep(0.2)
    raise SystemExit("нет ответа %s от %s" % (want, url))


def metric(text, name, **labels):
    """Значение метрики с подмножеством меток; None если нет."""
    for line in text.splitlines():
        if not line.startswith(name + "{") and not line.startswith(name + " "):
            continue
        m = re.match(r"^(\S+?)(\{(.*)\})? (\S+)$", line)
        if not m:
            continue
        lbls = dict(re.findall(r'(\w+)="((?:[^"\\]|\\.)*)"', m.group(3) or ""))
        if all(lbls.get(k) == v for k, v in labels.items()):
            return float(m.group(4))
    return None


def main():
    pp, ep = free_port(), free_port()
    panel = subprocess.Popen([PY, os.path.join(ROOT, "tests", "fake_panel.py"), "--listen", "127.0.0.1:%d" % pp, "--token", "t0k", "--down", "US-1"])
    env = dict(os.environ, PANEL_URL="http://127.0.0.1:%d" % pp, PANEL_TOKEN="t0k", SCRAPE_SECONDS="5", LISTEN="127.0.0.1:%d" % ep, BRIDGE_COUNTRIES="")
    exp = subprocess.Popen([PY, os.path.join(ROOT, "exporter", "rw_exporter.py")], env=env)
    failures = []
    try:
        base = "http://127.0.0.1:%d" % ep
        wait_http(base + "/healthz")
        text = wait_http(base + "/metrics")

        def check(cond, msg):
            (print("  ✅", msg) if cond else failures.append(msg) or print("  ❌", msg))

        check(metric(text, "remnawave_exporter_up") == 1, "exporter_up = 1")
        check(metric(text, "remnawave_users_total") == 2088, "users_total из system/stats")
        check(metric(text, "remnawave_users_by_status", status="ACTIVE") == 610, "users_by_status{ACTIVE}")
        check(metric(text, "remnawave_nodes_total") == 6 and metric(text, "remnawave_nodes_connected") == 5, "нод 6, на связи 5")
        check(metric(text, "remnawave_node_connected", node="US-1") == 0, "US-1 отвалилась → connected 0")
        check(metric(text, "remnawave_node_connected", node="FI-1", role="node", country="FI") == 1, "FI-1 на связи, role=node")
        check(metric(text, "remnawave_node_users_online", node="RF-1", role="bridge") == 140, "RF-1 по тегу → role=bridge, онлайн 140")
        check(metric(text, "remnawave_node_traffic_used_percent", node="RF-1") == 55.0, "процент лимита RF-1 = 55")
        check(metric(text, "remnawave_node_traffic_used_percent", node="FI-1") == 0, "без лимита → процент 0")
        check(abs(metric(text, "remnawave_node_rx_bytes_per_second", node="FI-1") - 220e6 / 8) < 1, "rx bytes/s FI-1")
        check(metric(text, "remnawave_node_rx_bytes_total", node="FI-1") > 12e12, "счётчик интерфейса rx_bytes_total")
        check(metric(text, "remnawave_node_load1", node="FI-1") is not None, "load1 есть")
        check(metric(text, "remnawave_node_info", node="FI-1", xray_version="26.6.2") == 1, "node_info с версией xray")
        check("# TYPE remnawave_node_rx_bytes_total counter" in text, "TYPE counter у счётчика")
        check("# HELP remnawave_node_connected" in text, "HELP есть")
        bad = [l for l in text.splitlines() if l and not l.startswith("#") and not re.match(r"^[a-z_][a-z0-9_]*(\{[^}]*\})? -?[0-9.e+]+$", l)]
        check(not bad, "все строки в формате Prometheus (%s)" % (bad[:2] if bad else "ок"))
        # ошибка панели: заглушка выключена → exporter_up 0, healthz 503, старые метрики не отдаются как живые
        panel.terminate(); panel.wait()
        time.sleep(7)
        text2 = wait_http(base + "/metrics")
        check(metric(text2, "remnawave_exporter_up") == 0, "панель недоступна → exporter_up 0")
        check(metric(text2, "remnawave_exporter_errors_total", ) >= 1, "errors_total вырос")
        check(metric(text2, "remnawave_users_total") is None, "старые значения при ошибке не отдаются")
        rc = None
        try:
            urllib.request.urlopen(base + "/healthz", timeout=2)
        except urllib.error.HTTPError as e:
            rc = e.code
        check(rc == 503, "/healthz → 503 при ошибке панели")
    finally:
        exp.terminate(); exp.wait()
        if panel.poll() is None:
            panel.terminate(); panel.wait()
    # неверный токен
    pp2, ep2 = free_port(), free_port()
    panel = subprocess.Popen([PY, os.path.join(ROOT, "tests", "fake_panel.py"), "--listen", "127.0.0.1:%d" % pp2, "--token", "right"])
    env = dict(os.environ, PANEL_URL="http://127.0.0.1:%d" % pp2, PANEL_TOKEN="wrong", SCRAPE_SECONDS="5", LISTEN="127.0.0.1:%d" % ep2)
    exp = subprocess.Popen([PY, os.path.join(ROOT, "exporter", "rw_exporter.py")], env=env, stderr=subprocess.PIPE)
    try:
        text = ""
        for _ in range(60):  # первый опрос может застать заглушку ещё не поднятой — ждём именно 401
            text = wait_http("http://127.0.0.1:%d/healthz" % ep2, want=503)
            if "401" in text:
                break
            time.sleep(0.5)
        ok = "401" in text
        print("  ✅" if ok else "  ❌", "неверный токен → healthz 503 с текстом ошибки (%s)" % text.strip()[:60])
        if not ok:
            failures.append("неверный токен")
    finally:
        exp.terminate(); exp.wait(); panel.terminate(); panel.wait()
    # без переменных — код 2
    rc = subprocess.run([PY, os.path.join(ROOT, "exporter", "rw_exporter.py")], env={k: v for k, v in os.environ.items() if not k.startswith("PANEL_")}, capture_output=True).returncode
    print("  ✅" if rc == 2 else "  ❌", "без PANEL_URL/PANEL_TOKEN → exit 2")
    if rc != 2:
        failures.append("exit 2")
    if failures:
        print("ПРОВАЛЕНО:", failures)
        sys.exit(1)
    print("экспортёр: все проверки прошли")


if __name__ == "__main__":
    main()
