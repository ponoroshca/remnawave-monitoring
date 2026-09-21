# Восстановление после потери

Здесь — что где лежит и что делать, если умер сервер. Рассчитано на человека, у которого есть
секретный ключ age и доступ к серверам (или деньги на новые).

## Что нужно иметь на руках — проверьте сегодня

| что | где должно лежать | без этого |
|---|---|---|
| **секретный ключ age** `AGE-SECRET-KEY-1…` | менеджер паролей + бумага; **не** на серверах | бэкапы не расшифровать — никак |
| ssh-доступ к серверам (ключ или пароли) | ваш компьютер + менеджер паролей | заново через консоль хостера |
| этот репозиторий | GitHub (или клон у вас) | скрипты восстановления |
| конфиг мониторинга `/opt/remnawave-monitoring/stack/.env` | в бэкапе мониторинга (`stack.tgz`) | заново прогнать мастер (5 минут) |

## Где лежат копии

| что | делается на | когда | хранится | ещё копии |
|---|---|---|---|---|
| **панель**: `pg_dump -Fc` базы + папка панели (`/opt/remnawave`: compose, `.env`, ключи) + MANIFEST | сервер панели, `/var/backups/remnawave/panel/panel-<дата>.tar.age` | ежедневно (`HOUR`, по умолчанию 03:30) | `KEEP_DAYS` (14), но не меньше `KEEP_MIN` (3) | `OFFSITE` — второй сервер, `current/` + ежедневные снимки `snapshots/<дата>` (14) |
| **мониторинг**: базы Kuma и Grafana (`sqlite backup`), `stack/` (`.env`, цели, provisioning) | сервер мониторинга, `/var/backups/remnawave/monitoring/monitoring-<дата>.tar.age` | тот же таймер | `MON_KEEP_DAYS` (7) | там же |

История Prometheus не бэкапится — она большая и восстановится сама жизнью.
Лог: `/var/backups/remnawave/backup.log`. Любая ошибка → Telegram (если задан бот).

## Как расшифровать любой архив

```bash
age -d -i age-backup.key panel-2026-09-22_0330.tar.age | tar x
# панель:     MANIFEST  panel.pgdump  panel-dir.tgz
# мониторинг: MANIFEST  kuma.db  grafana.db  stack.tgz
```

`age` на Mac — `brew install age`, на Linux — `apt install age`, Windows — https://github.com/FiloSottile/age/releases.
`age-backup.key` — файл с одной строкой `AGE-SECRET-KEY-1…`.

## Сценарий 1: умер сервер панели (самое страшное)

Без бэкапа теряются все пользователи, подписки, ноды, хосты. С бэкапом — не больше суток.

1. Новый сервер (та же ОС, что была; Docker поставлен — например, `curl -fsSL https://get.docker.com | sh`).
2. Заберите последний `panel-*.tar.age` с offsite-сервера (`/root/remnawave-offsite/current/panel/`)
   или, если старый сервер ещё отдаёт файлы, с него: `scp root@старый:/var/backups/remnawave/panel/panel-*.tar.age .`
3. Секретный ключ в файл `age-backup.key` (права 600), архив и ключ — на новый сервер.
4. На новом сервере:
   ```bash
   apt install -y age
   curl -fsSL https://raw.githubusercontent.com/ponoroshca/remnawave-monitoring/main/backup/restore-panel.sh -o restore-panel.sh
   bash restore-panel.sh panel-2026-09-22_0330.tar.age age-backup.key
   ```
   Скрипт откажется работать, если на сервере уже есть `/opt/remnawave` или контейнер `remnawave-db`
   (защита от запуска на живой панели). Спросит подтверждение словом `восстановить`, затем:
   папка панели → только база → `pg_restore` → вся панель. Напечатает число пользователей в базе.
5. DNS панели и страницы подписки → IP нового сервера (у Cloudflare — минута).
6. **Ноды подключаются к панели сами** (они ходят на её домен), но панели нужно достучаться до нод:
   если у нод в файрволе порт remnanode (обычно 2222/3000) открыт только со старого IP панели —
   на каждой ноде `ufw allow from <новый IP> to any port <порт>`. В панели ноды должны стать
   зелёными в течение пары минут.
