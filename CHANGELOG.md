# История изменений

## 1.0.0 — 2026-09-22

Первая публичная версия: экспортёр панели (только stdlib), стек Prometheus + Grafana (дашборды «флот»
и «нода», 11 правил тревог с доставкой в Telegram через file provisioning) + node-exporter + blackbox +
Uptime Kuma 2; `remnawave-monitoring setup/targets/doctor/status/kuma-sql/telegram-test`; агент на ноды
с файрволом «только серверу мониторинга»; зашифрованные age бэкапы панели и мониторинга с ротацией,
offsite-копией, снимками, проверкой восстановления и восстановлением на новом сервере.
