# Справочник

Всё, что есть в репозитории: команды и флаги, переменные, метрики, правила, файлы, коды выхода.
Для первого знакомства — [START-HERE.md](START-HERE.md).

## remnawave-monitoring — команды

Общие флаги (перед командой): `--dir DIR` — папка установки (по умолчанию `/opt/remnawave-monitoring`,
или переменная `RWMON_DIR`), `--version`.

### `setup` — мастер и запуск стека

| флаг | что |
|---|---|
| `--panel-url URL` | адрес панели (`https://…`, без `/api`) |
| `--token T` | API-токен панели |
| `--bridge-countries RU,KZ` | страны, чьи ноды считать мостами (`BRIDGE_COUNTRIES`) |
| `--grafana-password P` | пароль admin (иначе берётся из `.env` или генерируется) |
| `--bind 0.0.0.0\|127.0.0.1` | где слушать Grafana и Kuma |
| `--tg-token T` | токен бота; `--tg-token ""` — без Telegram |
| `--tg-chat ID` | chat_id (без него — определяется по первому сообщению боту, до 90 с) |
| `--tg-proxy URL` | HTTP-прокси для api.telegram.org |
| `--skip-telegram-test` | не слать пробное сообщение |
| `--sub-url URL` | страница подписки для HTTPS-проверки; `--sub-url ""` — не проверять |
| `--no-start` | записать `.env`, `telegram.yml` и цели, стек не поднимать |
| `--yes` | без вопросов: значения из флагов и существующего `.env` |

Мастер: проверяет панель → определяет мосты → пароль Grafana → Telegram (getMe, getUpdates, пробное
сообщение) → страница подписки → пишет `.env` (600) → создаёт/удаляет `telegram.yml` → генерирует цели →
`docker compose up -d --remove-orphans` → ждёт до 180 с готовности Prometheus, Grafana и первого
удачного опроса панели экспортёром → печатает адреса.

### `targets` — цели Prometheus из нод панели

| флаг | что |
|---|---|
| `--node-exporter-port N` | порт агента (9100) |
| `--exclude REGEX` | не включать ноды, чьё имя подходит |
| `--http URL` | дополнительная HTTPS-проверка (можно несколько раз) |
| `--sub-url URL` | страница подписки (запоминается в `.env` как `SUB_URL`) |
| `--no-blackbox` | без проверок портов |
| `--no-agents` | без целей node-exporter |
| `--ssh-list` | только напечатать `имя адрес` по нодам — для `rollout-node-exporter.sh` |
| `--dry-run` | показать файлы, не записывать |

Пишет `stack/prometheus/targets/{nodes,blackbox,http}.yml` (выключенные в панели ноды пропускаются),
затем `POST http://127.0.0.1:$PROMETHEUS_PORT/-/reload`. Файлы можно править руками — Prometheus перечитывает
их раз в минуту. Порты для blackbox берутся из активных инбаундов ноды (`configProfile.activeInbounds[].port`).

### `doctor` — чек-лист

Файлы и права `.env`, Telegram и `telegram.yml`, панель (и какие ноды считаются мостами), Docker и
шесть контейнеров, цели Prometheus по job'ам с причинами недоступности, последний опрос панели,
Grafana (пароль, дашборды, правила, точка доставки), Kuma (администратор, число мониторов), ufw.
Код выхода 0 — проблем нет, 1 — есть (ℹ️ — не проблема).

### `status` — сводка в консоль

Онлайн/сессии/пользователи/ноды и таблица по нодам (страна, связь, сессии, load на ядро, входящая
полоса) из Prometheus; цели, которые не отвечают.

### `kuma-sql` — мониторы Uptime Kuma

| флаг | что |
|---|---|
| `--apply` | залить в базу Kuma (`docker exec rwmon-kuma sqlite3`) с копией `kuma.db.bak-<дата>` и перезапустить контейнер |
| `--sub-url URL` | страница подписки |
| `--status-slug S` | адрес страницы статуса `/status/S` (`status`) |
| `--title T` | заголовок страницы статуса («Статус сети») |
| `--no-status-page` | без страницы статуса |
| `--no-telegram` | не создавать Telegram-уведомление |

