"""T070: observation-time ordering and late-arrival handling.

Points are timestamped at `window.end`, never at arrival time, so a late or
out-of-order window lands at its own place in the series. A window older than the
raw retention can never be stored; it is rejected terminally (`outside_retention`)
instead of failing the write and stalling redelivery.
"""

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session, sessionmaker

from energy_ingestion.contracts.validate import contracts_dir, validate_payload
from energy_ingestion.mqtt.pipeline import IngestPipeline, utc_ms
from energy_ingestion.persistence.db import IngestionLedger
from energy_ingestion.persistence.influx import MAX_STORABLE_AGE, RAW_RETENTION
from tests.fakes import FakeClock, FakePublisher, FakeWriter

pytestmark = pytest.mark.unit
TOPIC = "unmsm/energy/v1/nodes/node-001/measurements"
BASE = json.loads((contracts_dir() / "examples" / "valid-measurement.json").read_text())
NOW = datetime(2026, 11, 25, 12, 0, 0, tzinfo=UTC)

Env = tuple[IngestPipeline, FakeWriter, FakePublisher, FakeClock]


@pytest.fixture
def env(sessions: sessionmaker[Session]) -> Env:
    writer, pub, clock = FakeWriter(), FakePublisher(), FakeClock(NOW)
    return IngestPipeline(sessions, writer, pub, clock=clock), writer, pub, clock


def window(end: datetime, seq: int, boot: str = "8f6c2b1e-1d2a-4c3b-9e8f-7a6b5c4d3e2f") -> bytes:
    doc = json.loads(json.dumps(BASE))
    doc["message_id"] = str(uuid.UUID(int=seq + 1, version=4))
    doc["boot_id"] = boot
    doc["sequence"] = seq
    doc["window"]["start"] = utc_ms(end - timedelta(seconds=5))
    doc["window"]["end"] = utc_ms(end)
    raw = json.dumps(doc).encode()
    validate_payload("measurement", raw)
    return raw


def point_times_ms(writer: FakeWriter) -> list[int]:
    return [
        int(line.rsplit(" ", 1)[1]) for line in writer.lines("energy_raw", "electrical_measurement")
    ]


def ack_statuses(pub: FakePublisher) -> list[tuple[str, str | None]]:
    out = []
    for topic, payload, _qos, _retain in pub.sent:
        if topic.endswith("/acks/measurements"):
            ack = json.loads(payload)
            out.append((ack["status"], ack["reason_code"]))
    return out


def ms(t: datetime) -> int:
    """Line-protocol time: milliseconds, the writer's precision."""
    return int(t.timestamp() * 1000)


def test_points_carry_observation_time_not_arrival_order(env: Env) -> None:
    pipe, writer, _pub, clock = env
    ends = [NOW - timedelta(seconds=s) for s in (15, 5, 10)]  # arrives out of order
    for k, end in enumerate(ends):
        clock.advance(1)
        assert pipe.handle(TOPIC, window(end, k)).result == "accepted"
    assert point_times_ms(writer) == [ms(e) for e in ends]
    assert sorted(point_times_ms(writer)) == [ms(e) for e in sorted(ends)]


def test_late_arrival_inside_retention_is_stored_at_its_window_end(env: Env) -> None:
    pipe, writer, pub, _clock = env
    end = NOW - timedelta(hours=26)  # longer than the node's 24 h message expiry
    assert pipe.handle(TOPIC, window(end, 1)).result == "accepted"
    (line,) = writer.lines("energy_raw", "electrical_measurement")
    assert line.endswith(f" {ms(end)}")
    assert f"receive_lag_ms={26 * 3600 * 1000}" in line
    assert ack_statuses(pub) == [("accepted", None)]


@pytest.mark.parametrize(
    ("age", "stored"),
    [
        (MAX_STORABLE_AGE - timedelta(seconds=1), True),
        (MAX_STORABLE_AGE + timedelta(seconds=1), False),
        (RAW_RETENTION + timedelta(days=1), False),
    ],
)
def test_retention_boundary(env: Env, age: timedelta, stored: bool) -> None:
    pipe, writer, pub, _clock = env
    out = pipe.handle(TOPIC, window(NOW - age, 1))
    assert (out.result == "accepted") is stored
    assert len(writer.lines("energy_raw", "electrical_measurement")) == (1 if stored else 0)
    assert ack_statuses(pub) == [
        ("accepted", None) if stored else ("rejected", "outside_retention")
    ]


def test_unsynchronized_uptime_timestamp_is_rejected_terminally(
    env: Env, sessions: sessionmaker[Session]
) -> None:
    """Before the first SNTP sync the node stamps windows with uptime (near 1970)."""
    pipe, writer, pub, _clock = env
    doc = json.loads(window(datetime(1970, 1, 1, 0, 0, 10, tzinfo=UTC), 1))
    doc["clock"] = {"source": "unsynchronized", "last_sync_age_s": None}
    doc["quality"]["state"] = "degraded"
    doc["quality"]["flags"] = ["clock_unsynchronized"]
    raw = json.dumps(doc).encode()
    assert pipe.handle(TOPIC, raw).reason == "outside_retention"
    assert pipe.handle(TOPIC, raw).result == "rejected"  # redelivery: same answer, no write
    assert writer.lines("energy_raw", "electrical_measurement") == []
    assert ack_statuses(pub) == [("rejected", "outside_retention")] * 2
    with sessions() as s:
        row = s.get(IngestionLedger, doc["message_id"])
        assert row is not None
        assert (row.state, row.reject_code) == ("rejected", "outside_retention")
    # one event; the redelivery is answered from the ledger
    (event,) = writer.lines("operations", "ingest_event")
    assert 'reason="outside_retention"' in event


def test_received_then_crash_then_beyond_retention_is_rejected(
    env: Env, sessions: sessionmaker[Session]
) -> None:
    """A RESUME whose window aged out meanwhile is rejected, not written."""
    pipe, writer, pub, clock = env
    raw = window(NOW - timedelta(days=1), 1)
    writer.fail = True
    with pytest.raises(ConnectionError):
        pipe.handle(TOPIC, raw)
    writer.fail = False
    clock.advance(timedelta(days=30).total_seconds())
    assert pipe.handle(TOPIC, raw).reason == "outside_retention"
    assert writer.lines("energy_raw", "electrical_measurement") == []
    assert ack_statuses(pub) == [("rejected", "outside_retention")]


def test_stored_message_redelivered_after_retention_is_still_a_duplicate(env: Env) -> None:
    pipe, _writer, pub, clock = env
    raw = window(NOW - timedelta(seconds=5), 1)
    assert pipe.handle(TOPIC, raw).result == "accepted"
    clock.advance(timedelta(days=31).total_seconds())
    assert pipe.handle(TOPIC, raw).result == "duplicate"
    assert [s for s, _ in ack_statuses(pub)] == ["accepted", "duplicate"]
