#!/usr/bin/env bash
# Read-only viewers for the guided end-to-end walkthrough (guides/operations/e2e-walkthrough.md).
#
#   scripts/e2e-view.sh broker  [node]          live MQTT messages of one node (Ctrl-C to stop)
#   scripts/e2e-view.sh db      <table> [node]  latest SQLite rows of one node
#   scripts/e2e-view.sh influx  <view>  [node] [range]   latest InfluxDB points (range: 15m)
#   scripts/e2e-view.sh counts  [node]          ledger states and reject codes of one node
#
# Tables: node, calibration, threshold, ledger, alert, transition, outbox
# Views:  raw (energy_raw readings), status, ingest, alerts, notifications, pipeline
#
# Nothing here writes: SQLite opens read-only, InfluxDB uses the read-only Grafana token
# (passed by environment, never printed), and MQTT uses the read-only svc-admin identity.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
SECRETS="$ROOT/infrastructure/secrets"
INGESTION=unmsm-energy-ingestion-1
INFLUX=unmsm-energy-influxdb-1
NODE_DEFAULT=sim-e2e

usage() { sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }
check_node() { [[ "$1" =~ ^[a-z0-9][a-z0-9-]{0,31}$ ]] || { echo "bad node id: $1" >&2; exit 2; }; }

broker() {
  local node="${1:-$NODE_DEFAULT}"; check_node "$node"
  local port
  port="$(grep -E '^MQTT_TLS_PORT=' "$ROOT/.env" 2>/dev/null | cut -d= -f2)"
  echo "Watching unmsm/energy/v1/nodes/$node/# (retained messages first; Ctrl-C to stop)"
  mosquitto_sub -h localhost -p "${port:-8883}" --cafile "$SECRETS/ca.crt" \
    --cert "$SECRETS/admin.crt" --key "$SECRETS/admin.key" -v -F '%I  %t  %p' \
    -t "unmsm/energy/v1/nodes/$node/#"
}

db() {
  local table="${1:-}" node="${2:-$NODE_DEFAULT}"
  [[ -n "$table" ]] || usage
  check_node "$node"
  docker exec -i "$INGESTION" python - "$table" "$node" <<'PY'
import os, sqlite3, sys
table, node = sys.argv[1], sys.argv[2]
QUERIES = {
    "node": ("select node_id, status, firmware_version, calibration_revision, last_seen_at, "
             "last_valid_observed_at from monitoring_node where node_id = ?"),
    "calibration": ("select calibration_revision, calibration_kind, voltage_gain, current_gain, "
                    "accepted_at, accepted_by from calibration_artifact where node_id = ? "
                    "order by rowid desc limit 5"),
    "threshold": ("select config_version, active_power_limit_w as limit_w, clear_below_w, "
                  "confirm_ms, clear_ms, severity, effective_at, created_by "
                  "from threshold_configuration where node_id = ? order by config_version desc"),
    "ledger": ("select substr(message_id, 1, 8) as msg, substr(boot_id, 1, 8) as boot, sequence, "
               "state, reject_code, ack_count, received_at, stored_at from ingestion_ledger "
               "where node_id = ? order by received_at desc limit 15"),
    "alert": ("select substr(alert_id, 1, 8) as alert, kind, severity, status, quality, "
              "observed_value, threshold_value, opened_at, acknowledged_at, resolved_at "
              "from alert where node_id = ? order by opened_at desc limit 10"),
    "transition": ("select substr(t.alert_id, 1, 8) as alert, t.from_status, t.to_status, "
                   "t.actor, t.reason, t.at from alert_transition t join alert a using (alert_id) "
                   "where a.node_id = ? order by t.transition_id desc limit 15"),
    "outbox": ("select substr(o.alert_id, 1, 8) as alert, o.destination_type, o.state, "
               "o.attempt_count, o.last_error_code, o.next_attempt_at, o.delivered_at "
               "from notification_outbox o join alert a using (alert_id) "
               "where a.node_id = ? order by a.opened_at desc limit 10"),
}
if table not in QUERIES:
    sys.exit(f"unknown table {table!r}; one of: {', '.join(QUERIES)}")
con = sqlite3.connect(f"file:{os.environ['SQLITE_PATH']}?mode=ro", uri=True)
cur = con.execute(QUERIES[table], (node,))
cols = [d[0] for d in cur.description]
rows = [["" if v is None else str(v) for v in r] for r in cur.fetchall()]
if not rows:
    print(f"({table}: no rows for {node})")
    sys.exit(0)
widths = [max(len(c), *(len(r[i]) for r in rows)) for i, c in enumerate(cols)]
print("  ".join(c.ljust(w) for c, w in zip(cols, widths)))
print("  ".join("-" * w for w in widths))
for r in rows:
    print("  ".join(v.ljust(w) for v, w in zip(r, widths)))
PY
}