Без `--apply` печатает SQL. Мониторы: `port` на каждый активный инбаунд каждой ноды (интервал 60 с,
2 повтора, таймаут 10 с), `http` на панель и страницу подписки (коды 2xx/3xx/401/403/404 = «жива»),
уведомление Telegram из `.env` привязывается ко всем мониторам, страница статуса с группой «Серверы».
Все вставки — `WHERE NOT EXISTS` по имени: повторный запуск ничего не дублирует, новые ноды добавляет.
Требует созданного администратора Kuma (иначе отказ). Kuma 2.x, SQLite.

### `telegram-test` — пробное сообщение

`--text` — текст, `--tg-proxy` — прокси.

## stack/.env

| переменная | по умолчанию | что |
|---|---|---|
| `PANEL_URL` | — | адрес панели, `https://panel.example.com` |
| `PANEL_TOKEN` | — | API-токен |
| `SCRAPE_SECONDS` | 30 | период опроса панели экспортёром (не меньше 5) |
| `BRIDGE_TAG` | `bridge` | тег ноды в панели → `role=bridge` |
| `BRIDGE_REGEX` | `(?i)bridge` | регулярка по имени ноды → `role=bridge` |
| `BRIDGE_COUNTRIES` | пусто | страны через запятую → `role=bridge` |
| `PANEL_INSECURE` | 0 | 1 — не проверять TLS-сертификат панели |
| `GRAFANA_ADMIN_PASSWORD` | — | пароль admin (задаётся при первом старте; менять потом — в интерфейсе Grafana и здесь) |
| `GRAFANA_BIND` / `GRAFANA_PORT` | `0.0.0.0` / 3000 | где слушает Grafana |
| `GRAFANA_ROOT_URL` | пусто | внешний адрес для ссылок в уведомлениях |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | пусто | тревоги Grafana и уведомления Kuma |
| `SUB_URL` | пусто | страница подписки для HTTPS-проверок |
| `KUMA_BIND` / `KUMA_PORT` | `0.0.0.0` / 3001 | где слушает Kuma |
| `PROMETHEUS_PORT` | 9090 | всегда только 127.0.0.1 |
| `PROMETHEUS_RETENTION` | 90d | глубина истории |
| `PROMETHEUS_IMAGE_TAG`, `GRAFANA_IMAGE_TAG`, `NODE_EXPORTER_IMAGE_TAG`, `BLACKBOX_IMAGE_TAG` | `latest` | версии образов |
| `KUMA_IMAGE_TAG` | `2` | Uptime Kuma 2.x (SQL из `kuma-sql` рассчитан на её схему) |
| `PYTHON_IMAGE_TAG` | `3.12-slim` | образ для экспортёра |

Значения с `$` в `.env` docker compose читает как подстановку — экранируйте `$$`.
После правки `.env`: `cd /opt/remnawave-monitoring/stack && docker compose up -d`.

## Экспортёр `exporter/rw_exporter.py`

Запускается контейнером `rwmon-exporter` (`python:3.12-slim`, файл примонтирован только для чтения) или
где угодно с Python 3.9+. Переменные окружения: `PANEL_URL`, `PANEL_TOKEN` (обязательные), `SCRAPE_SECONDS`
(30), `LISTEN` (`0.0.0.0:9200`), `BRIDGE_TAG`, `BRIDGE_REGEX`, `BRIDGE_COUNTRIES`, `PANEL_INSECURE`,
`PANEL_TIMEOUT` (20 с). Адреса: `/metrics`, `/healthz` (200 — последний опрос удался, 503 — нет, с текстом
ошибки), `/`. `--version`. Коды выхода: 2 — нет `PANEL_URL`/`PANEL_TOKEN` или неверный `LISTEN`.
При ошибке панели старые значения **не** отдаются — только `remnawave_exporter_up 0` и счётчики, чтобы
графики честно рвались, а не показывали вчерашний онлайн.

