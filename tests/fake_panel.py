#!/usr/bin/env python3
"""Заглушка панели Remnawave для тестов и демо: отвечает на GET /api/system/stats и /api/nodes
так же, как настоящая панель (форма ответа снята с Remnawave 2.x), с выдуманным флотом.

  python3 tests/fake_panel.py --listen 127.0.0.1:8099 --token demo [--drift] [--down NL-1]

--drift  — цифры плавно «дышат» (онлайн, скорость), чтобы на графиках было что смотреть;
--down   — имя ноды, которую заглушка показывает отвалившейся.
Адреса нод — из документационных диапазонов (RFC 5737), ни один не настоящий.
"""
import argparse
import json
import math
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TB = 10 ** 12
FLEET = [
    # имя, адрес, страна, теги, ядер, ОЗУ ГБ, лимит ТБ, базовый онлайн, базовая скорость Мбит/с
    ("RF-1", "203.0.113.10", "RU", ["bridge"], 2, 4, 32, 140, 300),
    ("RF-2", "203.0.113.11", "RU", ["bridge"], 2, 4, 32, 120, 260),
    ("FI-1", "198.51.100.20", "FI", [], 4, 8, 0, 90, 220),
    ("NL-1", "198.51.100.21", "NL", [], 2, 4, 0, 60, 150),
    ("DE-1", "198.51.100.22", "DE", [], 2, 2, 0, 35, 90),
    ("US-1", "198.51.100.23", "US", [], 1, 1, 0, 12, 40),
]


def build(drift, down, t0):
    t = time.time() - t0
    wave = (math.sin(t / 60.0) * 0.15 + 1.0) if drift else 1.0
    nodes = []
    sessions = 0
    for i, (name, addr, cc, tags, cpus, ram, lim, base_on, base_mbit) in enumerate(FLEET):
        is_down = name == down
        online = 0 if is_down else int(base_on * wave * (1 + 0.05 * math.sin(t / 37.0 + i)))
        mbit = 0 if is_down else base_mbit * wave
        sessions += online
        used = (0.55 + i * 0.07) * (lim * TB if lim else 5 * TB)
        nodes.append({
            "uuid": "00000000-0000-4000-8000-%012d" % (i + 1), "name": name, "address": addr, "port": 3000,
            "isConnected": not is_down, "isConnecting": False, "isDisabled": False,
            "lastStatusChange": "2026-01-01T00:00:00.000Z", "lastStatusMessage": None,
            "trafficResetDay": 1, "isTrafficTrackingActive": bool(lim), "trafficLimitBytes": lim * TB,
            "trafficUsedBytes": int(used), "notifyPercent": 80 if lim else 0, "countryCode": cc, "tags": tags,
            "configProfile": {"activeConfigProfileUuid": "11111111-0000-4000-8000-000000000001",
                              "activeInbounds": [{"uuid": "22222222-0000-4000-8000-%012d" % (i + 1), "tag": name + "-VLESS",
                                                  "type": "vless", "network": "tcp", "security": "reality", "port": 2053}]},
            "xrayUptime": 0 if is_down else int(86400 * 3 + t), "usersOnline": online,
            "system": {"info": {"arch": "x64", "cpus": cpus, "cpuModel": "Example CPU", "memoryTotal": ram * 1024 ** 3,
                                "hostname": "node", "platform": "linux", "release": "6.8.0", "type": "Linux"},
                       "stats": {"memoryFree": int(ram * 1024 ** 3 * 0.6), "memoryUsed": int(ram * 1024 ** 3 * 0.4),
                                 "uptime": 86400 * 30 + t, "loadAvg": [round(0.3 * cpus * wave, 2), round(0.25 * cpus, 2), round(0.2 * cpus, 2)],
                                 "interface": {"interface": "eth0", "rxBytesPerSec": mbit * 1e6 / 8, "txBytesPerSec": mbit * 1e6 / 8 * 0.95,
                                               "rxTotal": int(12 * TB + t * mbit * 1e6 / 8), "txTotal": int(11 * TB + t * mbit * 1e6 / 8 * 0.95)}}},
            "versions": {"xray": "26.6.2", "node": "2.8.0"},
        })
    stats = {"cpu": {"cores": 2}, "memory": {"total": 4 * 1024 ** 3, "free": int(2.1 * 1024 ** 3), "used": int(1.9 * 1024 ** 3)},
             "uptime": 86400 * 12 + t, "timestamp": int(time.time() * 1000),
             "users": {"statusCounts": {"ACTIVE": 610, "DISABLED": 25, "LIMITED": 3, "EXPIRED": 1450}, "totalUsers": 2088},
             "onlineStats": {"onlineNow": int(sessions * 0.9), "lastDay": 480, "lastWeek": 590, "neverOnline": 700},
             "nodes": {"totalOnline": sessions, "totalBytesLifetime": str(250 * TB)}}
    return stats, nodes


def make_handler(token, drift, down):
    t0 = time.time()

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.headers.get("Authorization") != "Bearer " + token:
                return self._send(401, {"message": "Unauthorized"})
            stats, nodes = build(drift, down, t0)
            path = self.path.split("?", 1)[0].rstrip("/")
            if path == "/api/system/stats":
                return self._send(200, {"response": stats})
            if path == "/api/nodes":
                return self._send(200, {"response": nodes})
            return self._send(404, {"message": "Not Found"})

        def _send(self, code, obj):
            b = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def log_message(self, *a):
            pass

    return H


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--listen", default="127.0.0.1:8099")
    ap.add_argument("--token", default="demo")
    ap.add_argument("--drift", action="store_true")
    ap.add_argument("--down", default="")
    a = ap.parse_args()
    host, _, port = a.listen.rpartition(":")
    srv = ThreadingHTTPServer((host or "0.0.0.0", int(port)), make_handler(a.token, a.drift, a.down))
    print("заглушка панели: http://%s/api (токен %s, нод %d)" % (a.listen, a.token, len(FLEET)), flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
