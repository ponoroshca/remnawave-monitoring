# remnawave-monitoring — fleet monitoring and encrypted backups for Remnawave

Russian is the primary language of this project ([README.md](README.md)); this is a short summary.

One command gives you Grafana with your Remnawave fleet, Telegram alerts, a public status page
and nightly encrypted backups of the panel. Standard components only (Prometheus, Grafana,
node-exporter, blackbox, Uptime Kuma, age); nothing in the panel is modified.

- `exporter/rw_exporter.py` — Prometheus exporter for the panel (stdlib only, read-only): online
  users, sessions, per-node link state, speed, interface counters (the way hosters bill), load,
  memory, traffic vs limit, xray/remnanode versions.
- `stack/` — docker compose: Prometheus + Grafana (2 dashboards, 11 provisioned alert rules →
  Telegram) + node-exporter + blackbox + Uptime Kuma.
- `remnawave-monitoring targets` — scrape targets generated from the panel's node list.
- `scripts/install-node-exporter.sh` — agent for nodes; port 9100 is opened only to the monitoring
  host via ufw, refuses to install with the firewall off.
- `backup/` — nightly `pg_dump` + panel folder (and Kuma/Grafana DBs), encrypted with an **age**
  public key (no secret key on servers), rotation, off-site copy, `verify-restore.sh`, `restore-panel.sh`.

```bash
curl -fsSL https://raw.githubusercontent.com/ponoroshca/remnawave-monitoring/main/scripts/install.sh | sudo bash
```

Docs (Russian): [START-HERE](docs/START-HERE.md) · [SAFETY](docs/SAFETY.md) · [RECOVERY](docs/RECOVERY.md) · [reference](docs/reference.md) · [faq](docs/faq.md). MIT.
