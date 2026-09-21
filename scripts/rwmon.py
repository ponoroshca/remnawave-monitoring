#!/usr/bin/env python3
"""remnawave-monitoring — мастер настройки, цели для Prometheus из панели, doctor, Uptime Kuma, Telegram.
Только стандартная библиотека Python 3.9+. Ставится как /usr/local/bin/remnawave-monitoring.

  remnawave-monitoring setup            мастер: панель → Grafana → Telegram → Kuma → запуск стека
  remnawave-monitoring targets          цели Prometheus (node-exporter, порты, HTTPS) из списка нод панели
  remnawave-monitoring doctor           чек-лист «почему не работает»
  remnawave-monitoring status           что видит мониторинг прямо сейчас
  remnawave-monitoring kuma-sql         SQL с мониторами Uptime Kuma из нод панели (--apply — залить)
  remnawave-monitoring telegram-test    пробное сообщение в Telegram
"""
import argparse
import base64
import getpass
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

VERSION = "1.0.0"
DEFAULT_DIR = "/opt/remnawave-monitoring"
ENV_KEYS_SECRET = ("PANEL_TOKEN", "GRAFANA_ADMIN_PASSWORD", "TELEGRAM_BOT_TOKEN")


# ───────────────────────── .env ─────────────────────────

def read_env(path):
    vals = {}
    if not os.path.exists(path):
        return vals
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        vals[k.strip()] = v
    return vals


def write_env(path, vals, example):
    """Пишем .env по порядку и с комментариями из .env.example; лишние ключи — в конец. Права 600."""
    out, seen = [], set()
    for line in open(example, encoding="utf-8"):
        raw = line.rstrip("\n")
        if raw and not raw.startswith("#") and "=" in raw:
            k = raw.split("=", 1)[0].strip()
            seen.add(k)
            out.append("%s=%s" % (k, vals.get(k, raw.split("=", 1)[1])))
        else:
            out.append(raw)
    extra = [k for k in vals if k not in seen]
    if extra:
        out.append("")
        out += ["%s=%s" % (k, vals[k]) for k in extra]
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("\n".join(out).rstrip("\n") + "\n")
    os.replace(tmp, path)
    os.chmod(path, 0o600)


def stack_dir(a):
    return os.path.join(a.dir, "stack")


def env_file(a):
    return os.path.join(stack_dir(a), ".env")


# ───────────────────────── панель ─────────────────────────

class Panel:
    def __init__(self, url, token, insecure=False):
        self.url = url.rstrip("/")
        self.token = token
        import ssl
        self.ctx = ssl.create_default_context()
        if insecure:
            self.ctx.check_hostname = False
            self.ctx.verify_mode = ssl.CERT_NONE

    def get(self, path):
        req = urllib.request.Request(self.url + "/api/" + path.lstrip("/"),
                                     headers={"Authorization": "Bearer " + self.token, "User-Agent": "remnawave-monitoring/" + VERSION})
        with urllib.request.urlopen(req, timeout=20, context=self.ctx) as r:
            return json.load(r)["response"]

    def nodes(self):
        return self.get("nodes")

    def stats(self):
        return self.get("system/stats")


def panel_check(url, token, insecure=False):
    """(ok, сообщение, ноды)."""
    if not url.startswith(("http://", "https://")):
        return False, "адрес должен начинаться с https:// (или http://)", []
    try:
        p = Panel(url, token, insecure)
        nodes = p.nodes()
        st = p.stats()
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return False, "токен не принят (HTTP %d) — скопируйте его заново целиком" % e.code, []
        return False, "панель ответила HTTP %d на %s" % (e.code, e.geturl()), []
    except Exception as e:  # noqa: BLE001
        return False, "панель не ответила: %s" % str(e)[:120], []
    return True, "панель отвечает: нод %d, пользователей %s, онлайн %s" % (
        len(nodes), (st.get("users") or {}).get("totalUsers", "?"), (st.get("onlineStats") or {}).get("onlineNow", "?")), nodes


def node_role(n, env):
    """Та же логика, что в экспортёре: тег → регулярка по имени → страна."""
    tag = (env.get("BRIDGE_TAG") or "bridge").strip().lower()
    tags = [str(t).strip().lower() for t in (n.get("tags") or [])]
    if tag and tag in tags:
        return "bridge"
    rx = env.get("BRIDGE_REGEX", "(?i)bridge")
    try:
        if rx and re.search(rx, n.get("name") or ""):
            return "bridge"
    except re.error:
        pass
    countries = {c.strip().upper() for c in (env.get("BRIDGE_COUNTRIES") or "").split(",") if c.strip()}
    if (n.get("countryCode") or "").upper() in countries:
        return "bridge"
    return "node"


def node_ports(n):
    ports = []
    for ib in ((n.get("configProfile") or {}).get("activeInbounds") or []):
        p = ib.get("port")
        if isinstance(p, int) and p not in ports:
            ports.append(p)
    return ports


# ───────────────────────── Telegram ─────────────────────────

def telegram_api(token, method, params=None, timeout=25, proxy=None):
    data = urllib.parse.urlencode(params or {}).encode() if params else None
    last = None
    for p in ([proxy, None] if proxy else [None, None]):
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({"https": p} if p else {}))
            raw = opener.open(urllib.request.Request("https://api.telegram.org/bot%s/%s" % (token, method), data=data), timeout=timeout).read()
            return json.loads(raw.decode()), None
        except urllib.error.HTTPError as e:
            try:
                body = json.loads(e.read().decode())
            except Exception:  # noqa: BLE001
                body = {}
            return None, "%s %s" % (e.code, body.get("description") or e.reason)
        except Exception as e:  # noqa: BLE001
            last = e
    return None, str(last)[:100]


