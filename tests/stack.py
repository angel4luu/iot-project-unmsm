"""Harness for tests against the running Compose stack (`make infra-up`).

Talks to the stack the way an operator would: MQTT over mutual TLS on the
published port (as the simulator identity), Flux through `influx` inside the
InfluxDB container (InfluxDB is not published), Grafana through Caddy on 443,
and `energyctl` inside the ingestion container. Secrets are read from the
ignored `infrastructure/secrets/` and never printed.
"""

from __future__ import annotations

import csv
import http.client
import io
import json
import os
import socket
import ssl
import subprocess
import threading
import time
from base64 import b64encode
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import paho.mqtt.client as mqtt

REPO = Path(__file__).resolve().parents[1]
SECRETS = REPO / "infrastructure" / "secrets"
PROJECT = "unmsm-energy"
INGESTION = f"{PROJECT}-ingestion-1"
INFLUXDB = f"{PROJECT}-influxdb-1"
ORG = "unmsm-energy"
DOCKER_INFLUX = ("docker", "exec", "-i", "-e", "INFLUX_TOKEN", INFLUXDB, "influx", "query")
ACK_TOPIC = "unmsm/energy/v1/nodes/{node}/acks/measurements"


def env() -> dict[str, str]:
    out: dict[str, str] = {}
    path = REPO / ".env"
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, _, value = line.partition("=")
                out[key.strip()] = value.strip()
    return {**out, **{k: v for k, v in os.environ.items() if k in out}}


def health(container: str) -> str:
    r = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Health.Status}}", container],
        capture_output=True,
        text=True,
        check=False,
    )
    return r.stdout.strip() if r.returncode == 0 else "missing"


def require_stack() -> None:
    down = [c for c in (INGESTION, INFLUXDB) if health(c) != "healthy"]
    if down:
        raise RuntimeError(f"stack not ready ({', '.join(down)}); run `make infra-up` first")


def wait_until(predicate: Any, timeout_s: float, every_s: float = 0.5) -> Any:
    deadline = time.monotonic() + timeout_s
    while True:
        value = predicate()
        if value or time.monotonic() > deadline:
            return value
        time.sleep(every_s)


# ---- InfluxDB --------------------------------------------------------------------


def flux(query: str) -> list[dict[str, str]]:
    """Run a Flux query; return every data row of every table as a dict."""
    token = (SECRETS / "influx-admin-token").read_text(encoding="utf-8").strip()
    r = subprocess.run(
        [*DOCKER_INFLUX, "--org", ORG, "--raw", "-"],
        input=query,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "INFLUX_TOKEN": token},
    )
    if r.returncode != 0:
        raise RuntimeError(f"flux failed: {r.stderr.strip()[:300]}")
    rows: list[dict[str, str]] = []
    header: list[str] | None = None
    for record in csv.reader(io.StringIO(r.stdout)):
        if not record or record[0].startswith("#"):
            header = None if not record else header
            continue
        if header is None:
            header = record
            continue
        rows.append(dict(zip(header, record, strict=False)))
    return rows


def raw_points(node: str, field: str, since: str = "-1h") -> list[dict[str, str]]:
    return flux(
        f'from(bucket: "energy_raw") |> range(start: {since})'
        f' |> filter(fn: (r) => r._measurement == "electrical_measurement"'
        f' and r.node_id == "{node}" and r._field == "{field}")'
        ' |> group() |> sort(columns: ["_time"])'
    )


# ---- ingestion container ---------------------------------------------------------


def energyctl(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", "exec", INGESTION, "energyctl", *args],
        capture_output=True,
        text=True,
        check=False,
    )


def ingestion_metrics() -> dict[str, Any]:
    code = "import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:8080/metrics').read().decode())"
    r = subprocess.run(
        ["docker", "exec", INGESTION, "python", "-c", code],
        capture_output=True,
        text=True,
        check=True,
    )
    result: dict[str, Any] = json.loads(r.stdout)
    return result


