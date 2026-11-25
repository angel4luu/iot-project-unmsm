# Secrets directory (example)

Everything in `infrastructure/secrets/` is ignored by git except this file.
Files are created with owner-only permissions (`0600`, directory `0700`) by
`make dev-certs` and `infrastructure/influxdb/setup.sh`, or by hand where noted.
Never copy a value into `.env.example`, Compose YAML, firmware source, fixtures,
screenshots, logs, or the article (constitution IV).

| File | Content | Created by |
|---|---|---|
| `ca.key` | Private key of the lab certificate authority | `make dev-certs` |
| `ca.crt` | Lab CA certificate (public, distributed to clients) | `make dev-certs` |
| `broker.key`, `broker.crt` | Mosquitto server key and certificate | `make dev-certs` |
| `ingestion.key`, `ingestion.crt` | Ingestion MQTT client identity | `make dev-certs` |
| `admin.key`, `admin.crt` | Operator/admin MQTT client identity | `make dev-certs` |
| `simulator.key`, `simulator.crt` | Simulator test-node identity | `make dev-certs` |
| `node-<node_id>.key`, `node-<node_id>.crt` | One identity per physical node | `make dev-certs` |
| `influx-admin-password` | InfluxDB setup user password | `infrastructure/influxdb/setup.sh` |
| `influx-admin-token` | InfluxDB setup/admin token | `infrastructure/influxdb/setup.sh` |
| `influx-ingestion-token` | Write-only token for `energy_raw` and `operations` | `infrastructure/influxdb/setup.sh` |
| `influx-grafana-token` | Read-only token for Grafana | `infrastructure/influxdb/setup.sh` |
| `grafana-admin-password` | Grafana administrator password | `make dev-certs` (random) |
| `notification-token` | Notification provider token | by hand |
| `secrets.local.node-<node_id>.json` | Per-device provisioning manifest: Wi-Fi SSID and password, broker host name, node ID | by hand (read by `scripts/provision-node.py`) |
