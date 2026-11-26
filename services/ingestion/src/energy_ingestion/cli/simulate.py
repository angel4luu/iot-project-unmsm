"""Node simulator (T024): schema-valid telemetry from a test identity, no hardware.

It behaves like one node on the plan B 12 V bulb loop: a measurement window every
5 s, a retained status every 30 s, and a retained last will marking it offline.
Every window carries a `nominal` calibration revision. Scenarios:

    normal          bulb on: ~12.6 V, ~1.62 A, ~20.4 W
    surge           3 s above the limit every 60 s (shorter than confirm_ms)
    sustained       30 s above the limit every 2 min
    alerts          T080 episodes in turn: sustained (confirm_ms + 2 s above), surge
                    (shorter than confirm_ms), and below the limit (0.9 x limit)
    invalid         quality-invalid windows (nulls) and contract-invalid payloads
    outage          middle third offline; windows are queued and sent in order later
    duplicate       every window sent twice with the same identity and bytes
    out_of_order    adjacent windows swapped
    clock_holdover  SNTP, then holdover, then unsynchronized (degraded)

The node evaluates every 1 s block with the local threshold state machine
(`thresholds/local.py`, the mirror of firmware threshold.c, configured like the
retained threshold config) and publishes its events on `.../events`: threshold
entered/cleared and measurement quality changes. A window's power is the mean of
its five blocks. The `history` scenario sends no events (its bytes stay fixed).

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
import secrets
import ssl
import sys
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from energy_ingestion.contracts.topics import topic_for
from energy_ingestion.thresholds.local import LocalEvent, LocalThreshold, State

SCENARIOS = (
    "normal",
    "surge",
    "sustained",
    "invalid",
    "outage",
    "duplicate",
    "out_of_order",
    "clock_holdover",
    "history",
    "alerts",
)
EPISODES = ("sustained", "surge", "below")
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
    confirm_ms: int = 10_000
    clear_ms: int = 5_000
    clear_below_w: float | None = None  # default: 95 % of the limit (plan)
    config_version: int = 1
    boot_id: str = field(default="")
    counter_id: str = field(default="")
    rng: random.Random = field(init=False)
    energy_wh: float = 0.0
    sequence: int = 0
    event_sequence: int = 0
    local: LocalThreshold = field(init=False)
    # (block end, state letter, local warning on) for every 1 s block: the simulated
    # node's own timing evidence for the local warning (T080).
    local_log: list[tuple[datetime, str, bool]] = field(default_factory=list, init=False)
    _blocks: list[float | None] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        if self.scenario not in SCENARIOS:
            raise ValueError(f"unknown scenario {self.scenario!r}")
        self.rng = random.Random(self.seed)  # noqa: S311 - simulation noise, not crypto
        # Separate stream, so events never shift the measurement payloads.
        self.event_rng = random.Random(self.seed ^ 0x5EED)  # noqa: S311
        if self.clear_below_w is None:
            self.clear_below_w = round(0.95 * self.limit_w, 3)
        self.local = LocalThreshold(
            self.limit_w, self.clear_below_w, self.confirm_ms, self.clear_ms
        )
        self.boot_id = self.boot_id or str(uuid.UUID(int=self.rng.getrandbits(128), version=4))
        self.counter_id = self.counter_id or str(
            uuid.UUID(int=self.rng.getrandbits(128), version=4)
        )

    @property
    def calibration_revision(self) -> str:
        return f"{self.node_id}-nominal-r1"

    # ---- signal model -------------------------------------------------------------

    @property
    def episode_s(self) -> int:
        """Length of one `alerts` episode: room to confirm, clear, and settle."""
        return math.ceil(self.confirm_ms / 1000) + math.ceil(self.clear_ms / 1000) + 5

    def episode(self, sec: int) -> tuple[int, str, int]:
        """(episode index, kind, second within it) of second `sec` in `alerts`."""
        k, offset = divmod(sec, self.episode_s)
        return k, EPISODES[k % len(EPISODES)], offset

    def _block_level(self, sec: int) -> float:
        """Noise-free power of the 1 s block starting `sec` seconds into the run."""
        above = self.limit_w * 1.15
        if self.scenario == "surge" and sec % 60 in (30, 31, 32):
            return above
        if self.scenario == "sustained" and 60 <= sec % 120 < 90:
            return above
        if self.scenario == "alerts":
            confirm_s = math.ceil(self.confirm_ms / 1000)
            _, kind, offset = self.episode(sec)
            if kind == "sustained" and offset < confirm_s + 2:
                return above
            if kind == "surge" and offset < max(1, confirm_s - 1):
                return above
            if kind == "below" and offset < confirm_s + 2:
                return 0.9 * self.limit_w
            return 0.6 * self.limit_w
        return 20.4

    def _block_levels(self, t_s: float) -> list[float]:
        return [self._block_level(int(t_s) + k) for k in range(WINDOW_S)]

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
        contract_broken = self.scenario == "invalid" and index % 4 == 3
        invalid = contract_broken
        local = w_start.astimezone(ZoneInfo("America/Lima"))
        history_peak = (
            self.scenario == "history"
            and local.date().isoformat() == "2026-11-19"
            and local.hour == 18
        )
        on = self._history_is_on(local) if self.scenario == "history" else True
        if self.scenario == "history" and index % 200 == self.seed % 200:
            invalid = True
        nominal_power = 24.0 if history_peak else 20.4
        levels = [nominal_power if on else 0.0] if self.scenario == "history" else []
        levels = levels or self._block_levels(t_s)
        noise = 1 + self.rng.gauss(0, 0.005)  # one draw per window: the stream is unchanged
        power = sum(levels) / len(levels) * noise
        self._blocks = [level * noise for level in levels]
        voltage = 12.6 * (1 + self.rng.gauss(0, 0.003))
        if history_peak:
            voltage = 14.0 * (1 + self.rng.gauss(0, 0.003))
        current = power / voltage  # resistive bulb: power factor 1
        flags: list[str] = []
        state = "valid"
        if self.scenario == "invalid" and index % 4 == 1:
            state, flags = "invalid", ["sensor_disconnected"]
        elif source == "unsynchronized":
            state, flags = "degraded", ["clock_unsynchronized"]
        elif self.scenario == "history" and invalid:
            state, flags = "invalid", ["sensor_disconnected"]
        values: dict[str, float | None]
        if state == "invalid":
            self._blocks = [None] * len(self._blocks)
            values = dict.fromkeys(("v", "i", "p", "e"))
        else:
            first_counter_reading = self.scenario == "history" and index in {
                0,
                int(total_s // WINDOW_S) // 2,
            }
            if not first_counter_reading:
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
        if contract_broken:  # deliberate contract defects: missing unit and an unknown field
            del doc["measurements"]["voltage_rms"]["unit"]
            doc["unexpected"] = True
        assert math.isfinite(power)
        return doc, not contract_broken

    @staticmethod
    def _history_is_on(local: datetime) -> bool:
        """Different Lima-local daily schedules, with a single full peak hour."""
        if local.date().isoformat() == "2026-11-19" and local.hour == 18:
            return True
        weekday = local.weekday()
        schedules = {
            0: ((6, 35), (7, 50), (17, 15), (21, 5)),
            1: ((6, 50), (8, 10), (16, 45), (20, 40)),
            2: ((7, 5), (8, 20), (17, 10), (21, 20)),
            3: ((6, 40), (8, 0), (16, 30), (20, 50)),
            4: ((7, 0), (8, 25), (17, 20), (22, 0)),
            5: ((8, 15), (10, 5), (18, 0), (22, 30)),
            6: ((9, 0), (10, 20), (17, 30), (20, 15)),
        }
        spans = schedules[weekday]
        minute = local.hour * 60 + local.minute
        return spans[0][0] * 60 + spans[0][1] <= minute < spans[1][0] * 60 + spans[1][1] or (
            spans[2][0] * 60 + spans[2][1] <= minute < spans[3][0] * 60 + spans[3][1]
        )

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

    def threshold_config(self, effective_at: datetime) -> dict[str, Any]:
        """The retained config this node evaluates with (threshold-config contract)."""
        return {
            "schema_version": "1.0.0",
            "config_version": self.config_version,
            "node_id": self.node_id,
            "circuit_id": self.circuit_id,
            "effective_at": utc_ms(effective_at),
            "active_power_limit_W": self.limit_w,
            "confirm_ms": self.confirm_ms,
            "clear_below_W": self.clear_below_w,
            "clear_ms": self.clear_ms,
            "severity": "warning",
            "local_warning_enabled": True,
        }

    def _event_doc(self, ev: LocalEvent, at: datetime) -> dict[str, Any]:
        doc = {
            "schema_version": "1.0.0",
            "event_id": str(uuid.UUID(int=self.event_rng.getrandbits(128), version=4)),
            "node_id": self.node_id,
            "circuit_id": self.circuit_id,
            "boot_id": self.boot_id,
            "sequence": self.event_sequence,
            "observed_at": utc_ms(at),
            "event_type": ev.event_type,
            "severity": ev.severity,
            "config_version": self.config_version,
            "measured_value": ev.measured_value,
            "threshold_value": ev.threshold_value,
            "unit": "W" if ev.measured_value is not None else "none",
            "quality": ev.quality,
            "local_warning_active": ev.local_warning_active,
            "reason_code": ev.reason_code,
        }
        self.event_sequence += 1
        return doc

    def evaluate_blocks(self, window_start: datetime) -> list[Message]:
        """Run the latest window's 1 s blocks through the local threshold."""
        out: list[Message] = []
        topic = topic_for(self.node_id, "events")
        for k, power in enumerate(self._blocks):
            at = window_start + timedelta(seconds=k + 1)
            for ev in self.local.step(None if power is None else round(power, 3)):
                out.append(Message(topic, _dumps(self._event_doc(ev, at)), False, at, "node-event"))
            self.local_log.append((at, State(self.local.state).value, self.local.warning_active))
        return out

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
        if self.scenario == "history":
            now = datetime.now(UTC)
            yield Message(status_topic, _dumps(self.status(now)), True, now, "node-status")
            midpoint = n // 2
            for i in range(n):
                at = self.start + timedelta(seconds=(i + 1) * WINDOW_S)
                if i == midpoint:
                    self.boot_id = str(uuid.UUID(int=self.rng.getrandbits(128), version=4))
                    self.counter_id = str(uuid.UUID(int=self.rng.getrandbits(128), version=4))
                    self.energy_wh = 0.0
                    self.sequence = 0
                doc, ok = self.window(i, total_s)
                yield Message(meas_topic, _dumps(doc), False, at, "measurement", ok)
            return
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
            events = self.evaluate_blocks(self.start + timedelta(seconds=i * WINDOW_S))
            msg = Message(meas_topic, _dumps(doc), False, at, "measurement", ok)
            if i in outage:
                queued.extend(events)
                queued.append(msg)
                continue
            yield from events  # each at its own block end, before the window
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
    import threading

    ack_condition = threading.Condition()

    def on_message(_client: Any, _userdata: Any, msg: Any) -> None:
        with ack_condition:
            acks.append(msg.payload)
            ack_condition.notify_all()

    client.on_message = on_message
    client.connect(args.host, args.port, keepalive=30)
    client.subscribe(topic_for(node.node_id, "acks/measurements"), qos=1)
    client.loop_start()
    sent = 0
    t0 = time.monotonic()
    try:
        if args.backfill:
            client.publish(
                topic_for(node.node_id, "status"),
                json.dumps(node.status(datetime.now(UTC))),
                qos=1,
                retain=True,
            ).wait_for_publish(10)
        in_flight: set[str] = set()
        for msg in node.messages(args.duration):
            delay = (msg.at - node.start).total_seconds() - (time.monotonic() - t0)
            if not args.backfill and delay > 0:
                time.sleep(delay)
            if args.backfill and msg.kind == "node-status":
                continue
            message_id = (
                json.loads(msg.payload).get("message_id") if msg.kind == "measurement" else None
            )
            while args.backfill and message_id is not None and len(in_flight) >= 100:
                with ack_condition:
                    acknowledged = {json.loads(a).get("message_id") for a in acks}
                    if not in_flight.intersection(acknowledged):
                        ack_condition.wait(timeout=30)
                        acknowledged = {json.loads(a).get("message_id") for a in acks}
                if not (in_flight & acknowledged):
                    raise TimeoutError("no application ACK received while backfilling")
                in_flight -= acknowledged
            client.publish(msg.topic, msg.payload, qos=1, retain=msg.retain).wait_for_publish(10)
            sent += 1
            if message_id is not None:
                in_flight.add(message_id)
        if args.backfill:
            deadline = time.monotonic() + 60
            while in_flight and time.monotonic() < deadline:
                with ack_condition:
                    ack_condition.wait(timeout=1)
                    acknowledged = {json.loads(a).get("message_id") for a in acks}
                in_flight -= acknowledged
            if in_flight:
                raise TimeoutError(f"{len(in_flight)} measurement application ACKs remain")
    finally:
        client.publish(
            topic_for(node.node_id, "status"),
            json.dumps(node.status(datetime.now(UTC), state="offline")),
            qos=1,
            retain=True,
        ).wait_for_publish(10)
        client.loop_stop()
        client.disconnect()
    print(
        json.dumps(
            {"scenario": args.scenario, "seed": args.seed, "published": sent, "acks": len(acks)}
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="energy-simulate", description=__doc__.split("\n")[0])
    p.add_argument("--scenario", choices=SCENARIOS, default="normal")
    p.add_argument("--duration", type=parse_duration, default=parse_duration("10m"))
    p.add_argument(
        "--start",
        type=lambda value: datetime.fromisoformat(value.replace("Z", "+00:00")),
        default=None,
        help="ISO 8601 UTC run start",
    )
    p.add_argument(
        "--backfill",
        action="store_true",
        help="publish historical windows as fast as application ACKs allow",
    )
    p.add_argument("--node-id", default="sim-001")
    p.add_argument("--circuit-id", default="sim-load-001")
    p.add_argument("--limit-w", type=float, default=22.0, help="threshold the scenarios cross")
    p.add_argument("--confirm-ms", type=int, default=10_000, help="local confirmation time")
    p.add_argument("--clear-ms", type=int, default=5_000, help="local clearing time")
    p.add_argument("--config-version", type=int, default=1, help="threshold config version")
    p.add_argument(
        "--seed",
        type=int,
        default=None,
        help="reproduce a run; default is a fresh seed, so every run is a new boot with new IDs",
    )
    p.add_argument("--host", default=os.environ.get("MQTT_HOST", "localhost"))
    p.add_argument("--port", type=int, default=int(os.environ.get("MQTT_TLS_PORT", "8883")))
    p.add_argument("--ca", type=Path, default=SECRETS / "ca.crt")
    p.add_argument("--cert", type=Path, default=SECRETS / "simulator.crt")
    p.add_argument("--key", type=Path, default=SECRETS / "simulator.key")
    p.add_argument("--dry-run", action="store_true", help="print payloads; no broker")
    args = p.parse_args(argv)
    start = args.start or datetime.now(UTC).replace(microsecond=0)
    if start.tzinfo is None or start.utcoffset() != timedelta(0):
        p.error("--start must be an ISO 8601 UTC timestamp")
    if args.seed is None:  # same seed = same message IDs: a rerun would be an identity conflict
        args.seed = secrets.randbits(32)
    node = SimulatedNode(
        args.scenario,
        start,
        args.node_id,
        args.circuit_id,
        args.limit_w,
        args.seed,
        confirm_ms=args.confirm_ms,
        clear_ms=args.clear_ms,
        config_version=args.config_version,
    )
    if args.dry_run:
        for msg in node.messages(args.duration):
            if args.scenario == "history" and msg.kind == "node-status":
                continue  # the measurement payload stream remains byte-for-byte reproducible
            line = {"topic": msg.topic, "retain": msg.retain, "payload": json.loads(msg.payload)}
            sys.stdout.write(json.dumps(line) + "\n")
        return 0
    for f in (args.ca, args.cert, args.key):
        if not f.is_file():
            p.error(f"missing {f}; run `make dev-certs` first")
    return run_broker(args, node)


if __name__ == "__main__":
    sys.exit(main())
