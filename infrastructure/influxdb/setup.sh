#!/usr/bin/env bash
set -euo pipefail

ORG=unmsm-energy
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
SECRETS_DIR="${SECRETS_DIR:-$ROOT/infrastructure/secrets}"
COMPOSE=(docker compose -f "$ROOT/infrastructure/compose.yaml" -f "$ROOT/infrastructure/compose.lock.yaml" --env-file "$ROOT/.env")

write_secret() {
  local path="$1"
  if [[ ! -s "$path" ]]; then
    openssl rand -hex 32 > "$path"
  fi
  chmod 0600 "$path"
}

prepare() {
  mkdir -p "$SECRETS_DIR"
  chmod 0700 "$SECRETS_DIR"
  write_secret "$SECRETS_DIR/influx-admin-password"
  write_secret "$SECRETS_DIR/influx-admin-token"
  for name in influx-ingestion-token influx-grafana-token; do
    if [[ ! -e "$SECRETS_DIR/$name" ]]; then
      install -m 0600 /dev/null "$SECRETS_DIR/$name"
    else
      chmod 0600 "$SECRETS_DIR/$name"
    fi
  done
  printf 'Prepared InfluxDB secret files in %s\n' "$SECRETS_DIR"
}

apply() {
  influx_cli() {
    "${COMPOSE[@]}" exec -T influxdb /bin/sh -c '
      export INFLUX_HOST=http://localhost:8086
      export INFLUX_ORG=unmsm-energy
      export INFLUX_TOKEN="$(cat /run/secrets/influx-admin-token)"
      exec influx "$@"
    ' influx-cli "$@"
  }

  local buckets
  buckets="$(influx_cli bucket list --org "$ORG" --json)"
  for bucket in energy_raw operations; do
    if ! python3 -c 'import json,sys; raise SystemExit(0 if any(item["name"] == sys.argv[1] for item in json.load(sys.stdin)) else 1)' "$bucket" <<< "$buckets"; then
      influx_cli bucket create --name "$bucket" --org "$ORG" --retention 720h >/dev/null
    fi
  done

  local raw_id operations_id
  buckets="$(influx_cli bucket list --org "$ORG" --json)"
  raw_id="$(python3 -c 'import json,sys; print(next(item["id"] for item in json.load(sys.stdin) if item["name"] == "energy_raw"))' <<< "$buckets")"
  operations_id="$(python3 -c 'import json,sys; print(next(item["id"] for item in json.load(sys.stdin) if item["name"] == "operations"))' <<< "$buckets")"
  [[ -n "$raw_id" && -n "$operations_id" ]] || { echo 'Unable to resolve bucket IDs' >&2; return 1; }

  ensure_auth() {
    local description="$1" secret_file="$2" permissions="$3"
    local auths response value temp_file
    auths="$(influx_cli auth list --org "$ORG" --json)"
    if ! python3 -c 'import json,sys; raise SystemExit(0 if any(item.get("description") == sys.argv[1] for item in json.load(sys.stdin)) else 1)' "$description" <<< "$auths"; then
      # The CLI generates the credential; capture it so it never reaches logs.
      # shellcheck disable=SC2086
      response="$(influx_cli auth create --org "$ORG" --description "$description" $permissions --json)"
      value="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["token"])' <<< "$response")"
      temp_file="$(mktemp "$SECRETS_DIR/.${secret_file}.XXXXXX")"
      printf '%s' "$value" > "$temp_file"
      chmod 0600 "$temp_file"
      mv -f "$temp_file" "$SECRETS_DIR/$secret_file"
    fi
  }
  ensure_auth energy-ingestion-write influx-ingestion-token "--write-bucket $raw_id --write-bucket $operations_id"
  ensure_auth energy-grafana-read influx-grafana-token "--read-bucket $raw_id --read-bucket $operations_id"
  printf 'InfluxDB buckets and scoped authorizations are ready.\n'
}

case "${1:---prepare}" in
  --prepare) prepare ;;
  --apply) apply ;;
  *) echo 'Usage: setup.sh [--prepare|--apply]' >&2; exit 2 ;;
esac
