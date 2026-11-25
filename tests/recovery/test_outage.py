"""T068: outage recovery against the live stack (SC-003, plan > Telemetry and Delivery).

`RecoveringNode` behaves like the firmware's RAM queue (T048/T069): every 5 s
summary is queued before it is sent, the queue holds 256 records and drops the
oldest when full, sending is oldest first with at most 10 unacknowledged, a
record leaves the queue only on an `accepted`/`duplicate` ACK (a `rejected` one
goes to diagnostics), and a record without an ACK after `ack_timeout_s` is sent
again (the server deduplicates).

- `test_outage_recovery` (SC-003): live for 1 min, then the MQTT connection is
  really closed for OUTAGE (env, default 10m; `make test-recovery OUTAGE=10m`)
  while summaries keep being queued, then it reconnects and drains while new
  summaries keep arriving. Pass: >= 99 % of the records retained during the
  outage are stored within 5 min of reconnection, none twice, and InfluxDB
  returns them in observation order. Evidence goes to the ignored
  `experiments/data/recovery/`.
- The other tests cover the listed edge cases quickly with recent timestamps:
  exact duplicates, conflicting IDs, out-of-order arrival, an ingestion restart,
  storage unavailable (InfluxDB paused), clock holdover, and a full queue.
"""

from __future__ import annotations

import json
import os
import secrets
import subprocess
import time
from collections import deque
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from tests import stack

from energy_ingestion.cli.simulate import SimulatedNode, parse_duration

pytestmark = pytest.mark.integration
NODE = "sim-001"  # the simulator certificate's identity
OUTAGE_S = int(parse_duration(os.environ.get("OUTAGE", "10m")).total_seconds())
WINDOW_S = 5
QUEUE_CAPACITY = 256
MAX_IN_FLIGHT = 10
RECOVERY_LIMIT_S = 300  # SC-003: within 5 min of reconnection
EVIDENCE = stack.REPO / "experiments" / "data" / "recovery"
TOPIC = f"unmsm/energy/v1/nodes/{NODE}/measurements"


# ---- a node-like publisher -------------------------------------------------------------


class RecoveringNode:
    def __init__(self, scenario: str, start: datetime, total_windows: int) -> None:
        self.sim = SimulatedNode(scenario, start, NODE, seed=secrets.randbits(32))
        self.total_s = float(total_windows * WINDOW_S)
        self.next_index = 0
        self.queue: deque[tuple[str, bytes]] = deque()
        self.dropped = 0
        self.sent_at: dict[str, float] = {}  # in flight: message_id -> monotonic send time
        self.acked: dict[str, tuple[str, float]] = {}  # message_id -> (status, monotonic)
        self.rejected: list[str] = []
        self.ack_timeout_s = 30.0

    @property
    def boot_id(self) -> str:
        return self.sim.boot_id

    def produce(self) -> str:
        doc, _ = self.sim.window(self.next_index, self.total_s)
        self.next_index += 1
        return self.enqueue(doc["message_id"], json.dumps(doc).encode())

    def enqueue(self, mid: str, raw: bytes) -> str:
        if len(self.queue) == QUEUE_CAPACITY:  # firmware: drop the oldest, count it
            old, _ = self.queue.popleft()
            self.sent_at.pop(old, None)
            self.dropped += 1
        self.queue.append((mid, raw))
        return mid

    def pump(self, link: stack.SimLink) -> None:
        """One firmware pump step: apply ACKs, resend stale, send oldest first."""
        now = time.monotonic()
        with link._cv:
            answered = {m: link.acks[m]["status"] for m in self.sent_at if m in link.acks}
        for mid, status in answered.items():
            self.acked[mid] = (status, now)
            if status == "rejected":
                self.rejected.append(mid)
            del self.sent_at[mid]
        if answered:
            self.queue = deque((m, r) for m, r in self.queue if m not in answered)
        for mid in [m for m, t in self.sent_at.items() if now - t >= self.ack_timeout_s]:
            del self.sent_at[mid]  # no ACK in time: sendable again
            with link._cv:
                link.acks.pop(mid, None)
        for mid, raw in self.queue:
            if len(self.sent_at) >= MAX_IN_FLIGHT:
                break
            if mid not in self.sent_at:
                link.publish(TOPIC, raw)
                self.sent_at[mid] = time.monotonic()

    def drain(self, link: stack.SimLink, timeout_s: float) -> bool:
        deadline = time.monotonic() + timeout_s
        while self.queue and time.monotonic() < deadline:
            self.pump(link)
            time.sleep(0.05)
        return not self.queue

    def lose_connection_state(self) -> None:
        """After a disconnect nothing is in flight; everything queued is resent."""
        self.sent_at.clear()


# ---- stack helpers ---------------------------------------------------------------------