### Метрики

Метки `node` (имя ноды в панели), `role` (`bridge`/`node`), `country` (ISO-код из панели).

| метрика | тип | метки | что |
| `remnawave_online_now` | gauge | — | Уникальных пользователей онлайн сейчас (по данным панели) |
| `remnawave_online_last_day` | gauge | — | Пользователей, выходивших онлайн за последние сутки |
| `remnawave_online_last_week` | gauge | — | Пользователей, выходивших онлайн за последнюю неделю |
| `remnawave_online_never` | gauge | — | Пользователей, ни разу не подключавшихся |
| `remnawave_users_total` | gauge | — | Всего пользователей в панели |
| `remnawave_users_by_status` | gauge | status | Пользователей по статусу (ACTIVE, DISABLED, LIMITED, EXPIRED) |
| `remnawave_sessions_total` | gauge | — | Сессий (подключений) на всех нодах сейчас; один пользователь с двух устройств — две сессии |
| `remnawave_panel_uptime_seconds` | gauge | — | Аптайм сервера панели, секунд |
| `remnawave_panel_memory_total_bytes` | gauge | — | Память сервера панели, всего |
| `remnawave_panel_memory_used_bytes` | gauge | — | Память сервера панели, занято |
| `remnawave_panel_cpu_cores` | gauge | — | Ядер CPU на сервере панели |
| `remnawave_node_connected` | gauge | country, node, role | 1 — нода на связи с панелью |
| `remnawave_node_disabled` | gauge | country, node, role | 1 — нода выключена в панели (не считается проблемой) |
| `remnawave_node_users_online` | gauge | country, node, role | Сессий на ноде сейчас |
| `remnawave_node_traffic_used_bytes` | gauge | country, node, role | Трафик пользователей ноды, накопленный панелью (счётчик панели, не хостера) |
| `remnawave_node_traffic_limit_bytes` | gauge | country, node, role | Лимит трафика ноды в панели; 0 — лимита нет |
| `remnawave_node_traffic_used_percent` | gauge | country, node, role | Процент лимита трафика ноды; 0 — если лимита нет |
| `remnawave_node_traffic_reset_day` | gauge | country, node, role | День месяца, когда панель сбрасывает счётчик трафика ноды |
| `remnawave_node_xray_uptime_seconds` | gauge | country, node, role | Аптайм xray на ноде, секунд |
| `remnawave_node_system_uptime_seconds` | gauge | country, node, role | Аптайм сервера ноды, секунд |
| `remnawave_node_cpus` | gauge | country, node, role | Ядер CPU на ноде |
| `remnawave_node_memory_total_bytes` | gauge | country, node, role | Память ноды, всего |
| `remnawave_node_memory_free_bytes` | gauge | country, node, role | Память ноды, свободно |
| `remnawave_node_load1` | gauge | country, node, role | Load average ноды за 1/5/15 минут |
| `remnawave_node_load5` | gauge | country, node, role | Load average ноды за 1/5/15 минут |
| `remnawave_node_load15` | gauge | country, node, role | Load average ноды за 1/5/15 минут |
| `remnawave_node_rx_bytes_per_second` | gauge | country, node, role | Входящая скорость интерфейса ноды, байт/с (умножьте на 8 — биты) |
| `remnawave_node_tx_bytes_per_second` | gauge | country, node, role | Исходящая скорость интерфейса ноды, байт/с |
| `remnawave_node_rx_bytes_total` | counter | country, node, role | Счётчик интерфейса ноды с загрузки сервера, входящие байты (так считает хостер) |
| `remnawave_node_tx_bytes_total` | counter | country, node, role | Счётчик интерфейса ноды с загрузки сервера, исходящие байты |
| `remnawave_node_info` | gauge | country, node, node_version, role, xray_version | Версии xray и remnanode на ноде (всегда 1, данные — в метках) |
| `remnawave_nodes_total` | gauge | — | Нод в панели, всего |
| `remnawave_nodes_connected` | gauge | — | Нод на связи с панелью |
| `remnawave_nodes_disabled` | gauge | — | Нод, выключенных в панели |
| `remnawave_exporter_up` | gauge | — | 1 — последний опрос панели удался |
| `remnawave_exporter_scrape_duration_seconds` | gauge | — | Длительность последнего опроса панели |
| `remnawave_exporter_last_success_timestamp_seconds` | gauge | — | Unix-время последнего удачного опроса |
| `remnawave_exporter_scrapes_total` | counter | — | Опросов панели с запуска экспортёра |
| `remnawave_exporter_errors_total` | counter | — | Неудачных опросов с запуска экспортёра |
| `remnawave_exporter_info` | gauge | version | Версия экспортёра |

