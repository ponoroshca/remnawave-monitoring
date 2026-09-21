# Как помочь проекту

- Не сходится с вашей панелью/версией Grafana/Kuma — issue с выводом `remnawave-monitoring doctor`
  (адреса можно заменить на 203.0.113.x) и версиями образов (`docker compose images`).
- Код: Python 3.9+ и bash, только стандартная библиотека; экспортёр и команды не должны ничего
  менять в панели — PR с PATCH/POST/DELETE к панели не принимаются.
- Дашборды правятся в `tools/build_dashboard.py`, JSON генерируется (`python3 tools/build_dashboard.py`);
  CI проверяет, что JSON в репозитории совпадает с генератором.
- Перед PR: `python3 -m py_compile exporter/*.py scripts/*.py tools/*.py`, `bash -n scripts/*.sh backup/*.sh`,
  `python3 tests/test_exporter.py`, `python3 tools/build_dashboard.py --check`.
