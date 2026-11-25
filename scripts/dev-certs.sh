#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
SECRETS="$ROOT/infrastructure/secrets"
FORCE=0
NODE_IDS=(node-001)

if [[ "${1:-}" == "--force" ]]; then
  FORCE=1
  shift
fi
if (($#)); then
  NODE_IDS=("$@")
fi

for node_id in "${NODE_IDS[@]}"; do
  if [[ ! "$node_id" =~ ^[a-z0-9][a-z0-9-]{0,31}$ ]]; then
    printf 'Invalid node ID: %s\n' "$node_id" >&2
    exit 2
  fi
done

mkdir -p "$SECRETS"
chmod 0700 "$SECRETS"

if [[ "$FORCE" -eq 1 ]]; then
  rm -f "$SECRETS"/{ca.key,ca.crt,broker.key,broker.crt,ingestion.key,ingestion.crt,admin.key,admin.crt,simulator.key,simulator.crt,node-*.key,node-*.crt}
fi

umask 077
if [[ ! -e "$SECRETS/ca.key" && ! -e "$SECRETS/ca.crt" ]]; then
  openssl ecparam -name prime256v1 -genkey -noout -out "$SECRETS/ca.key"
  openssl req -x509 -new -key "$SECRETS/ca.key" -sha256 -days 730 \
    -subj '/CN=UNMSM IoT Lab CA' \
    -addext 'basicConstraints=critical,CA:TRUE,pathlen:0' \
    -addext 'keyUsage=critical,keyCertSign,cRLSign' \
    -addext 'subjectKeyIdentifier=hash' -out "$SECRETS/ca.crt"
elif [[ ! -s "$SECRETS/ca.key" || ! -s "$SECRETS/ca.crt" ]]; then
  echo 'CA key/certificate pair is incomplete; restore both or rotate with --force.' >&2
  exit 1
fi

issue_cert() {
  local name="$1" common_name="$2" san="$3"
  local key="$SECRETS/$name.key" csr="$SECRETS/$name.csr" cert="$SECRETS/$name.crt"
  local ext="$SECRETS/$name.ext"
  if [[ -s "$key" && -s "$cert" ]]; then
    return
  elif [[ -e "$key" || -e "$cert" ]]; then
    printf 'Incomplete certificate pair for %s; refusing to overwrite it.\n' "$name" >&2
    return 1
  fi
  openssl ecparam -name prime256v1 -genkey -noout -out "$key"
  openssl req -new -key "$key" -subj "/CN=$common_name" -out "$csr"
  {
    printf 'basicConstraints=CA:FALSE\n'
    printf 'keyUsage=digitalSignature,keyAgreement\n'
    printf 'extendedKeyUsage=clientAuth,serverAuth\n'
    if [[ -n "$san" ]]; then
      printf 'subjectAltName=%s\n' "$san"
    fi
  } > "$ext"
  openssl x509 -req -in "$csr" -CA "$SECRETS/ca.crt" -CAkey "$SECRETS/ca.key" \
    -CAcreateserial -out "$cert" -days 365 -sha256 -extfile "$ext"
  rm -f "$csr" "$ext"
}

issue_cert broker mosquitto "DNS:mosquitto,DNS:${DASHBOARD_HOSTNAME:-energy.example.invalid},DNS:localhost,IP:127.0.0.1"
issue_cert ingestion svc-ingestion ""
issue_cert admin svc-admin ""
issue_cert simulator sim-001 ""
for node_id in "${NODE_IDS[@]}"; do
  issue_cert "node-$node_id" "$node_id" ""
done

if [[ ! -s "$SECRETS/grafana-admin-password" ]]; then
  openssl rand -hex 32 > "$SECRETS/grafana-admin-password"
fi
chmod 0600 "$SECRETS"/{ca.key,ca.crt,broker.key,broker.crt,ingestion.key,ingestion.crt,admin.key,admin.crt,simulator.key,simulator.crt,grafana-admin-password}
for cert_file in "$SECRETS"/node-*.key "$SECRETS"/node-*.crt; do
  [[ -e "$cert_file" ]] && chmod 0600 "$cert_file"
done
chmod 0700 "$SECRETS"
printf 'Created CA, broker/service/node certificates in %s\n' "$SECRETS"