## Правила тревог (`stack/grafana/provisioning/alerting/rules.yml`)

Группа `remnawave`, папка Remnawave, вычисляются раз в минуту; `noDataState: OK` (кроме экспортёра),
`execErrState: Error`. Доставка — `telegram.yml` (из `stack/grafana/telegram.yml.template`): группировка
по `alertname` + `node`, `group_wait 30s`, `group_interval 5m`, `repeat_interval 6h`, сообщение из шаблона
`rw-telegram` (`🔴`/`✅ снято:` + summary), без разметки.

| uid | выражение (A) | условие | for | severity |
|---|---|---|---|---|
| `rw-node-down` | `remnawave_node_connected == 0 and remnawave_node_disabled == 0` | < 1 | 3m | critical |
| `rw-traffic-80` | `remnawave_node_traffic_used_percent` | > 80 | 5m | warning |
| `rw-load-high` | `remnawave_node_load1 / remnawave_node_cpus > 0` | > 0.9 | 15m | warning |
| `rw-cpu-high` | `100 - avg by (node) (rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100` | > 85 | 10m | warning |
| `rw-disk-low` | `node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"} * 100` | < 10 | 5m | warning |
| `rw-memory-low` | `node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes * 100` | < 10 | 10m | warning |
| `rw-conntrack-high` | `node_nf_conntrack_entries / node_nf_conntrack_entries_limit * 100` | > 80 | 5m | warning |
| `rw-port-down` | `probe_success{job="blackbox-tcp"}` | < 1 | 3m | critical |
| `rw-http-down` | `probe_success{job="blackbox-http"}` | < 1 | 2m | critical |
| `rw-agent-down` | `up{job="node"}` | < 1 | 5m | warning |
| `rw-exporter-down` | `min(remnawave_exporter_up) or vector(0)` | < 1 | 5m (noData → Alerting) | warning |

Правила заведены через file provisioning — в интерфейсе они только для чтения. Меняйте YAML и
`docker compose restart grafana`. Свои правила добавляйте в интерфейсе в другой папке или другим файлом.

## Дашборды

`stack/grafana/provisioning/dashboards/json/remnawave-fleet.json` («Remnawave — флот», uid `remnawave-fleet`)
и `remnawave-node.json` («Remnawave — нода», uid `remnawave-node`, переменная `node`). Генерируются
`tools/build_dashboard.py` (`--check` — сравнить с файлами; CI проверяет). В интерфейсе редактирование
выключено (`allowUiUpdates: false`) — правьте генератор или скопируйте дашборд («Save as») в свою папку.

## Файлы и порты (сервер мониторинга)