# ---- MQTT as the simulator -------------------------------------------------------


class SimLink:
    """mTLS connection with the simulator identity; collects application ACKs."""

    def __init__(self, node: str = "sim-001") -> None:
        e = env()
        self.node = node
        self.acks: dict[str, dict[str, Any]] = {}
        self._cv = threading.Condition()
        self.client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"{node}-test",
            protocol=mqtt.MQTTv5,
        )
        ctx = ssl.create_default_context(cafile=str(SECRETS / "ca.crt"))
        ctx.check_hostname = False  # the broker cert names the Compose host, not the LAN IP
        ctx.load_cert_chain(str(SECRETS / "simulator.crt"), str(SECRETS / "simulator.key"))
        self.client.tls_set_context(ctx)
        self.client.on_message = self._on_ack
        self.client.connect(
            e.get("LAN_BIND_ADDRESS", "127.0.0.1"), int(e.get("MQTT_TLS_PORT", "8883"))
        )
        self.client.subscribe(ACK_TOPIC.format(node=node), qos=1)
        self.client.loop_start()

    def _on_ack(self, _c: Any, _u: Any, msg: Any) -> None:
        ack = json.loads(msg.payload)
        with self._cv:
            self.acks.setdefault(ack["message_id"], ack)
            self.acks[ack["message_id"] + "#last"] = ack
            self._cv.notify_all()

    def publish(self, topic: str, payload: bytes, retain: bool = False) -> None:
        self.client.publish(topic, payload, qos=1, retain=retain).wait_for_publish(10)

    def wait_ack(self, message_id: str, timeout_s: float = 15) -> dict[str, Any] | None:
        with self._cv:
            self._cv.wait_for(lambda: message_id in self.acks, timeout=timeout_s)
            return self.acks.get(message_id)

    def close(self) -> None:
        self.client.loop_stop()
        self.client.disconnect()


@contextmanager
def sim_link(node: str = "sim-001") -> Iterator[SimLink]:
    link = SimLink(node)
    try:
        yield link
    finally:
        link.close()


# ---- Grafana through Caddy -------------------------------------------------------


class _PinnedHTTPS(http.client.HTTPSConnection):
    """HTTPS to a fixed address with the dashboard host name as SNI (like curl --resolve)."""

    def __init__(self, address: str, port: int, hostname: str, ctx: ssl.SSLContext) -> None:
        super().__init__(hostname, port, context=ctx, timeout=20)
        self._address = address
        self._ctx = ctx

    def connect(self) -> None:
        sock = socket.create_connection((self._address, self.port), self.timeout)
        self.sock = self._ctx.wrap_socket(sock, server_hostname=self.host)


class GrafanaError(RuntimeError):
    """An HTTP error from Grafana; `body` keeps its JSON answer (e.g. a query error)."""

    def __init__(self, message: str, body: bytes) -> None:
        super().__init__(message)
        self.body = body


def grafana(path: str, body: dict[str, Any] | None = None) -> Any:
    e = env()
    password = (SECRETS / "grafana-admin-password").read_text(encoding="utf-8").strip()
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE  # Caddy's internal CA; the test checks content, not TLS
    conn = _PinnedHTTPS(
        e.get("LAN_BIND_ADDRESS", "127.0.0.1"),
        int(e.get("HTTPS_PORT", "443")),
        e.get("DASHBOARD_HOSTNAME", "localhost"),
        ctx,
    )
    headers = {
        "Authorization": "Basic " + b64encode(f"operator:{password}".encode()).decode(),
        "Content-Type": "application/json",
    }
    try:
        conn.request(
            "GET" if body is None else "POST",
            path,
            body=None if body is None else json.dumps(body),
            headers=headers,
        )
        resp = conn.getresponse()
        data = resp.read()
        if resp.status >= 400:
            raise GrafanaError(f"grafana {path}: HTTP {resp.status}", data)
        return json.loads(data)
    finally:
        conn.close()
