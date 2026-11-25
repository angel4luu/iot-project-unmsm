#!/usr/bin/env python3
"""Provision one node's credentials over a wired USB console (T030, research R-007).

Reads the ignored per-device manifest
`infrastructure/secrets/secrets.local.node-<node_id>.json`:

    {"node_id": "node-001", "wifi_ssid": "...", "wifi_password": "...",
     "mqtt_host": "...", "mqtt_port": 8883}

plus `ca.crt`, `node-<node_id>.crt`, and `node-<node_id>.key` from the same
directory, and sends them to a node waiting in provisioning mode (first boot, or
empty NVS). The node stores them in encrypted NVS. Values are hex-encoded on the
wire and never printed; `--dry-run` shows only keys and lengths.

    uv run --project services/ingestion python scripts/provision-node.py \
        --node-id node-001 --port /dev/ttyUSB0
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Protocol

REPO = Path(__file__).resolve().parents[1]
SECRETS = REPO / "infrastructure" / "secrets"
IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
# Wire keys in the order the firmware expects them (provisioning.h).
WIRE_KEYS = (
    "node_id",
    "wifi_ssid",
    "wifi_pass",
    "mqtt_host",
    "mqtt_port",
    "ca_cert",
    "node_cert",
    "node_key",
)
LIMITS = {"node_id": 32, "wifi_ssid": 32, "wifi_pass": 63, "mqtt_host": 253, "mqtt_port": 5}
PEM_MAX = 4096


class ManifestError(ValueError):
    pass


def load_values(node_id: str, secrets: Path = SECRETS) -> dict[str, str]:
    """Collect and validate every value to send (mirrors the firmware's checks)."""
    if not IDENTIFIER.fullmatch(node_id):
        raise ManifestError("node_id is not an identifier")
    manifest_path = secrets / f"secrets.local.node-{node_id}.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ManifestError(f"missing manifest {manifest_path.name}") from exc
    if manifest.get("node_id") != node_id:
        raise ManifestError("manifest node_id does not match --node-id")
    values = {
        "node_id": node_id,
        "wifi_ssid": str(manifest.get("wifi_ssid", "")),
        "wifi_pass": str(manifest.get("wifi_password", "")),
        "mqtt_host": str(manifest.get("mqtt_host", "")),
        "mqtt_port": str(manifest.get("mqtt_port", 8883)),
    }
    files = {
        "ca_cert": "ca.crt",
        "node_cert": f"node-{node_id}.crt",
        "node_key": f"node-{node_id}.key",
    }
    for key, name in files.items():
        path = secrets / name
        if not path.is_file():
            raise ManifestError(f"missing {name}; run `make dev-certs {node_id}`")
        values[key] = path.read_text(encoding="ascii")
    _validate(values)
    return values


def _validate(v: dict[str, str]) -> None:
    for key, limit in LIMITS.items():
        if not 1 <= len(v[key]) <= limit:
            raise ManifestError(f"{key} must be 1-{limit} characters")
    if len(v["wifi_pass"]) < 8:
        raise ManifestError("wifi_password must be 8-63 characters (WPA2)")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]*", v["mqtt_host"]):
        raise ManifestError("mqtt_host must be a host name")
    if not v["mqtt_port"].isdigit() or not 1 <= int(v["mqtt_port"]) <= 65535:
        raise ManifestError("mqtt_port must be 1-65535")
    for key in ("ca_cert", "node_cert"):
        if not v[key].startswith("-----BEGIN CERTIFICATE-----"):
            raise ManifestError(f"{key} is not a PEM certificate")
    if not (v["node_key"].startswith("-----BEGIN ") and "PRIVATE KEY-----" in v["node_key"]):
        raise ManifestError("node_key is not a PEM private key")
    for key in ("ca_cert", "node_cert", "node_key"):
        if len(v[key]) > PEM_MAX:
            raise ManifestError(f"{key} is larger than {PEM_MAX} bytes")
    if any("\x00" in value for value in v.values()):
        raise ManifestError("values must not contain NUL bytes")


def command_lines(values: dict[str, str]) -> list[str]:
    return [f"set {k} {values[k].encode().hex()}" for k in WIRE_KEYS] + ["commit"]


def redacted(line: str) -> str:
    parts = line.split(" ")
    if parts[0] == "set":
        return f"set {parts[1]} <{len(parts[2]) // 2} bytes>"
    return line


class Link(Protocol):
    def write(self, data: bytes) -> int | None: ...
    def readline(self) -> bytes: ...


def send(link: Link, lines: list[str], timeout_s: float = 10.0) -> None:
    """Send each line and require `PROV ok`; other console output is ignored."""
    for line in lines:
        link.write(line.encode("ascii") + b"\n")
        deadline = time.monotonic() + timeout_s
        while True:
            if time.monotonic() > deadline:
                raise TimeoutError(f"no reply to {redacted(line)}")
            reply = link.readline().decode("utf-8", "replace").strip()
            if reply.startswith("PROV "):
                break
        if reply != "PROV ok":
            raise RuntimeError(f"node refused {redacted(line)}: {reply.removeprefix('PROV ')}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--node-id", required=True)
    parser.add_argument("--port", help="serial device, e.g. /dev/ttyUSB0")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--dry-run", action="store_true", help="show keys and sizes only")
    args = parser.parse_args(argv)
    try:
        lines = command_lines(load_values(args.node_id))
    except ManifestError as exc:
        parser.error(str(exc))
    if args.dry_run or not args.port:
        for line in lines:
            print(redacted(line))
        return 0 if args.dry_run else parser.error("--port is required unless --dry-run")
    import serial  # only needed with a real port

    with serial.Serial(args.port, args.baud, timeout=1) as link:
        send(link, lines)
    print(f"{args.node_id}: provisioned (encrypted NVS)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