| путь | что |
|---|---|
| `/opt/remnawave-monitoring/` | копия репозитория; `stack/` — compose и конфиги |
| `stack/.env` (600) | настройки и секреты |
| `stack/prometheus/prometheus.yml` | job'ы: `prometheus`, `remnawave` (экспортёр), `node` (агенты + сам сервер), `blackbox-tcp`, `blackbox-http` |
| `stack/prometheus/targets/*.yml` | цели (file_sd, перечитываются раз в минуту) |
| `stack/blackbox/blackbox.yml` | модули `tcp_connect`, `http_2xx` |
| `stack/grafana/provisioning/` | datasource `prometheus` (uid `prometheus`), дашборды, `alerting/rules.yml`, `alerting/telegram.yml` |
| `stack/grafana/telegram.yml.template` | шаблон точки доставки; копируется мастером в `provisioning/alerting/telegram.yml` только при заданном токене |
| `/usr/local/bin/remnawave-monitoring` | ссылка на `scripts/rwmon.py` |
| тома `remnawave-monitoring_{prometheus,grafana,kuma}-data` | история, Grafana, Kuma |
| контейнеры `rwmon-prometheus`, `rwmon-exporter`, `rwmon-node-exporter`, `rwmon-blackbox`, `rwmon-grafana`, `rwmon-kuma` | стек |
| порты | 3000 Grafana, 3001 Kuma (по `*_BIND`), 9090 Prometheus (только 127.0.0.1); 9200/9100/9115 — только внутри сети compose |

## Установка и удаление стека

`scripts/install.sh` (root): переменные `NO_SETUP=1` — только скопировать файлы, `INSTALL_DOCKER=1` —
ставить Docker без вопроса, `RWMON_SRC_URL` — откуда брать архив исходников (по умолчанию GitHub, main).
Из клона берёт файлы из него. Ставит `python3`, `curl`, `tar`, Docker (`docker.io` + `docker-compose-v2` из
дистрибутива, иначе get.docker.com). Повторный запуск = обновление: `exporter/`, `scripts/`, `backup/`,
`tools/`, `docs/` заменяются, `stack/` копируется поверх — `.env`, `prometheus/targets/*.yml` и
`telegram.yml` сохраняются; если `.env` есть — `docker compose up -d`. Останавливается на чужой ссылке
`/usr/local/bin/remnawave-monitoring` или чужой непустой `/opt/remnawave-monitoring`.

`scripts/uninstall.sh` (root): без флагов спрашивает (нужен терминал; без терминала — ничего не удаляет,
кроме контейнеров); `--keep-data` — остановить контейнеры, тома и папку оставить; `--data` — удалить и
тома (история, Grafana, Kuma); `--all` — тома и `/opt/remnawave-monitoring` вместе с `.env`.

## Агент на ноде

`scripts/install-node-exporter.sh` (запускать на ноде, root): `--allow-from IP` (обязательно), `--port N`
(9100), `--no-firewall`, `--uninstall`, `--help`. Контейнер `node-exporter` (`prom/node-exporter:latest`,
`--net host --pid host`, `/:/host:ro`, `--path.rootfs=/host`, `--web.listen-address=:PORT`), правило
`ufw allow from IP to any port PORT proto tcp comment node-exporter`. Коды выхода: 1 — нет root/docker,
ufw не активен без `--no-firewall`, чужой контейнер, контейнер не поднялся; 2 — неверные флаги.

`scripts/rollout-node-exporter.sh hosts.txt` — установить агент по ssh на все ноды из файла (строка:
`имя адрес [порт ssh]`, `#` — комментарий). Флаги: `-k` ключ ssh, `-p` порт ssh по умолчанию (22),
`-j` параллельных установок (4), `--allow-from` IP сервера мониторинга (по умолчанию адрес этого
сервера), `--no-firewall`. Подключается как `root@адрес` в `BatchMode`; итоговая таблица; код выхода 1,
если хоть одна нода не встала. Список нод из панели: `remnawave-monitoring targets --ssh-list > hosts.txt`.

## Бэкапы (`backup/`)

