"""Node simulator (T024): schema-valid telemetry from a test identity, no hardware.

It behaves like one node on the plan B 12 V bulb loop: a measurement window every
5 s, a retained status every 30 s, and a retained last will marking it offline.
Every window carries a `nominal` calibration revision. Scenarios:

    normal          bulb on: ~12.6 V, ~1.62 A, ~20.4 W
    surge           one window above the limit every 60 s (shorter than confirm_ms)
    sustained       30 s above the limit every 2 min
    invalid         quality-invalid windows (nulls) and contract-invalid payloads
    outage          middle third offline; windows are queued and sent in order later
    duplicate       every window sent twice with the same identity and bytes
    out_of_order    adjacent windows swapped
    clock_holdover  SNTP, then holdover, then unsynchronized (degraded)

Usage: `make simulate SCENARIO=normal DURATION=10m`, or `--dry-run` to print the
payloads as JSON lines without a broker.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import re
import ssl
import sys
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from energy_ingestion.contracts.topics import topic_for

SCENARIOS = (
    "normal",
    "surge",
    "sustained",
    "invalid",
    "outage",
    "duplicate",
    "out_of_order",
    "clock_holdover",
)
WINDOW_S = 5
STATUS_EVERY_S = 30
SAMPLES_PER_WINDOW = 20_000
FIRMWARE_VERSION = "sim-0.1.0"
HARDWARE_REVISION = "simulator"
REPO = Path(__file__).resolve().parents[5]
SECRETS = REPO / "infrastructure" / "secrets"


@dataclass(frozen=True)
class Message:
    """One MQTT publication; `contract_valid` is False only for deliberate defects."""

    topic: str
    payload: bytes
    retain: bool
    at: datetime  # simulated send time
    kind: str  # schema name
    contract_valid: bool = True


def utc_ms(t: datetime) -> str:
    return t.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _dumps(doc: dict[str, Any]) -> bytes:
    return json.dumps(doc, separators=(",", ":"), allow_nan=False).encode()


def parse_duration(text: str) -> timedelta:
    m = re.fullmatch(r"(\d+)([smh])", text.strip())
    if not m:
        raise argparse.ArgumentTypeError("duration must look like 30s, 10m, or 1h")
    n, unit = int(m.group(1)), m.group(2)
    return timedelta(seconds=n * {"s": 1, "m": 60, "h": 3600}[unit])


@dataclass
class SimulatedNode:
    scenario: str
    start: datetime
    node_id: str = "sim-001"
    circuit_id: str = "sim-load-001"
    limit_w: float = 22.0
    seed: int = 1
    boot_id: str = field(default="")
    counter_id: str = field(default="")
    rng: random.Random = field(init=False)
    energy_wh: float = 0.0
    sequence: int = 0

    def __post_init__(self) -> None:
        if self.scenario not in SCENARIOS:
            raise ValueError(f"unknown scenario {self.scenario!r}")
        self.rng = random.Random(self.seed)  # noqa: S311 - simulation noise, not crypto
        self.boot_id = self.boot_id or str(uuid.UUID(int=self.rng.getrandbits(128), version=4))
        self.counter_id = self.counter_id or str(
            uuid.UUID(int=self.rng.getrandbits(128), version=4)
        )

    @property
    def calibration_revision(self) -> str:
        return f"{self.node_id}-nominal-r1"

    # ---- signal model -------------------------------------------------------------

    def _power_level(self, t_s: float) -> float:
        base = 20.4
        above = self.limit_w * 1.15
        if self.scenario == "surge" and int(t_s) % 60 == 30:
            return above
        if self.scenario == "sustained" and 60 <= int(t_s) % 120 < 90:
            return above
        return base

    def _clock(self, t_s: float, total_s: float) -> tuple[str, int | None]:
        if self.scenario != "clock_holdover":
            return "sntp", int(t_s) % 3600
        if t_s < total_s / 3:
            return "sntp", int(t_s) % 60
        if t_s < 2 * total_s / 3:
            return "holdover", int(t_s)
        return "unsynchronized", None

    # ---- payloads -----------------------------------------------------------------

    def _identity(self) -> dict[str, Any]:
        return {
            "message_id": str(uuid.UUID(int=self.rng.getrandbits(128), version=4)),
            "node_id": self.node_id,
            "circuit_id": self.circuit_id,
            "boot_id": self.boot_id,
            "sequence": self.sequence,
        }

    def window(self, index: int, total_s: float) -> tuple[dict[str, Any], bool]:
        """Window `index` as a measurement document and whether it is contract-valid."""
        t_s = index * WINDOW_S
        w_start = self.start + timedelta(seconds=t_s)
        w_end = w_start + timedelta(seconds=WINDOW_S)
        source, sync_age = self._clock(t_s, total_s)
        broken = self.scenario == "invalid" and index % 4 == 3
        power = self._power_level(t_s) * (1 + self.rng.gauss(0, 0.005))
        voltage = 12.6 * (1 + self.rng.gauss(0, 0.003))
        current = power / voltage  # resistive bulb: power factor 1
        flags: list[str] = []
        state = "valid"
        if self.scenario == "invalid" and index % 4 == 1:
            state, flags = "invalid", ["sensor_disconnected"]
        elif source == "unsynchronized":
            state, flags = "degraded", ["clock_unsynchronized"]
        values: dict[str, float | None]
        if state == "invalid":
            values = dict.fromkeys(("v", "i", "p", "e"))
        else:
            self.energy_wh += power * WINDOW_S / 3600
            values = {
                "v": round(voltage, 3),
                "i": round(current, 4),
                "p": round(power, 3),
                "e": round(self.energy_wh, 4),
            }
        doc: dict[str, Any] = {
            "schema_version": "1.0.0",
            **self._identity(),
            "window": {
                "start": utc_ms(w_start),
                "end": utc_ms(w_end),
                "duration_ms": WINDOW_S * 1000,
                "sample_count": SAMPLES_PER_WINDOW if state != "invalid" else 0,
            },
            "clock": {"source": source, "last_sync_age_s": sync_age},
            "measurements": {
                "voltage_rms": {"value": values["v"], "unit": "V"},
                "current_rms": {"value": values["i"], "unit": "A"},
                "active_power": {"value": values["p"], "unit": "W"},
                "active_energy_import_total": {
                    "value": values["e"],
                    "unit": "Wh",
                    "counter_id": self.counter_id,
                },
            },
            "quality": {
                "state": state,
                "flags": flags,
                "valid_sample_ratio": 1.0 if state == "valid" else 0.0,
                "calibration_revision": self.calibration_revision,
            },
            "uptime_ms": int((t_s + WINDOW_S) * 1000),
        }
        self.sequence += 1
        if broken:  # deliberate contract defects: missing unit and an unknown field
            del doc["measurements"]["voltage_rms"]["unit"]
            doc["unexpected"] = True
        assert math.isfinite(power)
        return doc, not broken

    def status(self, at: datetime, state: str = "online", pending: int = 0) -> dict[str, Any]:
        source, _ = self._clock((at - self.start).total_seconds(), 1e12)
        return {
            "schema_version": "1.0.0",
            "node_id": self.node_id,
            "boot_id": self.boot_id,
            "observed_at": utc_ms(at),
            "state": state,
            "firmware_version": FIRMWARE_VERSION,
            "hardware_revision": HARDWARE_REVISION,
            "calibration_revision": self.calibration_revision,
            "clock_source": source,
            "acquisition_state": "sampling" if state != "offline" else "stopped",
            "pending_records": pending,
            "oldest_pending_age_s": pending * WINDOW_S,
            "last_valid_window_end": None,
            "last_error_code": None,
        }

    def last_will(self) -> bytes:
        return _dumps(self.status(self.start, state="offline"))

    # ---- schedule -----------------------------------------------------------------

    def messages(self, duration: timedelta) -> Iterator[Message]:
        """Every publication of the run, in send order, with simulated send times."""
        total_s = duration.total_seconds()
        n = int(total_s // WINDOW_S)
        status_topic = topic_for(self.node_id, "status")
        meas_topic = topic_for(self.node_id, "measurements")
        outage = range(n // 3, 2 * n // 3) if self.scenario == "outage" else range(0)
        queued: list[Message] = []
        pending_swap: Message | None = None
        for i in range(n):
            at = self.start + timedelta(seconds=(i + 1) * WINDOW_S)
            if (i * WINDOW_S) % STATUS_EVERY_S == 0 and i not in outage:
                yield Message(
                    status_topic,
                    _dumps(self.status(at, pending=len(queued))),
                    True,
                    at,
                    "node-status",
                )
            doc, ok = self.window(i, total_s)
            msg = Message(meas_topic, _dumps(doc), False, at, "measurement", ok)
            if i in outage:
                queued.append(msg)
                continue
            if queued:  # reconnect: drain the queue in order, then continue live
                for q in queued:
                    yield Message(q.topic, q.payload, False, at, q.kind, q.contract_valid)
                queued.clear()
            if self.scenario == "out_of_order":
                if pending_swap is None:
                    pending_swap = msg
                    continue
                yield msg
                yield Message(pending_swap.topic, pending_swap.payload, False, at, "measurement")
                pending_swap = None
                continue
            yield msg
            if self.scenario == "duplicate":
                yield msg
        if pending_swap is not None:
            yield pending_swap
        for q in queued:
            yield q


# ---- broker publishing -----------------------------------------------------------


def _client(args: argparse.Namespace, node: SimulatedNode) -> Any:
    import paho.mqtt.client as mqtt

    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=node.node_id,
        protocol=mqtt.MQTTv5,
    )
    ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=str(args.ca))
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(certfile=str(args.cert), keyfile=str(args.key))
    client.tls_set_context(ctx)
    client.will_set(topic_for(node.node_id, "status"), node.last_will(), qos=1, retain=True)
    return client


def run_broker(args: argparse.Namespace, node: SimulatedNode) -> int:
    client = _client(args, node)
    acks: list[bytes] = []
    client.on_message = lambda _c, _u, msg: acks.append(msg.payload)
    client.connect(args.host, args.port, keepalive=30)
    client.subscribe(topic_for(node.node_id, "acks/measurements"), qos=1)
    client.loop_start()
    sent = 0
    t0 = time.monotonic()
    try:
        for msg in node.messages(args.duration):
            delay = (msg.at - node.start).total_seconds() - (time.monotonic() - t0)
            if delay > 0:
                time.sleep(delay)
            client.publish(msg.topic, msg.payload, qos=1, retain=msg.retain).wait_for_publish(10)
            sent += 1
    finally:
        client.publish(
            topic_for(node.node_id, "status"),
            json.dumps(node.status(datetime.now(UTC), state="offline")),
            qos=1,
            retain=True,
        ).wait_for_publish(10)
        client.loop_stop()
        client.disconnect()
    print(json.dumps({"scenario": args.scenario, "published": sent, "acks": len(acks)}))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="energy-simulate", description=__doc__.split("\n")[0])
    p.add_argument("--scenario", choices=SCENARIOS, default="normal")
    p.add_argument("--duration", type=parse_duration, default=parse_duration("10m"))
    p.add_argument("--node-id", default="sim-001")
    p.add_argument("--circuit-id", default="sim-load-001")
    p.add_argument("--limit-w", type=float, default=22.0, help="threshold the scenarios cross")
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--host", default=os.environ.get("MQTT_HOST", "localhost"))
    p.add_argument("--port", type=int, default=int(os.environ.get("MQTT_TLS_PORT", "8883")))
    p.add_argument("--ca", type=Path, default=SECRETS / "ca.crt")
    p.add_argument("--cert", type=Path, default=SECRETS / "simulator.crt")
    p.add_argument("--key", type=Path, default=SECRETS / "simulator.key")
    p.add_argument("--dry-run", action="store_true", help="print payloads; no broker")
    args = p.parse_args(argv)
    start = datetime.now(UTC).replace(microsecond=0)
    node = SimulatedNode(
        args.scenario, start, args.node_id, args.circuit_id, args.limit_w, args.seed
    )
    if args.dry_run:
        for msg in node.messages(args.duration):
            line = {"topic": msg.topic, "retain": msg.retain, "payload": json.loads(msg.payload)}
            sys.stdout.write(json.dumps(line) + "\n")
        return 0
    for f in (args.ca, args.cert, args.key):
        if not f.is_file():
            p.error(f"missing {f}; run `make dev-certs` first")
    return run_broker(args, node)


if __name__ == "__main__":
    sys.exit(main())