def stored(boot_id: str, since: datetime) -> list[dict[str, str]]:
    """This boot's stored windows, in observation order."""
    start = (since - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return stack.flux(
        f'from(bucket: "energy_raw") |> range(start: {start}, stop: now())'
        ' |> filter(fn: (r) => r._measurement == "electrical_measurement"'
        f' and r.node_id == "{NODE}")'
        ' |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")'
        f' |> filter(fn: (r) => r.boot_id == "{boot_id}")'
        ' |> group() |> sort(columns: ["_time"])'
    )


def assert_chronological_once(rows: list[dict[str, str]]) -> None:
    ids = [r["message_id"] for r in rows]
    assert len(ids) == len(set(ids)), "a window was stored twice"
    seqs = [int(float(r["sequence"])) for r in rows]
    assert seqs == sorted(seqs), "observation order differs from sequence order"
    times = [r["_time"] for r in rows]
    assert times == sorted(times)


def docker(*args: str) -> None:
    subprocess.run(["docker", *args], check=True, capture_output=True, text=True)


def wait_healthy(container: str, timeout_s: float = 120) -> None:
    assert stack.wait_until(lambda: stack.health(container) == "healthy", timeout_s), container


def past_start(windows: int) -> datetime:
    """A start such that all `windows` summaries already ended (recent past)."""
    now = datetime.now(UTC).replace(microsecond=0)
    return now - timedelta(seconds=WINDOW_S * (windows + 2))


@pytest.fixture(scope="module", autouse=True)
def _stack() -> None:
    stack.require_stack()


# ---- SC-003 ----------------------------------------------------------------------------


def test_outage_recovery() -> None:
    pre_s, post_live_s = 60, 60
    total = (pre_s + OUTAGE_S + RECOVERY_LIMIT_S) // WINDOW_S + 10
    t0 = datetime.now(UTC).replace(microsecond=0)
    node = RecoveringNode("normal", t0, total)
    run_id = f"outage-{t0:%Y%m%dT%H%M%SZ}-{secrets.token_hex(2)}"

    def due() -> bool:  # the next window has ended in wall time
        end = t0 + timedelta(seconds=WINDOW_S * (node.next_index + 1))
        return datetime.now(UTC) >= end

    # 1. live
    with stack.sim_link(NODE) as link:
        until = time.monotonic() + pre_s
        while time.monotonic() < until:
            if due():
                node.produce()
            node.pump(link)
            time.sleep(0.05)
        node.drain(link, 30)
    node.lose_connection_state()

    # 2. outage: the connection is closed; summaries keep being queued
    outage_started = datetime.now(UTC)
    until = time.monotonic() + OUTAGE_S
    while time.monotonic() < until:
        if due():
            node.produce()
        time.sleep(0.2)
    retained = [m for m, _ in node.queue]
    assert node.dropped == 0, "a 10 min outage must fit in the 256-record queue"

    # 3. reconnect and drain while new summaries keep arriving
    with stack.sim_link(NODE) as link:
        reconnected = time.monotonic()
        recovered_at: float | None = None
        live_until = reconnected + RECOVERY_LIMIT_S
        while time.monotonic() < live_until:
            if due():
                node.produce()
            node.pump(link)
            done = [m for m in retained if m in node.acked]
            if recovered_at is None and len(done) == len(retained):
                recovered_at = time.monotonic()
            if recovered_at is not None and time.monotonic() - recovered_at > post_live_s:
                break
            time.sleep(0.05)
        node.drain(link, 30)

    within = [
        m
        for m in retained
        if m in node.acked
        and node.acked[m][0] in ("accepted", "duplicate")
        and node.acked[m][1] - reconnected <= RECOVERY_LIMIT_S
    ]
    rows = stored(node.boot_id, t0)
    stored_ids = {r["message_id"] for r in rows}
    share = len([m for m in within if m in stored_ids]) / len(retained) if retained else 0.0
    drain_s = (recovered_at - reconnected) if recovered_at else None
    summary = {
        "run_id": run_id,
        "outage_s": OUTAGE_S,
        "outage_started": outage_started.isoformat(timespec="seconds"),
        "retained_during_outage": len(retained),
        "stored_within_5_min_share": round(share, 4),
        "all_retained_acked_after_s": round(drain_s, 1) if drain_s is not None else None,
        "drain_rate_records_per_s": round(len(retained) / drain_s, 2) if drain_s else None,
        "stored_windows_total": len(rows),
        "duplicates_stored": len(rows) - len(stored_ids),
        "rejected": len(node.rejected),
        "dropped_by_queue": node.dropped,
        "note": "simulated node; values are not validated",
    }
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    Path(EVIDENCE / f"{run_id}.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary))

    assert len(retained) >= OUTAGE_S // WINDOW_S - 1
    assert share >= 0.99, summary
    assert_chronological_once(rows)
    assert drain_s is not None, summary
    assert len(retained) / max(drain_s, 1e-3) >= 2.0, summary


# ---- edge cases ------------------------------------------------------------------------


def test_exact_duplicate_is_stored_once() -> None:
    node = RecoveringNode("normal", past_start(1), 1)
    mid = node.produce()
    raw = node.queue[0][1]
    with stack.sim_link(NODE) as link:
        link.publish(TOPIC, raw)
        assert (link.wait_ack(mid) or {}).get("status") == "accepted"
        link.publish(TOPIC, raw)
        assert stack.wait_until(
            lambda: link.acks.get(mid + "#last", {}).get("status") == "duplicate", 15
        )
    assert len(stored(node.boot_id, node.sim.start)) == 1


def test_conflicting_id_is_rejected_and_original_kept() -> None:
    node = RecoveringNode("normal", past_start(1), 1)
    mid = node.produce()
    raw = node.queue[0][1]
    other = json.loads(raw)
    other["measurements"]["active_power"]["value"] = 99.0
    with stack.sim_link(NODE) as link:
        link.publish(TOPIC, raw)
        assert (link.wait_ack(mid) or {}).get("status") == "accepted"
        link.publish(TOPIC, json.dumps(other).encode())
        last = stack.wait_until(
            lambda: link.acks.get(mid + "#last", {}).get("status") == "rejected", 15
        )
        assert last
        assert link.acks[mid + "#last"]["reason_code"] == "identity_conflict"
    (row,) = stored(node.boot_id, node.sim.start)
    assert float(row["active_power_W"]) != 99.0


def test_out_of_order_arrival_is_stored_in_observation_order() -> None:
    node = RecoveringNode("normal", past_start(6), 6)
    for _ in range(6):
        node.produce()
    items = list(node.queue)
    with stack.sim_link(NODE) as link:
        for k in (3, 0, 5, 1, 4, 2):
            link.publish(TOPIC, items[k][1])
        for mid, _ in items:
            assert (link.wait_ack(mid) or {}).get("status") == "accepted"
    rows = stored(node.boot_id, node.sim.start)
    assert [int(float(r["sequence"])) for r in rows] == [0, 1, 2, 3, 4, 5]
    assert_chronological_once(rows)


def test_ingestion_restart_during_drain_loses_nothing() -> None:
    n = 40
    node = RecoveringNode("normal", past_start(n), n)
    for _ in range(n):
        node.produce()
    node.ack_timeout_s = 20
    with stack.sim_link(NODE) as link:
        for _ in range(20):  # get the drain going
            node.pump(link)
            time.sleep(0.05)
        docker("restart", stack.INGESTION)
        wait_healthy(stack.INGESTION)
        assert node.drain(link, 180), f"{len(node.queue)} records never acknowledged"
    rows = stored(node.boot_id, node.sim.start)
    assert len(rows) == n
    assert_chronological_once(rows)


def test_storage_unavailable_withholds_acks_then_recovers() -> None:
    n = 10
    node = RecoveringNode("normal", past_start(n), n)
    for _ in range(n):
        node.produce()
    node.ack_timeout_s = 20
    docker("pause", stack.INFLUXDB)
    try:
        with stack.sim_link(NODE) as link:
            node.pump(link)
            time.sleep(10)
            node.pump(link)
            assert not node.acked, "acknowledged while storage was down"
            docker("unpause", stack.INFLUXDB)
            assert node.drain(link, 180), f"{len(node.queue)} records never acknowledged"
    finally:
        subprocess.run(["docker", "unpause", stack.INFLUXDB], capture_output=True, check=False)
        wait_healthy(stack.INFLUXDB)
        wait_healthy(stack.INGESTION)
    rows = stored(node.boot_id, node.sim.start)
    assert len(rows) == n
    assert_chronological_once(rows)


def test_clock_holdover_windows_keep_their_clock_and_quality() -> None:
    n = 18  # sntp, then holdover, then unsynchronized thirds (simulator scenario)
    node = RecoveringNode("clock_holdover", past_start(n), n)
    for _ in range(n):
        node.produce()
    with stack.sim_link(NODE) as link:
        assert node.drain(link, 60)
    rows = stored(node.boot_id, node.sim.start)
    assert len(rows) == n
    assert_chronological_once(rows)
    by_clock: dict[str, set[str]] = {}
    for r in rows:
        by_clock.setdefault(r["clock_source"], set()).add(r["quality"])
    assert by_clock["sntp"] == {"valid"}
    assert by_clock["holdover"] == {"valid"}
    assert by_clock["unsynchronized"] == {"degraded"}
    assert all(
        "clock_unsynchronized" in r["quality_flags"] for r in rows if r["quality"] == "degraded"
    )


def test_full_queue_drops_oldest_and_the_gap_is_visible() -> None:
    n = QUEUE_CAPACITY + 44
    node = RecoveringNode("normal", past_start(n), n)
    for _ in range(n):
        node.produce()
    assert node.dropped == 44
    with stack.sim_link(NODE) as link:
        assert node.drain(link, 240), f"{len(node.queue)} records never acknowledged"
    rows = stored(node.boot_id, node.sim.start)
    seqs = [int(float(r["sequence"])) for r in rows]
    assert len(rows) == QUEUE_CAPACITY
    assert seqs == list(range(44, n))  # the 44 oldest are a visible sequence gap
    assert_chronological_once(rows)