def telegram_send(token, chat_id, text, proxy=None):
    for i in range(4):
        r, err = telegram_api(token, "sendMessage", {"chat_id": chat_id, "text": text, "disable_web_page_preview": "true"}, proxy=proxy)
        if r:
            return True, ""
        if err and err.startswith("400"):
            return False, err
        time.sleep(2 + i)
    return False, err or "?"


def telegram_detect_chat(token, wait_s=90, proxy=None):
    me, err = telegram_api(token, "getMe", proxy=proxy)
    if not me:
        return None, "токен не принят Telegram (%s) — проверьте, что скопировали его целиком у @BotFather" % err
    username = me["result"].get("username")
    print("  бот найден: @%s. Откройте https://t.me/%s и нажмите Start (или напишите ему что угодно)." % (username, username))
    print("  жду сообщение до %d с…" % wait_s)
    t0, offset = time.time(), None
    while time.time() - t0 < wait_s:
        params = {"timeout": 15, "allowed_updates": json.dumps(["message"])}
        if offset:
            params["offset"] = offset
        upd, err = telegram_api(token, "getUpdates", params, timeout=30, proxy=proxy)
        if not upd:
            if err and err.startswith("409"):
                return None, ("этот бот уже используется другой программой (getUpdates занят или включён webhook). "
                              "Для тревог заведите ОТДЕЛЬНОГО бота у @BotFather или введите chat_id руками")
            time.sleep(2)
            continue
        for u in upd.get("result", []):
            offset = u["update_id"] + 1
            chat = (u.get("message") or {}).get("chat") or {}
            if chat.get("id"):
                who = chat.get("title") or " ".join(x for x in (chat.get("first_name"), chat.get("last_name")) if x) or chat.get("username") or "?"
                return chat["id"], who
    return None, "за отведённое время сообщение не пришло"


# ───────────────────────── docker / http ─────────────────────────

def sh(cmd, cwd=None, timeout=600, inp=None):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, input=inp)


def compose(a, *args, timeout=900):
    return sh(["docker", "compose"] + list(args), cwd=stack_dir(a), timeout=timeout)


def docker_ok():
    if not shutil.which("docker"):
        return False, "docker не установлен"
    r = sh(["docker", "info"], timeout=30)
    if r.returncode != 0:
        return False, "docker не отвечает (служба не запущена или нет прав): %s" % (r.stderr.strip().splitlines() or ["?"])[-1][:100]
    r = sh(["docker", "compose", "version"], timeout=30)
    if r.returncode != 0:
        return False, "нет docker compose v2 (плагин docker-compose-v2 или установка с get.docker.com)"
    return True, r.stdout.strip()