counts() {
  local node="${1:-$NODE_DEFAULT}"; check_node "$node"
  docker exec -i "$INGESTION" python - "$node" <<'PY'
import os, sqlite3, sys
con = sqlite3.connect(f"file:{os.environ['SQLITE_PATH']}?mode=ro", uri=True)
rows = con.execute(
    "select state, coalesce(reject_code, '-'), count(*), sum(ack_count) from ingestion_ledger "
    "where node_id = ? group by 1, 2 order by 1, 2", (sys.argv[1],)).fetchall()
print(f"{'state':10} {'reject_code':24} {'messages':>8} {'acks':>6}")
for state, code, n, acks in rows:
    print(f"{state:10} {code:24} {n:8} {acks or 0:6}")
if not rows:
    print(f"(no ledger rows for {sys.argv[1]})")
PY
}

influx() {
  local view="${1:-}" node="${2:-$NODE_DEFAULT}" range="${3:-15m}"
  [[ -n "$view" ]] || usage
  check_node "$node"
  [[ "$range" =~ ^[0-9]+[smhd]$ ]] || { echo "bad range: $range (e.g. 15m, 2h, 8d)" >&2; exit 2; }
  local bucket measurement keep shape
  local pivot='|> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")'
  case "$view" in
    raw) bucket=energy_raw; measurement=electrical_measurement
         keep='"_time", "quality", "voltage_rms_V", "current_rms_A", "active_power_W", "active_energy_import_total_Wh", "quality_flags", "clock_source", "sequence"' ;;
    status) bucket=operations; measurement=node_status
         keep='"_time", "state", "acquisition_state", "clock_source", "pending_records", "last_measurement_age_s"' ;;
    ingest) bucket=operations; measurement=ingest_event
         # the tag is called `result`, which the influx CLI reads as its own result name
         pivot="$pivot |> rename(columns: {result: \"outcome\"})"
         keep='"_time", "outcome", "reason", "message_id"' ;;
    alerts) bucket=operations; measurement=alert_transition
         keep='"_time", "kind", "to_status", "from_status", "actor", "reason", "observed_value", "threshold_value", "notification_state", "event_observed_at"' ;;
    notifications) bucket=operations; measurement=alert_notification
         keep='"_time", "state", "attempt_count", "last_error_code", "alert_id"' ;;
    pipeline) bucket=operations; measurement=pipeline ;;
    *) echo "unknown view: $view" >&2; usage ;;
  esac
  if [[ "$view" == pipeline ]]; then
    # counters since the service started: the latest value of each one
    shape='|> last()
  |> group()
  |> keep(columns: ["_time", "_field", "_value"])
  |> sort(columns: ["_field"])'
    filter="r._measurement == \"pipeline\""
  else
    shape="$pivot
  |> group()
  |> keep(columns: [$keep])
  |> sort(columns: [\"_time\"], desc: true)
  |> limit(n: 15)"
    filter="r._measurement == \"$measurement\" and r.node_id == \"$node\""
  fi
  local query="from(bucket: \"$bucket\")
  |> range(start: -$range)
  |> filter(fn: (r) => $filter)
  $shape"
  INFLUX_TOKEN="$(cat "$SECRETS/influx-grafana-token")" \
    docker exec -i -e INFLUX_TOKEN "$INFLUX" influx query --org unmsm-energy - <<<"$query"
}

cmd="${1:-}"; shift || true
case "$cmd" in
  broker) broker "$@" ;;
  db) db "$@" ;;
  counts) counts "$@" ;;
  influx) influx "$@" ;;
  *) usage ;;
esac