7. Проверка: вход в панель, страница подписки открывается, тестовый клиент подключается.
8. Заново включить бэкапы на новом сервере: `backup/install-backup.sh` (вариант 2 — вставить
   **прежний публичный** ключ, чтобы старые и новые копии открывались одним секретным).
9. `age-backup.key` с сервера удалить (`shred -u`).

## Сценарий 2: умер сервер мониторинга

Клиенты этого не заметят: панель и ноды от мониторинга не зависят. Пропадают графики, тревоги и
страница статуса.

1. Новый сервер, `scripts/install.sh` — мастер заново (5 минут, нужны токен панели и токен бота).
   Если есть бэкап мониторинга — расшифруйте и возьмите из `stack.tgz` файл `.env`
   (положить в `/opt/remnawave-monitoring/stack/.env` **до** мастера — он предложит значения по умолчанию).
2. Kuma: `kuma.db` из архива → в том `remnawave-monitoring_kuma-data` (`docker compose stop uptime-kuma`,
   `docker cp kuma.db rwmon-kuma:/app/data/kuma.db`, `docker compose start uptime-kuma`) — вернутся история
   и страница статуса. Или просто `remnawave-monitoring kuma-sql --apply` заново (история пропадёт).
3. Grafana: дашборды и правила приезжают из репозитория, `grafana.db` нужен только если вы делали
   свои дашборды — так же через `docker cp` в `/var/lib/grafana/grafana.db` контейнера `rwmon-grafana`.
4. **IP сервера мониторинга изменился** → на всех нодах `install-node-exporter.sh --allow-from <новый IP>`
   (старое правило ufw снять: `ufw status numbered` → `ufw delete N`). И в Kuma/Grafana ничего
   больше менять не нужно.

## Сценарий 3: умер offsite-сервер

Ничего не потеряно — это была третья копия. Новый сервер: `install-backup.sh --offsite-receiver`,
на сервере панели в `/etc/remnawave-backup/backup.env` новый `OFFSITE=`, публичный ключ отправителя
(`/root/.ssh/remnawave-backup.pub`) — в `authorized_keys` нового, как напечатает `--offsite-receiver`.

## Сценарий 4: потерян секретный ключ age

Старые архивы не открыть — точка. Немедленно: `install-backup.sh` заново (вариант 1 — новая пара),
сохранить новый секрет в два места, дождаться ночного бэкапа и проверить его `verify-restore.sh`.
Пока панель жива, ничего не потеряно.

## Сценарий 5: панель жива, но что-то удалили/сломали

Не восстанавливайте поверх живой панели вслепую. Разверните бэкап **на другом сервере или в
временной базе** (`verify-restore.sh` оставляет цифры, а для «посмотреть данные» —
`docker exec -it rw-verify-… psql -U postgres -d verify`, если убрать `cleanup` из скрипта) и
перенесите нужное руками или SQL-ом.

## Как убедиться, что бэкапы живы

Раз в неделю (или включите себе напоминание):

```bash
ssh root@панель 'tail -3 /var/backups/remnawave/backup.log; ls -la /var/backups/remnawave/panel | tail -3'
ssh root@offsite 'ls /root/remnawave-offsite/snapshots/ | tail -3; tail -1 /root/remnawave-offsite/snapshot.log'
systemctl list-timers remnawave-backup.timer   # на сервере панели: NEXT — завтра, LAST — сегодня
```

Раз в месяц — **тестовое восстановление** на своём компьютере (нужны docker и age):

```bash
scp root@панель:/var/backups/remnawave/panel/panel-2026-09-22_0330.tar.age .
backup/verify-restore.sh panel-2026-09-22_0330.tar.age ~/keys/age-backup.key
#   таблиц: 36  пользователей: 2088  нод: 6  хостов: 9
# ✅ бэкап восстанавливается
```

Сравните число пользователей с панелью. Если скрипт говорит ❌ — бэкапы битые, чините сегодня,
а не когда понадобятся.