| скрипт | где запускать | что |
|---|---|---|
| `install-backup.sh` | сервер панели и/или мониторинга, root | ставит `age`, `rsync`; скрипты → `/opt/remnawave-backup`, конфиг → `/etc/remnawave-backup/backup.env` (600), юниты `remnawave-backup.timer/service`; мастер; первый бэкап. `NO_SETUP=1` — без мастера. `--uninstall`. `--offsite-receiver [папка]` — режим принимающего сервера (папка, `rrsync`, таймер снимков `remnawave-snapshot.timer` в 05:00) |
| `run.sh` | таймер | `backup-panel.sh` (если `BACKUP_PANEL=1`) → `backup-monitoring.sh` (если `BACKUP_MONITORING=1`) → `sync-offsite.sh` (если `OFFSITE` задан); части независимы |
| `backup-panel.sh [--dry-run]` | сервер панели | `docker exec $DB_CONTAINER pg_dump -Fc` → проверки размера (≥ `MIN_DUMP_BYTES`, ≥ половины прошлого) → `tar` папки панели → MANIFEST → `age -r RECIPIENT` → `panel-<дата>.tar.age` → ротация |
| `backup-monitoring.sh` | сервер мониторинга | `kuma.db`, `grafana.db` (sqlite backup API из томов) + `stack/` → `monitoring-<дата>.tar.age` |
| `sync-offsite.sh` | сервер с копиями | `rsync -a` (без `--delete`) `*.tar.age` и `backup.log` в `OFFSITE` ключом `OFFSITE_KEY` |
| `snapshot.sh [папка] [сколько]` | offsite-сервер | `cp -al current → snapshots/<дата>`, хранить N (14) |
| `verify-restore.sh <архив> <ключ> [--pg-image postgres:17]` | ваш компьютер (docker + age) | расшифровать → временный Postgres → `pg_restore` → таблицы/пользователи/ноды/хосты → убрать; код 1 при неудаче |
| `restore-panel.sh <архив> <ключ>` | НОВЫЙ сервер панели, root | отказ, если `/opt/remnawave` не пуст или есть `remnawave-db`; подтверждение словом `восстановить`; папка → база → `pg_restore --clean --if-exists` → `docker compose up -d` |

### `/etc/remnawave-backup/backup.env`

| ключ | по умолчанию | что |
|---|---|---|
| `RECIPIENT` | — | публичный ключ age `age1…` |
| `OUT_DIR` | `/var/backups/remnawave` | куда складывать (`panel/`, `monitoring/`, `backup.log`) |
| `KEEP_DAYS` / `MON_KEEP_DAYS` | 14 / 7 | хранить дней |
| `KEEP_MIN` | 3 | не удалять последние N копий, даже если старше |
| `BACKUP_PANEL` / `BACKUP_MONITORING` | по обнаружению | что делать на этом сервере |
| `DB_CONTAINER` | `remnawave-db` | контейнер Postgres панели (внутри должны быть `POSTGRES_USER`, `POSTGRES_DB`) |
| `PANEL_DIR` | `/opt/remnawave` | папка панели |
| `MONITORING_DIR` | `/opt/remnawave-monitoring` | папка стека |
| `MIN_DUMP_BYTES` | 2000 | меньше — дамп считается битым |
| `HOUR` | 03:30 | время таймера (по часам сервера) |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` / `TELEGRAM_PROXY` | пусто | только об ошибках |
| `OFFSITE` | пусто | `user@host:/path/current` |
| `OFFSITE_KEY` / `OFFSITE_PORT` | `/root/.ssh/remnawave-backup` / 22 | ключ и порт ssh |

Внутри архива панели: `MANIFEST` (host, date, dump_bytes, users, nodes, panel_dir), `panel.pgdump`
(`pg_dump -Fc`), `panel-dir.tgz`. Мониторинга: `MANIFEST`, `kuma.db`, `grafana.db`, `stack.tgz`.

## Коды выхода (общие)

`0` — успех; `1` — ошибка выполнения (панель не ответила, стек не поднялся, `doctor` нашёл проблемы,
бэкап не удался); `2` — нет конфига / неверные аргументы; `130` — прервано Ctrl+C.
