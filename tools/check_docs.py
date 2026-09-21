#!/usr/bin/env python3
"""Сверка документации с кодом: каждый флаг, переменная, метрика, правило и скрипт из кода должны быть
описаны в docs/reference.md; ссылки в docs/ и README ведут на существующие файлы. Код выхода 1 при расхождении."""
import os
import re
import socket
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REF = open(os.path.join(ROOT, "docs", "reference.md"), encoding="utf-8").read()
problems = []


def need(what, name):
    if name not in REF:
        problems.append("%s: %s не описан в docs/reference.md" % (what, name))


# 1. флаги rwmon.py
src = open(os.path.join(ROOT, "scripts", "rwmon.py"), encoding="utf-8").read()
for flag in sorted(set(re.findall(r'add_argument\("(--[a-z-]+)"', src))):
    need("флаг remnawave-monitoring", "`" + flag)
for cmd in re.findall(r'sub\.add_parser\("([a-z-]+)"', src):
    need("команда", "### `%s`" % cmd)

# 2. ключи .env.example
for key in re.findall(r"^([A-Z_]+)=", open(os.path.join(ROOT, "stack", ".env.example"), encoding="utf-8").read(), re.M):
    need("переменная .env", "`%s`" % key)

# 3. переменные экспортёра
exp = open(os.path.join(ROOT, "exporter", "rw_exporter.py"), encoding="utf-8").read()
for key in sorted(set(re.findall(r'env\("([A-Z_]+)"', exp))):
    need("переменная экспортёра", "`%s`" % key)

# 4. метрики (живой прогон против заглушки)
def free():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p
pp, ep = free(), free()
panel = subprocess.Popen([sys.executable, os.path.join(ROOT, "tests", "fake_panel.py"), "--listen", "127.0.0.1:%d" % pp, "--token", "t"], stdout=subprocess.DEVNULL)
e = subprocess.Popen([sys.executable, os.path.join(ROOT, "exporter", "rw_exporter.py")], stdout=subprocess.DEVNULL,
                     env=dict(os.environ, PANEL_URL="http://127.0.0.1:%d" % pp, PANEL_TOKEN="t", SCRAPE_SECONDS="5", LISTEN="127.0.0.1:%d" % ep))
text = ""
for _ in range(60):
    try:
        text = urllib.request.urlopen("http://127.0.0.1:%d/metrics" % ep, timeout=2).read().decode()
        if "remnawave_users_total" in text:
            break
    except Exception:  # noqa: BLE001
        pass
    time.sleep(0.2)
e.terminate(); panel.terminate()
metrics = re.findall(r"^# HELP (\S+)", text, re.M)
if len(metrics) < 30:
    problems.append("экспортёр отдал только %d метрик — заглушка не поднялась?" % len(metrics))
for m in metrics:
    need("метрика", "`%s`" % m)

# 5. правила тревог
rules = open(os.path.join(ROOT, "stack", "grafana", "provisioning", "alerting", "rules.yml"), encoding="utf-8").read()
for uid in re.findall(r"^\s+- uid: (\S+)", rules, re.M):
    need("правило", "`%s`" % uid)

# 6. ключи backup.env из install-backup.sh
ib = open(os.path.join(ROOT, "backup", "install-backup.sh"), encoding="utf-8").read()
block = ib[ib.index('cat > "$CONF" <<EOF'):ib.index("\nEOF", ib.index('cat > "$CONF" <<EOF'))]
for key in re.findall(r"^([A-Z_]+)=", block, re.M):
    need("ключ backup.env", "`%s`" % key)

# 7. скрипты
for d in ("scripts", "backup"):
    for f in sorted(os.listdir(os.path.join(ROOT, d))):
        if f.endswith((".sh", ".py")) and f not in ("common.sh",):
            need("скрипт", f)

# 8. флаги install-node-exporter.sh и uninstall.sh
for f, pat in (("install-node-exporter.sh", r"^\s+(--[a-z-]+)\)"), ("rollout-node-exporter.sh", r"(-[kpj]|--allow-from|--no-firewall)\)")):
    body = open(os.path.join(ROOT, "scripts", f), encoding="utf-8").read()
    for flag in sorted(set(re.findall(pat, body, re.M))):
        need("флаг " + f, "`%s" % flag)
for flag in ("--keep-data", "--data", "--all"):
    if flag not in open(os.path.join(ROOT, "scripts", "uninstall.sh"), encoding="utf-8").read():
        problems.append("uninstall.sh: нет флага %s" % flag)
    need("флаг uninstall.sh", "`%s`" % flag)

# 9. ссылки на файлы в README и docs
for f in ["README.md", "README.en.md"] + [os.path.join("docs", x) for x in os.listdir(os.path.join(ROOT, "docs")) if x.endswith(".md")]:
    body = open(os.path.join(ROOT, f), encoding="utf-8").read()
    for link in re.findall(r"\]\(([^)#\s]+)(?:#[^)]*)?\)", body):
        if link.startswith(("http://", "https://")):
            continue
        target = os.path.normpath(os.path.join(ROOT, os.path.dirname(f), link))
        if not os.path.exists(target):
            problems.append("%s: битая ссылка %s" % (f, link))

if problems:
    print("\n".join("❌ " + p for p in problems))
    sys.exit(1)
print("документация сходится с кодом: флаги, переменные, %d метрик, правила, скрипты, ссылки" % len(metrics))
