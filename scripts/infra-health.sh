#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE=(docker compose -f "$ROOT/infrastructure/compose.yaml" -f "$ROOT/infrastructure/compose.lock.yaml" --env-file "$ROOT/.env")
SECRETS="$ROOT/infrastructure/secrets"
HOST="${DASHBOARD_HOSTNAME:-energy.lab.internal}"
LAN_BIND_ADDRESS="${LAN_BIND_ADDRESS:-127.0.0.1}"
FAILURES=0

check() {
  local name="$1"
  shift
  if "$@" >/dev/null 2>&1; then
    printf 'PASS %s\n' "$name"
  else
    printf 'FAIL %s\n' "$name"
    FAILURES=$((FAILURES + 1))
  fi
}

broker_id="$("${COMPOSE[@]}" ps -q mosquitto 2>/dev/null || true)"
if [[ -n "$broker_id" ]]; then
  check 'broker TLS/mTLS handshake' docker run --rm --network "container:$broker_id" \
    --user 0 -v "$SECRETS:/run/secrets:ro" --entrypoint mosquitto_sub \
    eclipse-mosquitto:2.1.2-alpine@sha256:75d6662dee52c947dc9dd9c29f1d8d7ffef78ddaf38001caa09755681e8bbc98 \
    -h localhost -p 8883 --cafile /run/secrets/ca.crt \
    --cert /run/secrets/admin.crt --key /run/secrets/admin.key \
    -V mqttv5 -t 'unmsm/energy/v1/#' -E
else
  printf 'FAIL broker TLS/mTLS handshake\n'
  FAILURES=$((FAILURES + 1))
fi
check 'InfluxDB /health' "${COMPOSE[@]}" exec -T influxdb \
  curl --fail --silent http://localhost:8086/health
caddy_id="$("${COMPOSE[@]}" ps -q caddy 2>/dev/null || true)"
if [[ -n "$caddy_id" ]] && [[ "$(docker inspect --format '{{.State.Status}}' "$caddy_id" 2>/dev/null || true)" == running ]]; then
  printf 'PASS Caddy container running\n'
  check 'Grafana /api/health via Caddy HTTPS' docker run --rm --network "container:$caddy_id" \
    --entrypoint curl influxdb:2.9.1@sha256:6682b6e798b7a5ca8688af3bba576f136f21d022a0796c59a723fc98879f14fd \
    --fail --silent --insecure --resolve "$HOST:443:127.0.0.1" "https://$HOST/api/health"
else
  printf 'FAIL Caddy container running\n'
  FAILURES=$((FAILURES + 1))
fi

ingestion_id="$("${COMPOSE[@]}" ps -q ingestion 2>/dev/null || true)"
if [[ -n "$ingestion_id" ]] && [[ "$(docker inspect --format '{{.State.Health.Status}}' "$ingestion_id" 2>/dev/null || true)" == healthy ]]; then
  printf 'PASS ingestion readiness\n'
else
  printf 'FAIL ingestion readiness\n'
  FAILURES=$((FAILURES + 1))
fi

# From the host, through the published ports, as the node and the browser reach them.
check "broker reachable on ${LAN_BIND_ADDRESS}:${MQTT_TLS_PORT:-8883} (host, mTLS)" \
  mosquitto_sub -h "$LAN_BIND_ADDRESS" -p "${MQTT_TLS_PORT:-8883}" --cafile "$SECRETS/ca.crt" \
  --cert "$SECRETS/admin.crt" --key "$SECRETS/admin.key" --insecure \
  `# --insecure skips only the host-name match (the LAN address varies); the chain is verified` \
  -V mqttv5 -t 'unmsm/energy/v1/#' -E
check "dashboard reachable on ${LAN_BIND_ADDRESS}:${HTTPS_PORT:-443} (host, HTTPS)" \
  curl --fail --silent --insecure --max-time 5 \
  --resolve "$HOST:${HTTPS_PORT:-443}:$LAN_BIND_ADDRESS" "https://$HOST:${HTTPS_PORT:-443}/api/health"

if ((FAILURES)); then
  printf '%d health check(s) failed.\n' "$FAILURES" >&2
  exit 1
fi