def http_get(url, timeout=8, auth=None, headers=None):
    """(код, тело) — HTTP-ошибки возвращаются кодом, сетевые — (0, текст)."""
    h = dict(headers or {})
    if auth:
        h["Authorization"] = "Basic " + base64.b64encode(("%s:%s" % auth).encode()).decode()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=timeout) as r:
            return r.status, r.read().decode(errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")
    except Exception as e:  # noqa: BLE001
        return 0, str(e)[:120]


def http_post(url, data=b"", timeout=8, auth=None):
    h = {}
    if auth:
        h["Authorization"] = "Basic " + base64.b64encode(("%s:%s" % auth).encode()).decode()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=h, method="POST"), timeout=timeout) as r:
            return r.status, r.read().decode(errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")
    except Exception as e:  # noqa: BLE001
        return 0, str(e)[:120]


def container_state(name):
    r = sh(["docker", "inspect", "-f", "{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{end}}", name], timeout=30)
    return r.stdout.strip() if r.returncode == 0 else "нет"


def my_ip():
    """Адрес этого сервера: сначала по маршруту наружу, иначе hostname -I."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("1.1.1.1", 53))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:  # noqa: BLE001
        r = sh(["hostname", "-I"], timeout=10)
        return (r.stdout.split() or ["<IP сервера>"])[0]


def is_private(ip):
    return bool(re.match(r"^(10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|127\.)", ip))


# ───────────────────────── targets ─────────────────────────

def yaml_targets(entries):
    """entries: [(target, labels)] → YAML-текст file_sd (JSON-кавычки — валидный YAML)."""
    if not entries:
        return "[]\n"
    out = []
    for target, labels in entries:
        out.append("- targets: [%s]" % json.dumps(target, ensure_ascii=False))
        out.append("  labels: {%s}" % ", ".join("%s: %s" % (k, json.dumps(v, ensure_ascii=False)) for k, v in labels.items()))
    return "\n".join(out) + "\n"


def build_targets(nodes, env, ne_port=9100, exclude=None, extra_http=(), sub_url="", panel_url="", no_blackbox=False, no_agents=False):
    ex = re.compile(exclude) if exclude else None
    agents, ports, https = [], [], []
    for n in nodes:
        name, addr = n.get("name") or "?", n.get("address") or ""
        if not addr or n.get("isDisabled") or (ex and ex.search(name)):
            continue
        lbl = {"node": name, "role": node_role(n, env), "country": (n.get("countryCode") or "").upper()}
        if not no_agents:
            agents.append(("%s:%d" % (addr, ne_port), lbl))
        if not no_blackbox:
            for p in node_ports(n):
                ports.append(("%s:%d" % (addr, p), lbl))
    if panel_url:
        https.append((panel_url, {"node": "panel", "check": "панель"}))
    if sub_url:
        https.append((sub_url, {"node": "subscription", "check": "страница подписки"}))
    for u in extra_http:
        https.append((u, {"node": urllib.parse.urlparse(u).hostname or u, "check": "http"}))
    return agents, ports, https


def prometheus_reload(env):
    port = env.get("PROMETHEUS_PORT") or "9090"
    code, _ = http_post("http://127.0.0.1:%s/-/reload" % port)
    return code == 200


def cmd_targets(a):
    env = read_env(env_file(a))
    if not env.get("PANEL_URL") or not env.get("PANEL_TOKEN"):
        print("в %s нет PANEL_URL/PANEL_TOKEN — сначала remnawave-monitoring setup" % env_file(a))
        return 2
    ok, msg, nodes = panel_check(env["PANEL_URL"], env["PANEL_TOKEN"], env.get("PANEL_INSECURE") == "1")
    if not ok:
        print("  ❌", msg)
        return 1
    print(" ", msg)
    if a.ssh_list:
        for n in nodes:
            if n.get("address") and not n.get("isDisabled"):
                print("%s %s" % (n["name"].replace(" ", "_"), n["address"]))
        return 0
    agents, ports, https = build_targets(nodes, env, a.node_exporter_port, a.exclude, a.http, a.sub_url or env.get("SUB_URL", ""),
                                         env["PANEL_URL"], a.no_blackbox, a.no_agents)
    tdir = os.path.join(stack_dir(a), "prometheus", "targets")
    os.makedirs(tdir, exist_ok=True)
    head = "# Сгенерировано remnawave-monitoring targets %s — можно править руками, файл перечитывается сам.\n" % time.strftime("%Y-%m-%d %H:%M")
    for fname, entries in (("nodes.yml", agents), ("blackbox.yml", ports), ("http.yml", https)):
        text = head + yaml_targets(entries)
        path = os.path.join(tdir, fname)
        if a.dry_run:
            print("── %s ──\n%s" % (fname, text.rstrip()))
        else:
            open(path, "w", encoding="utf-8").write(text)
    if a.sub_url and not a.dry_run:
        env["SUB_URL"] = a.sub_url
        write_env(env_file(a), env, os.path.join(stack_dir(a), ".env.example"))
    print("  node-exporter: %d целей (порт %d) · порты нод: %d · HTTPS: %d%s" % (
        len(agents), a.node_exporter_port, len(ports), len(https), " (не записано: --dry-run)" if a.dry_run else ""))
    for n in nodes:
        if n.get("isDisabled"):
            print("  пропущена (выключена в панели): %s" % n.get("name"))
    if not a.dry_run:
        print("  prometheus перечитал конфиг" if prometheus_reload(env) else "  (prometheus не запущен — цели подхватит при старте)")
        if agents:
            print("  агенты на нодах ставятся так (на каждой ноде):")
            print("    curl -fsSL https://raw.githubusercontent.com/ponoroshca/remnawave-monitoring/main/scripts/install-node-exporter.sh | sudo bash -s -- --allow-from %s" % my_ip())
    return 0


# ───────────────────────── doctor / status ─────────────────────────

def prom_targets(env):
    port = env.get("PROMETHEUS_PORT") or "9090"
    code, body = http_get("http://127.0.0.1:%s/api/v1/targets" % port)
    if code != 200:
        return None
    try:
        return json.loads(body)["data"]["activeTargets"]
    except Exception:  # noqa: BLE001
        return None


def prom_query(env, expr):
    port = env.get("PROMETHEUS_PORT") or "9090"
    code, body = http_get("http://127.0.0.1:%s/api/v1/query?%s" % (port, urllib.parse.urlencode({"query": expr})))
    if code != 200:
        return []
    try:
        return json.loads(body)["data"]["result"]
    except Exception:  # noqa: BLE001
        return []


def cmd_doctor(a):
    env = read_env(env_file(a))
    problems = 0

    def ok(msg, hint=""):
        print("  ✅", msg)

    def bad(msg, hint=""):
        nonlocal problems
        problems += 1
        print("  ❌", msg + ((" → " + hint) if hint else ""))

    print("── Файлы ──")
    if not os.path.exists(env_file(a)):
        bad("нет %s" % env_file(a), "remnawave-monitoring setup")
        return 1
    ok("конфиг %s (права %o)" % (env_file(a), os.stat(env_file(a)).st_mode & 0o777))
    if os.stat(env_file(a)).st_mode & 0o077:
        bad("права на .env шире 600", "chmod 600 " + env_file(a))
    for k in ("PANEL_URL", "PANEL_TOKEN", "GRAFANA_ADMIN_PASSWORD"):
        if not env.get(k):
            bad("в .env пусто %s" % k, "remnawave-monitoring setup")
    tg_file = os.path.join(stack_dir(a), "grafana", "provisioning", "alerting", "telegram.yml")
    if env.get("TELEGRAM_BOT_TOKEN") and env.get("TELEGRAM_CHAT_ID"):
        ok("Telegram настроен (chat_id %s)%s" % (env["TELEGRAM_CHAT_ID"], "" if os.path.exists(tg_file) else " — но нет telegram.yml"))
        if not os.path.exists(tg_file):
            bad("нет %s — Grafana не будет слать тревоги" % tg_file, "remnawave-monitoring setup (или скопируйте grafana/telegram.yml.template → grafana/provisioning/alerting/telegram.yml и docker compose restart grafana)")
    else:
        print("  ℹ️  Telegram не настроен — тревоги видны только в Grafana")
        if os.path.exists(tg_file):
            bad("есть telegram.yml без токена в .env — Grafana не стартует", "удалите файл или задайте TELEGRAM_BOT_TOKEN")
    print("── Панель ──")
    okp, msg, nodes = panel_check(env.get("PANEL_URL", ""), env.get("PANEL_TOKEN", ""), env.get("PANEL_INSECURE") == "1")
    (ok if okp else bad)(msg)
    if okp:
        bridges = [n["name"] for n in nodes if node_role(n, env) == "bridge"]
        print("  ℹ️  мосты (role=bridge): %s" % (", ".join(bridges) if bridges else "не определены — тег bridge / BRIDGE_REGEX / BRIDGE_COUNTRIES в .env"))
    print("── Docker ──")
    okd, msg = docker_ok()
    (ok if okd else bad)(msg)
    if not okd:
        return 1
    for c in ("rwmon-prometheus", "rwmon-exporter", "rwmon-grafana", "rwmon-node-exporter", "rwmon-blackbox", "rwmon-kuma"):
        st = container_state(c)
        (ok if st.startswith("running") and "unhealthy" not in st else bad)("%s: %s" % (c, st), "" if st.startswith("running") else "cd %s && docker compose up -d" % stack_dir(a))
    print("── Prometheus ──")
    ts = prom_targets(env)
    if ts is None:
        bad("Prometheus не отвечает на 127.0.0.1:%s" % (env.get("PROMETHEUS_PORT") or "9090"), "docker logs rwmon-prometheus")
    else:
        by_job = {}
        for t in ts:
            j = t["labels"].get("job", "?")
            by_job.setdefault(j, [0, 0, []])
            by_job[j][0] += 1
            if t.get("health") == "up":
                by_job[j][1] += 1
            else:
                why = (t.get("lastError") or ("ещё не опрашивалась — подождите минуту" if t.get("health") == "unknown" else "?"))[:80]
                by_job[j][2].append("%s (%s): %s" % (t["labels"].get("node") or t["labels"].get("instance"), t["labels"].get("instance"), why))
        for j, (n, up, down) in sorted(by_job.items()):
            (ok if up == n else bad)("job %s: %d из %d целей отвечают" % (j, up, n))
            for d in down[:10]:
                print("       ⚠️ ", d)
        if "node" in by_job and by_job["node"][0] <= 1:
            print("  ℹ️  агенты на нодах ещё не добавлены: remnawave-monitoring targets, затем install-node-exporter.sh на нодах")
        r = prom_query(env, "remnawave_exporter_up")
        if r:
            (ok if r[0]["value"][1] == "1" else bad)("экспортёр: последний опрос панели %s" % ("удался" if r[0]["value"][1] == "1" else "НЕ удался"), "docker logs rwmon-exporter")
        else:
            bad("в Prometheus нет метрик экспортёра", "docker logs rwmon-exporter; подождите минуту после старта")
    print("── Grafana ──")
    gport = env.get("GRAFANA_PORT") or "3000"
    code, body = http_get("http://127.0.0.1:%s/api/health" % gport)
    if code != 200:
        bad("Grafana не отвечает на порту %s" % gport, "docker logs rwmon-grafana")
    else:
        ok("Grafana отвечает (порт %s)" % gport)
        auth = ("admin", env.get("GRAFANA_ADMIN_PASSWORD", ""))
        code, body = http_get("http://127.0.0.1:%s/api/search?type=dash-db" % gport, auth=auth)
        if code == 401:
            bad("пароль admin из .env не подходит", "если меняли пароль в интерфейсе — впишите новый в .env")
        elif code == 200:
            titles = [d["title"] for d in json.loads(body)]
            (ok if any("Remnawave" in t for t in titles) else bad)("дашборды: %s" % (", ".join(titles) or "нет"))
            code, body = http_get("http://127.0.0.1:%s/api/v1/provisioning/alert-rules" % gport, auth=auth)
            n = len(json.loads(body)) if code == 200 else 0
            (ok if n else bad)("правил тревог: %d" % n, "docker logs rwmon-grafana | grep -i provision")
            code, body = http_get("http://127.0.0.1:%s/api/v1/provisioning/contact-points" % gport, auth=auth)
            cps = [c["name"] for c in json.loads(body)] if code == 200 else []
            if env.get("TELEGRAM_BOT_TOKEN"):
                (ok if "telegram" in cps else bad)("точка доставки telegram %s" % ("есть" if "telegram" in cps else "не создана"), "docker logs rwmon-grafana | grep -i alerting")
    print("── Uptime Kuma ──")
    kport = env.get("KUMA_PORT") or "3001"
    code, _ = http_get("http://127.0.0.1:%s/" % kport)
    if code == 200:
        r = sh(["docker", "exec", "rwmon-kuma", "sqlite3", "/app/data/kuma.db", "select count(*) from user; select count(*) from monitor;"], timeout=30)
        cnt = r.stdout.split() if r.returncode == 0 else []
        if len(cnt) == 2:
            if cnt[0] == "0":
                print("  ℹ️  Kuma отвечает, администратор ещё не создан — откройте http://%s:%s и заведите его" % (my_ip(), kport))
            else:
                ok("Kuma: мониторов %s" % cnt[1] + ("" if cnt[1] != "0" else " — remnawave-monitoring kuma-sql --apply"))
        else:
            ok("Kuma отвечает (порт %s)" % kport)
    else:
        bad("Kuma не отвечает на порту %s" % kport, "docker logs rwmon-kuma")
    print("── Сеть ──")
    r = sh(["ufw", "status"], timeout=10) if shutil.which("ufw") else None
    if r and r.returncode == 0 and "Status: active" in r.stdout:
        ok("ufw активен")
        for p, what in ((gport, "Grafana"), (kport, "Kuma")):
            if env.get("GRAFANA_BIND" if what == "Grafana" else "KUMA_BIND", "0.0.0.0") != "127.0.0.1" and not re.search(r"^%s(/tcp)?\s+ALLOW" % p, r.stdout, re.M):
                print("  ℹ️  порт %s (%s) в ufw не открыт — снаружи не откроется (это нормально, если заходите через ssh -L)" % (p, what))
    else:
        print("  ℹ️  ufw не активен: порты Grafana/Kuma открыты для всех, вход по паролю; Prometheus и экспортёр снаружи недоступны")
    print("\n%s" % ("всё в порядке" if not problems else "проблем: %d" % problems))
    return 1 if problems else 0


def cmd_status(a):
    env = read_env(env_file(a))
    ts = prom_targets(env)
    if ts is None:
        print("Prometheus не отвечает — remnawave-monitoring doctor")
        return 1
    one = lambda e: (prom_query(env, e) or [{"value": [0, "?"]}])[0]["value"][1]  # noqa: E731
    print("Онлайн: %s уникальных, %s сессий · пользователей %s (активных %s) · нод на связи %s из %s" % (
        one("remnawave_online_now"), one("remnawave_sessions_total"), one("remnawave_users_total"),
        one('remnawave_users_by_status{status="ACTIVE"}'), one("remnawave_nodes_connected"), one("remnawave_nodes_total")))
    rows = prom_query(env, "remnawave_node_users_online")
    load = {r["metric"]["node"]: float(r["value"][1]) for r in prom_query(env, "remnawave_node_load1 / remnawave_node_cpus")}
    rx = {r["metric"]["node"]: float(r["value"][1]) for r in prom_query(env, "remnawave_node_rx_bytes_per_second * 8")}
    conn = {r["metric"]["node"]: r["value"][1] for r in prom_query(env, "remnawave_node_connected")}
    for r in sorted(rows, key=lambda r: -float(r["value"][1])):
        n = r["metric"]["node"]
        print("  %-18s %-6s %-7s сессий %4s  load/ядро %.2f  вход %6.0f Мбит" % (
            n, r["metric"].get("country", ""), "●" if conn.get(n) == "1" else "○ ОТВАЛ", r["value"][1], load.get(n, 0), rx.get(n, 0) / 1e6))
    down = [t for t in ts if t.get("health") != "up"]
    print("Цели Prometheus: %d, не отвечают: %d%s" % (len(ts), len(down), (" — " + ", ".join(
        "%s/%s" % (t["labels"].get("job"), t["labels"].get("node") or t["labels"].get("instance")) for t in down[:8])) if down else ""))
    return 0


# ───────────────────────── Uptime Kuma ─────────────────────────

FLAGS = {"RU": "🇷🇺", "DE": "🇩🇪", "NL": "🇳🇱", "FI": "🇫🇮", "FR": "🇫🇷", "CH": "🇨🇭", "SE": "🇸🇪", "US": "🇺🇸", "PL": "🇵🇱", "ES": "🇪🇸",
         "BG": "🇧🇬", "GR": "🇬🇷", "LV": "🇱🇻", "CZ": "🇨🇿", "GB": "🇬🇧", "IT": "🇮🇹", "TR": "🇹🇷", "KZ": "🇰🇿", "AM": "🇦🇲", "GE": "🇬🇪",
         "AT": "🇦🇹", "EE": "🇪🇪", "LT": "🇱🇹", "RO": "🇷🇴", "HU": "🇭🇺", "JP": "🇯🇵", "SG": "🇸🇬", "CA": "🇨🇦", "UA": "🇺🇦", "MD": "🇲🇩"}


def sq(s):
    return "'" + str(s).replace("'", "''") + "'"


def kuma_sql(nodes, env, sub_url="", status_slug="status", title="Статус сети", with_telegram=True):
    """SQL для Uptime Kuma 1.x: мониторы портов по нодам панели + HTTPS панели/подписки, Telegram-уведомление
    на все мониторы, публичная страница статуса. Повторный запуск ничего не дублирует (проверка по имени)."""
    lines = ["BEGIN;"]

    def ins_port(name, host, port):
        lines.append("INSERT INTO monitor (name,type,hostname,port,interval,retry_interval,maxretries,timeout,user_id,active,accepted_statuscodes_json) "
                     "SELECT %s,'port',%s,%d,60,60,2,10,1,1,'[\"200-299\"]' WHERE NOT EXISTS (SELECT 1 FROM monitor WHERE name=%s);" % (sq(name), sq(host), port, sq(name)))

    def ins_http(name, url):
        lines.append("INSERT INTO monitor (name,type,url,interval,retry_interval,maxretries,timeout,user_id,active,accepted_statuscodes_json,ignore_tls) "
                     "SELECT %s,'http',%s,60,60,2,15,1,1,'[\"200-299\",\"300-399\",\"401\",\"403\",\"404\"]',0 WHERE NOT EXISTS (SELECT 1 FROM monitor WHERE name=%s);" % (sq(name), sq(url), sq(name)))

    for n in nodes:
        if not n.get("address") or n.get("isDisabled"):
            continue
        cc = (n.get("countryCode") or "").upper()
        for p in node_ports(n) or [443]:
            ins_port("%s %s · %d" % (FLAGS.get(cc, cc or "🌐"), n["name"], p), n["address"], p)
    if env.get("PANEL_URL"):
        ins_http("🖥️ Панель Remnawave", env["PANEL_URL"])
    if sub_url:
        ins_http("📄 Страница подписки", sub_url)
    if with_telegram and env.get("TELEGRAM_BOT_TOKEN") and env.get("TELEGRAM_CHAT_ID"):
        cfg = json.dumps({"name": "Telegram", "type": "telegram", "telegramBotToken": env["TELEGRAM_BOT_TOKEN"],
                          "telegramChatID": str(env["TELEGRAM_CHAT_ID"]), "isDefault": True, "applyExisting": True}, ensure_ascii=False)
        lines.append("INSERT INTO notification (name,active,user_id,is_default,config) SELECT 'Telegram',1,1,1,%s WHERE NOT EXISTS (SELECT 1 FROM notification WHERE name='Telegram');" % sq(cfg))
        lines.append("INSERT INTO monitor_notification (monitor_id, notification_id) SELECT m.id, (SELECT id FROM notification WHERE name='Telegram') FROM monitor m "
                     "WHERE NOT EXISTS (SELECT 1 FROM monitor_notification mn WHERE mn.monitor_id=m.id AND mn.notification_id=(SELECT id FROM notification WHERE name='Telegram'));")
    if status_slug:
        lines.append("INSERT INTO status_page (slug,title,description,icon,theme,published,search_engine_index,show_tags,modified_date) "
                     "SELECT %s,%s,'Живой статус серверов','/icon.svg','dark',1,0,0,DATETIME('now') WHERE NOT EXISTS (SELECT 1 FROM status_page WHERE slug=%s);" % (sq(status_slug), sq(title), sq(status_slug)))
        lines.append("INSERT INTO \"group\" (name,status_page_id,public,active,weight) SELECT 'Серверы',(SELECT id FROM status_page WHERE slug=%s),1,1,1 "
                     "WHERE NOT EXISTS (SELECT 1 FROM \"group\" WHERE status_page_id=(SELECT id FROM status_page WHERE slug=%s));" % (sq(status_slug), sq(status_slug)))
        lines.append("INSERT INTO monitor_group (monitor_id, group_id, weight, send_url) SELECT m.id, (SELECT id FROM \"group\" WHERE status_page_id=(SELECT id FROM status_page WHERE slug=%s) LIMIT 1), m.id, 0 FROM monitor m "
                     "WHERE NOT EXISTS (SELECT 1 FROM monitor_group mg WHERE mg.monitor_id=m.id);" % sq(status_slug))
    lines.append("COMMIT;")
    return "\n".join(lines) + "\n"


def cmd_kuma(a):
    env = read_env(env_file(a))
    if not env.get("PANEL_URL") or not env.get("PANEL_TOKEN"):
        print("в .env нет панели — сначала remnawave-monitoring setup")
        return 2
    ok, msg, nodes = panel_check(env["PANEL_URL"], env["PANEL_TOKEN"], env.get("PANEL_INSECURE") == "1")
    if not ok:
        print("  ❌", msg)
        return 1
    sql = kuma_sql(nodes, env, a.sub_url or env.get("SUB_URL", ""), "" if a.no_status_page else a.status_slug, a.title, not a.no_telegram)
    if not a.apply:
        sys.stdout.write(sql)
        return 0
    if not container_state("rwmon-kuma").startswith("running"):
        print("контейнер rwmon-kuma не запущен")
        return 1
    r = sh(["docker", "exec", "rwmon-kuma", "sqlite3", "/app/data/kuma.db", "select count(*) from user;"], timeout=30)
    if r.returncode != 0:
        print("не могу прочитать базу Kuma:", r.stderr.strip()[:200])
        return 1
    if r.stdout.strip() == "0":
        print("в Kuma ещё нет администратора: откройте http://%s:%s, создайте его и повторите" % (my_ip(), env.get("KUMA_PORT") or "3001"))
        return 1
    bak = "/app/data/kuma.db.bak-%s" % time.strftime("%Y%m%d-%H%M%S")
    r = sh(["docker", "exec", "rwmon-kuma", "sqlite3", "/app/data/kuma.db", ".backup %s" % bak], timeout=60)
    if r.returncode != 0:
        print("не удалось сделать копию базы Kuma:", r.stderr.strip()[:200])
        return 1
    print("  копия базы Kuma: %s (внутри контейнера)" % bak)
    r = sh(["docker", "exec", "-i", "rwmon-kuma", "sqlite3", "/app/data/kuma.db"], timeout=60, inp=sql)
    if r.returncode != 0:
        print("  ❌ SQL не прошёл:", r.stderr.strip()[:300])
        print("  база не изменена (транзакция откачена); копия:", bak)
        return 1
    r = sh(["docker", "exec", "rwmon-kuma", "sqlite3", "/app/data/kuma.db", "select count(*) from monitor;"], timeout=30)
    print("  мониторов в Kuma: %s" % r.stdout.strip())
    sh(["docker", "restart", "rwmon-kuma"], timeout=120)
    print("  Kuma перезапущена. Страница статуса: http://%s:%s/status/%s" % (my_ip(), env.get("KUMA_PORT") or "3001", a.status_slug))
    return 0


# ───────────────────────── setup ─────────────────────────

def ask(prompt, default="", secret=False, yes=False):
    if yes:
        return default
    p = "%s%s: " % (prompt, (" [%s]" % default) if default and not secret else "")
    try:
        v = getpass.getpass(p) if secret else input(p)
    except EOFError:
        return default
    return v.strip() or default


def ask_yn(prompt, default=True, yes=False):
    if yes:
        return default
    v = ask("%s [%s]" % (prompt, "Y/n" if default else "y/N"))
    if not v:
        return default
    return v.lower().startswith(("y", "д"))


def render_telegram(a, env):
    """telegram.yml есть ⇔ токен задан: с пустым bottoken Grafana не стартует."""
    g = os.path.join(stack_dir(a), "grafana")
    tpl, out = os.path.join(g, "telegram.yml.template"), os.path.join(g, "provisioning", "alerting", "telegram.yml")
    if env.get("TELEGRAM_BOT_TOKEN") and env.get("TELEGRAM_CHAT_ID"):
        shutil.copyfile(tpl, out)
        return True
    if os.path.exists(out):
        os.remove(out)
    return False


def wait_health(a, env, timeout=180):
    t0 = time.time()
    want = {"prometheus": False, "grafana": False, "exporter": False}
    while time.time() - t0 < timeout:
        if not want["prometheus"] and http_get("http://127.0.0.1:%s/-/ready" % (env.get("PROMETHEUS_PORT") or "9090"))[0] == 200:
            want["prometheus"] = True
        if not want["grafana"] and http_get("http://127.0.0.1:%s/api/health" % (env.get("GRAFANA_PORT") or "3000"))[0] == 200:
            want["grafana"] = True
        if not want["exporter"]:
            r = prom_query(env, "remnawave_exporter_up")
            if r and r[0]["value"][1] == "1":
                want["exporter"] = True
        if all(want.values()):
            return want
        time.sleep(3)
    return want


def cmd_setup(a):
    sd = stack_dir(a)
    example = os.path.join(sd, ".env.example")
    if not os.path.exists(example):
        print("не вижу %s — запускайте из установленной копии (%s) или из клона с --dir" % (example, DEFAULT_DIR))
        return 2
    env = read_env(env_file(a))
    if env and not a.yes:
        print("найден существующий .env — текущие значения будут предложены по умолчанию")
    yes = a.yes
    okd, msg = docker_ok()
    if not okd:
        print("  ❌ %s\n  Docker нужен для стека; установщик scripts/install.sh умеет его поставить." % msg)
        return 1
    print("── 1/5 Панель Remnawave ──")
    nodes = []
    while True:
        url = (a.panel_url or ask("адрес панели (https://panel.example.com)", env.get("PANEL_URL", ""), yes=yes)).rstrip("/")
        if a.token:
            token = a.token
        elif yes:
            token = env.get("PANEL_TOKEN", "")
        elif env.get("PANEL_TOKEN"):
            token = ask("API-токен панели (Enter — оставить прежний)", secret=True) or env["PANEL_TOKEN"]
        else:
            token = ask("API-токен панели", secret=True)
        insecure = env.get("PANEL_INSECURE", "0")
        okp, msg, nodes = panel_check(url, token, insecure == "1")
        print("  " + ("✅ " if okp else "❌ ") + msg)
        if okp:
            break
        if "certificate" in msg.lower() or "ssl" in msg.lower():
            if ask_yn("похоже на самоподписанный сертификат — не проверять его?", False, yes):
                insecure = "1"
                continue
        if yes or a.panel_url:
            return 1
    env.update(PANEL_URL=url, PANEL_TOKEN=token, PANEL_INSECURE=insecure)
    env.setdefault("BRIDGE_TAG", "bridge")
    env.setdefault("BRIDGE_REGEX", "(?i)bridge")
    if a.bridge_countries is not None:
        env["BRIDGE_COUNTRIES"] = a.bridge_countries
    bridges = [n["name"] for n in nodes if node_role(n, env) == "bridge"]
    if bridges:
        print("  мосты (role=bridge): %s" % ", ".join(bridges))
    else:
        print("  мосты не определены. Мост — нода в стране клиентов, через которую они выходят на остальные.")
        cc = ask("страны мостов через запятую (например RU; пусто — мостов нет)", env.get("BRIDGE_COUNTRIES", ""), yes=yes)
        env["BRIDGE_COUNTRIES"] = cc.upper()
        bridges = [n["name"] for n in nodes if node_role(n, env) == "bridge"]
        if bridges:
            print("  мосты: %s" % ", ".join(bridges))
    print("── 2/5 Grafana ──")
    pw = a.grafana_password or env.get("GRAFANA_ADMIN_PASSWORD") or secrets.token_urlsafe(15)
    env["GRAFANA_ADMIN_PASSWORD"] = pw
    bind = a.bind or ask("Grafana и Kuma доступны снаружи (0.0.0.0, вход по паролю) или только через ssh -L (127.0.0.1)", env.get("GRAFANA_BIND", "0.0.0.0"), yes=yes)
    env["GRAFANA_BIND"] = env["KUMA_BIND"] = bind if bind in ("0.0.0.0", "127.0.0.1") else "0.0.0.0"
    ip = my_ip()
    env["GRAFANA_ROOT_URL"] = env.get("GRAFANA_ROOT_URL") or ("" if is_private(ip) or bind == "127.0.0.1" else "http://%s:%s" % (ip, env.get("GRAFANA_PORT") or "3000"))
    print("  admin / %s  (пароль лежит в %s)" % (pw, env_file(a)))
    print("── 3/5 Telegram для тревог ──")
    tg_token = a.tg_token if a.tg_token is not None else (env.get("TELEGRAM_BOT_TOKEN", "") if yes else ask("токен бота (Enter — %s)" % ("оставить прежний" if env.get("TELEGRAM_BOT_TOKEN") else "без Telegram"), secret=True) or env.get("TELEGRAM_BOT_TOKEN", ""))
    tg_chat = a.tg_chat or (env.get("TELEGRAM_CHAT_ID", "") if (yes or tg_token == env.get("TELEGRAM_BOT_TOKEN")) else "")
    if tg_token and not tg_chat:
        chat, who = telegram_detect_chat(tg_token, proxy=a.tg_proxy)
        if chat:
            print("  ✅ получатель: %s (chat_id %s)" % (who, chat))
            tg_chat = str(chat)
        else:
            print("  ❌ %s" % who)
            tg_chat = ask("chat_id вручную (пусто — без Telegram)", yes=yes)
    if tg_token and tg_chat and not a.skip_telegram_test:
        okt, err = telegram_send(tg_token, tg_chat, "✅ remnawave-monitoring: Telegram подключён. Сюда будут приходить тревоги Grafana.", proxy=a.tg_proxy)
        print("  telegram: " + ("отправлено" if okt else "НЕ отправился: %s" % err))
    env["TELEGRAM_BOT_TOKEN"], env["TELEGRAM_CHAT_ID"] = (tg_token or ""), (tg_chat if tg_token else "")
    print("── 4/5 Проверки HTTPS ──")
    sub = a.sub_url if a.sub_url is not None else ask("адрес страницы подписки для проверки (Enter — не проверять)", env.get("SUB_URL", ""), yes=yes)
    env["SUB_URL"] = sub
    print("── 5/5 Запуск ──")
    write_env(env_file(a), env, example)
    print("  ✅ конфиг записан: %s" % env_file(a))
    print("  telegram.yml: %s" % ("создан" if render_telegram(a, env) else "не нужен"))
    agents, ports, https = build_targets(nodes, env, 9100, None, (), sub, url)
    tdir = os.path.join(sd, "prometheus", "targets")
    for fname, entries in (("nodes.yml", agents), ("blackbox.yml", ports), ("http.yml", https)):
        open(os.path.join(tdir, fname), "w", encoding="utf-8").write("# Сгенерировано remnawave-monitoring setup\n" + yaml_targets(entries))
    print("  ✅ цели: агентов %d, портов %d, HTTPS %d" % (len(agents), len(ports), len(https)))
    if a.no_start:
        print("  стек не запускаю (--no-start): cd %s && docker compose up -d" % sd)
        return 0
    print("  docker compose up -d (первый раз скачивает образы, 1–3 минуты)…")
    r = compose(a, "up", "-d", "--remove-orphans")
    if r.returncode != 0:
        print("  ❌ docker compose не поднялся:\n" + (r.stderr or r.stdout)[-1500:])
        return 1
    print("  жду готовности…")
    w = wait_health(a, env)
    for k, v in w.items():
        print("  %s %s" % ("✅" if v else "❌", k))
    if not all(w.values()):
        print("  что-то не поднялось — remnawave-monitoring doctor покажет причину")
    host = ip if env["GRAFANA_BIND"] == "0.0.0.0" else "127.0.0.1"
    print("\nГотово.")
    print("  Grafana:      http://%s:%s   (admin / %s)" % (host, env.get("GRAFANA_PORT") or "3000", pw))
    print("  Uptime Kuma:  http://%s:%s   (откройте и создайте администратора, потом: remnawave-monitoring kuma-sql --apply)" % (host, env.get("KUMA_PORT") or "3001"))
    if env["GRAFANA_BIND"] == "127.0.0.1":
        print("  доступ с компьютера: ssh -L 3000:127.0.0.1:3000 -L 3001:127.0.0.1:3001 root@%s" % ip)
    if agents:
        print("  Агент на каждую ноду (CPU, диск, память, conntrack) — выполнить на ноде:")
        print("    curl -fsSL https://raw.githubusercontent.com/ponoroshca/remnawave-monitoring/main/scripts/install-node-exporter.sh | sudo bash -s -- --allow-from %s" % ip)
    print("  Проверка: remnawave-monitoring doctor")
    return 0


def cmd_telegram_test(a):
    env = read_env(env_file(a))
    if not env.get("TELEGRAM_BOT_TOKEN") or not env.get("TELEGRAM_CHAT_ID"):
        print("Telegram не настроен в .env")
        return 1
    okt, err = telegram_send(env["TELEGRAM_BOT_TOKEN"], env["TELEGRAM_CHAT_ID"], a.text, proxy=a.tg_proxy)
    print("отправлено" if okt else "НЕ отправился: %s" % err)
    return 0 if okt else 1


# ───────────────────────── CLI ─────────────────────────

def main():
    ap = argparse.ArgumentParser(prog="remnawave-monitoring", description="Мониторинг флота Remnawave: мастер, цели, doctor, Kuma.",
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=VERSION)
    ap.add_argument("--dir", default=os.environ.get("RWMON_DIR", DEFAULT_DIR), help="папка установки (по умолчанию %s)" % DEFAULT_DIR)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("setup", help="мастер настройки и запуск стека")
    s.add_argument("--panel-url")
    s.add_argument("--token", help="API-токен панели")
    s.add_argument("--bridge-countries", help="страны мостов через запятую, например RU")
    s.add_argument("--grafana-password")
    s.add_argument("--bind", choices=["0.0.0.0", "127.0.0.1"], help="где слушать Grafana/Kuma")
    s.add_argument("--tg-token", help="токен бота; пустая строка — без Telegram")
    s.add_argument("--tg-chat", help="chat_id (без него мастер определит по первому сообщению боту)")
    s.add_argument("--tg-proxy", help="HTTP-прокси для api.telegram.org, если напрямую не доходит")
    s.add_argument("--skip-telegram-test", action="store_true")
    s.add_argument("--sub-url", help="адрес страницы подписки для HTTPS-проверки; пустая строка — не проверять")
    s.add_argument("--no-start", action="store_true", help="записать конфиг и цели, стек не запускать")
    s.add_argument("--yes", action="store_true", help="без вопросов: значения из флагов и текущего .env")
    s.set_defaults(fn=cmd_setup)
    t = sub.add_parser("targets", help="цели Prometheus из нод панели")
    t.add_argument("--node-exporter-port", type=int, default=9100)
    t.add_argument("--exclude", help="регулярка по имени ноды — не включать")
    t.add_argument("--http", action="append", default=[], help="дополнительный URL для HTTPS-проверки (можно несколько)")
    t.add_argument("--sub-url", help="адрес страницы подписки (запоминается в .env)")
    t.add_argument("--no-blackbox", action="store_true", help="без проверок портов")
    t.add_argument("--no-agents", action="store_true", help="без целей node-exporter")
    t.add_argument("--ssh-list", action="store_true", help="только напечатать «имя адрес» по нодам (для rollout-node-exporter.sh)")
    t.add_argument("--dry-run", action="store_true", help="показать, не записывать")
    t.set_defaults(fn=cmd_targets)
    d = sub.add_parser("doctor", help="чек-лист")
    d.set_defaults(fn=cmd_doctor)
    st = sub.add_parser("status", help="сводка прямо сейчас")
    st.set_defaults(fn=cmd_status)
    k = sub.add_parser("kuma-sql", help="мониторы Uptime Kuma из нод панели")
    k.add_argument("--apply", action="store_true", help="залить в базу Kuma (с копией) и перезапустить")
    k.add_argument("--sub-url")
    k.add_argument("--status-slug", default="status", help="адрес страницы статуса /status/<slug>")
    k.add_argument("--title", default="Статус сети")
    k.add_argument("--no-status-page", action="store_true")
    k.add_argument("--no-telegram", action="store_true", help="не привязывать Telegram-уведомление")
    k.set_defaults(fn=cmd_kuma)
    tt = sub.add_parser("telegram-test", help="пробное сообщение")
    tt.add_argument("--text", default="✅ remnawave-monitoring: проверка связи")
    tt.add_argument("--tg-proxy")
    tt.set_defaults(fn=cmd_telegram_test)
    a = ap.parse_args()
    try:
        return a.fn(a)
    except KeyboardInterrupt:
        print("\nпрервано")
        return 130


if __name__ == "__main__":
    sys.exit(main())
