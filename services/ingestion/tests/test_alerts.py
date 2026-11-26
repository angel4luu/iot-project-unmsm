"""T078: node events become audited alerts (plan, Threshold and alert lifecycle).

Lifecycle `open -> acknowledged -> resolved` (open may resolve directly), the
acknowledgment never clears the physical condition, `AlertTransition` is
append-only, a redelivered event is idempotent, every opened alert gets one
outbox row in the same transaction, and the event is cross-checked against the
stored configuration and the nearby measurements: disagreement opens a
`pipeline_health` alert and never changes the threshold alert silently.
"""

import json
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DatabaseError
from sqlalchemy.orm import Session, sessionmaker

from energy_ingestion.contracts.validate import contracts_dir, validate_payload
from energy_ingestion.mqtt.pipeline import IngestPipeline
from energy_ingestion.persistence.db import (
    Alert,
    AlertTransition,
    Circuit,
    MonitoringNode,
    NotificationOutbox,
    ThresholdConfiguration,
    transaction,
)
from energy_ingestion.thresholds import alerts
from tests.fakes import FakeClock, FakePublisher, FakeWriter

pytestmark = pytest.mark.unit
NODE = "node-001"
CIRCUIT = "lab-load-001"
EVENTS = f"unmsm/energy/v1/nodes/{NODE}/events"
MEASUREMENTS = f"unmsm/energy/v1/nodes/{NODE}/measurements"
BOOT = "123e4567-e89b-42d3-8456-426614174001"
T0 = datetime(2026, 11, 25, 15, 0, 0, tzinfo=UTC)

Env = tuple[IngestPipeline, FakeWriter, FakeClock]


@pytest.fixture
def env(sessions: sessionmaker[Session]) -> Env:
    with transaction(sessions) as s:
        s.add(
            MonitoringNode(
                node_id=NODE,
                display_name="Bench node",
                certificate_subject=f"CN={NODE}",
                hardware_revision="proto-a",
            )
        )
        s.flush()
        s.add(Circuit(circuit_id=CIRCUIT, node_id=NODE, display_name="12 V bulb loop"))
        s.flush()
        s.add(
            ThresholdConfiguration(
                node_id=NODE,
                config_version=3,
                circuit_id=CIRCUIT,
                active_power_limit_w=Decimal("15.000"),
                confirm_ms=10000,
                clear_below_w=Decimal("14.250"),
                clear_ms=5000,
                severity="warning",
                local_warning_enabled=True,
                effective_at=T0 - timedelta(days=1),
                created_by="operator",
            )
        )
    writer, clock = FakeWriter(), FakeClock(T0 + timedelta(seconds=30))
    return IngestPipeline(sessions, writer, FakePublisher(), clock=clock), writer, clock


_seq = iter(range(10_000))


def event(kind: str, at: datetime, **over: Any) -> bytes:
    doc: dict[str, Any] = {
        "schema_version": "1.0.0",
        "event_id": str(uuid.uuid4()),
        "node_id": NODE,
        "circuit_id": CIRCUIT,
        "boot_id": BOOT,
        "sequence": next(_seq),
        "observed_at": at.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "event_type": kind,
        "severity": "warning" if kind == "threshold_entered" else "info",
        "config_version": 3,
        "measured_value": 18.5 if kind == "threshold_entered" else 3.0,
        "threshold_value": 15.0 if kind == "threshold_entered" else 14.25,
        "unit": "W",
        "quality": "valid",
        "local_warning_active": kind == "threshold_entered",
        "reason_code": None,
    }
    if kind == "measurement_quality_changed":
        doc.update(measured_value=None, threshold_value=None, unit="none", quality="invalid")
        doc["severity"] = "warning"
        doc["reason_code"] = "sensor_disconnected"
    doc.update(over)
    raw = json.dumps(doc).encode()
    validate_payload("node-event", raw)
    return raw


def window(end: datetime, power: float, quality: str = "valid") -> bytes:
    """A stored 5 s window ending at `end` (asserted accepted by `store`)."""
    doc = json.loads((contracts_dir() / "examples" / "valid-measurement.json").read_text())
    doc["message_id"] = str(uuid.uuid4())
    doc["node_id"], doc["circuit_id"], doc["boot_id"] = NODE, CIRCUIT, BOOT
    doc["sequence"] = next(_seq)
    start = end - timedelta(seconds=5)
    doc["window"]["start"] = start.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    doc["window"]["end"] = end.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    doc["measurements"]["active_power"]["value"] = power
    doc["quality"]["state"] = quality
    doc["quality"]["flags"] = [] if quality == "valid" else ["out_of_range"]
    return json.dumps(doc).encode()


def store(pipe: IngestPipeline, raw: bytes) -> None:
    assert pipe.handle(MEASUREMENTS, raw).result == "accepted"


def rows(sessions: sessionmaker[Session], model: Any) -> list[Any]:
    with sessions() as s:
        return list(s.scalars(select(model)))


def history(sessions: sessionmaker[Session], alert_id: str) -> list[tuple[str | None, str]]:
    with sessions() as s:
        ts = s.scalars(
            select(AlertTransition)
            .where(AlertTransition.alert_id == alert_id)
            .order_by(AlertTransition.transition_id)
        )
        return [(t.from_status, t.to_status) for t in ts]


def only_alert(sessions: sessionmaker[Session], kind: str) -> Alert:
    (a,) = [a for a in rows(sessions, Alert) if a.kind == kind]
    return a


# ---- lifecycle -----------------------------------------------------------------------


def test_entered_opens_alert_with_evidence_and_one_outbox_row(
    env: Env, sessions: sessionmaker[Session]
) -> None:
    pipe, _, clock = env
    out = pipe.handle(EVENTS, event("threshold_entered", T0 + timedelta(seconds=20)))
    assert out.result == "opened"
    a = only_alert(sessions, "active_power_threshold")
    assert (a.status, a.severity, a.node_id, a.circuit_id) == ("open", "warning", NODE, CIRCUIT)
    assert (a.observed_value, a.threshold_value, a.unit, a.quality) == (18.5, 15.0, "W", "valid")
    assert a.opened_at == clock.now
    assert history(sessions, a.alert_id) == [(None, "open")]
    (box,) = rows(sessions, NotificationOutbox)
    assert (box.alert_id, box.destination_type, box.state, box.attempt_count) == (
        a.alert_id,
        "webhook",
        "pending",
        0,
    )
    assert box.next_attempt_at == a.opened_at
    uuid.UUID(box.delivery_id, version=4)
    assert not [x for x in rows(sessions, Alert) if x.kind == "pipeline_health"]


def test_open_resolves_directly_on_physical_clear(
    env: Env, sessions: sessionmaker[Session]
) -> None:
    pipe, _, _ = env
    pipe.handle(EVENTS, event("threshold_entered", T0 + timedelta(seconds=20)))
    out = pipe.handle(EVENTS, event("threshold_cleared", T0 + timedelta(seconds=40)))
    assert out.result == "resolved"
    a = only_alert(sessions, "active_power_threshold")
    assert a.status == "resolved"
    assert a.resolved_at is not None
    assert a.acknowledged_at is None
    assert history(sessions, a.alert_id) == [(None, "open"), ("open", "resolved")]
    assert len(rows(sessions, NotificationOutbox)) == 1  # resolution is not notified (MVP)


def test_acknowledgment_records_receipt_but_never_clears(
    env: Env, sessions: sessionmaker[Session]
) -> None:
    pipe, _, _ = env
    pipe.handle(EVENTS, event("threshold_entered", T0 + timedelta(seconds=20)))
    alert_id = only_alert(sessions, "active_power_threshold").alert_id
    with transaction(sessions) as s:
        a = alerts.acknowledge(s, alert_id, "operator", T0 + timedelta(seconds=50))
        assert a.status == "acknowledged"
    with transaction(sessions) as s:  # idempotent: no second transition
        alerts.acknowledge(s, alert_id, "operator", T0 + timedelta(seconds=55))
    a = only_alert(sessions, "active_power_threshold")
    assert a.status == "acknowledged"
    assert a.resolved_at is None
    assert a.acknowledged_at == T0 + timedelta(seconds=50)
    pipe.handle(EVENTS, event("threshold_cleared", T0 + timedelta(seconds=70)))
    a = only_alert(sessions, "active_power_threshold")
    assert a.status == "resolved"
    assert history(sessions, alert_id) == [
        (None, "open"),
        ("open", "acknowledged"),
        ("acknowledged", "resolved"),
    ]
    with sessions() as s:
        actors = [t.actor for t in s.scalars(select(AlertTransition))]
    assert actors == [f"node:{NODE}", "operator", f"node:{NODE}"]


def test_acknowledge_unknown_or_resolved(env: Env, sessions: sessionmaker[Session]) -> None:
    pipe, _, _ = env
    with transaction(sessions) as s, pytest.raises(KeyError):
        alerts.acknowledge(s, str(uuid.uuid4()), "operator", T0)
    pipe.handle(EVENTS, event("threshold_entered", T0 + timedelta(seconds=20)))
    pipe.handle(EVENTS, event("threshold_cleared", T0 + timedelta(seconds=40)))
    alert_id = only_alert(sessions, "active_power_threshold").alert_id
    with transaction(sessions) as s, pytest.raises(ValueError, match="resolved"):
        alerts.acknowledge(s, alert_id, "operator", T0 + timedelta(seconds=60))


def test_list_alerts_filters_by_status(env: Env, sessions: sessionmaker[Session]) -> None:
    pipe, _, clock = env
    pipe.handle(EVENTS, event("threshold_entered", T0 + timedelta(seconds=20)))
    pipe.handle(EVENTS, event("threshold_cleared", T0 + timedelta(seconds=40)))
    clock.advance(60)
    pipe.handle(EVENTS, event("threshold_entered", T0 + timedelta(seconds=90)))
    with sessions() as s:
        assert [a.status for a in alerts.list_alerts(s)] == ["open", "resolved"]  # newest first
        assert len(alerts.list_alerts(s, "open")) == 1
        assert len(alerts.list_alerts(s, "resolved")) == 1
        assert alerts.list_alerts(s, "acknowledged") == []
        with pytest.raises(ValueError, match="unknown status"):
            alerts.list_alerts(s, "closed")


def test_transitions_are_append_only(env: Env, sessions: sessionmaker[Session]) -> None:
    pipe, _, _ = env
    pipe.handle(EVENTS, event("threshold_entered", T0 + timedelta(seconds=20)))
    for sql in (
        "UPDATE alert_transition SET to_status = 'resolved'",
        "DELETE FROM alert_transition",
    ):
        with pytest.raises(DatabaseError, match="append-only"), transaction(sessions) as s:
            s.execute(text(sql))
    assert len(rows(sessions, AlertTransition)) == 1


def test_redelivered_event_is_idempotent(env: Env, sessions: sessionmaker[Session]) -> None:
    pipe, _, _ = env
    raw = event("threshold_entered", T0 + timedelta(seconds=20))
    pipe.handle(EVENTS, raw)
    assert pipe.handle(EVENTS, raw).result == "duplicate"
    cleared = event("threshold_cleared", T0 + timedelta(seconds=40))
    pipe.handle(EVENTS, cleared)
    assert pipe.handle(EVENTS, cleared).result == "ignored"  # nothing left to resolve
    assert len(rows(sessions, Alert)) == 1
    assert len(rows(sessions, AlertTransition)) == 2
    assert len(rows(sessions, NotificationOutbox)) == 1


def test_quality_event_opens_one_quality_alert_and_restoration_resolves_it(
    env: Env, sessions: sessionmaker[Session]
) -> None:
    pipe, _, _ = env
    assert pipe.handle(EVENTS, event("measurement_quality_changed", T0)).result == "opened"
    degraded = event(
        "measurement_quality_changed",
        T0 + timedelta(seconds=1),
        quality="degraded",
        reason_code="out_of_range",
    )
    assert pipe.handle(EVENTS, degraded).result == "ignored"  # already open for this node
    a = only_alert(sessions, "measurement_quality")
    assert (a.status, a.quality, a.observed_value, a.unit) == ("open", "invalid", None, None)
    restored = event(
        "measurement_quality_changed",
        T0 + timedelta(seconds=5),
        quality="valid",
        severity="info",
        reason_code="quality_restored",
    )
    assert pipe.handle(EVENTS, restored).result == "resolved"
    assert only_alert(sessions, "measurement_quality").status == "resolved"
    assert not [x for x in rows(sessions, Alert) if x.kind == "active_power_threshold"]


def test_invalid_event_payload_is_rejected_without_alert(
    env: Env, sessions: sessionmaker[Session]
) -> None:
    pipe, _, _ = env
    doc = json.loads(event("threshold_entered", T0))
    doc["event_type"] = "relay_opened"
    assert pipe.handle(EVENTS, json.dumps(doc).encode()).result == "rejected"
    assert rows(sessions, Alert) == []


# ---- cross-check -----------------------------------------------------------------------


def health(sessions: sessionmaker[Session]) -> list[Alert]:
    return [a for a in rows(sessions, Alert) if a.kind == "pipeline_health"]


def reasons(sessions: sessionmaker[Session], alert_id: str) -> list[str]:
    with sessions() as s:
        return [
            t.reason
            for t in s.scalars(select(AlertTransition).where(AlertTransition.alert_id == alert_id))
        ]


@pytest.mark.parametrize(
    ("over", "reason"),
    [
        ({"config_version": 9}, "config_unknown"),
        ({"threshold_value": 20.0}, "config_mismatch"),
        ({"measured_value": 14.0}, "value_not_above_limit"),
    ],
)
def test_config_or_value_disagreement_raises_a_health_alert(
    env: Env, sessions: sessionmaker[Session], over: dict[str, Any], reason: str
) -> None:
    pipe, _, _ = env
    raw = event("threshold_entered", T0 + timedelta(seconds=20), **over)
    pipe.handle(EVENTS, raw)
    a = only_alert(sessions, "active_power_threshold")  # the node's result is kept as sent
    assert (a.status, a.observed_value) == ("open", json.loads(raw)["measured_value"])
    (h,) = health(sessions)
    assert (h.status, h.severity, h.node_id) == ("open", "warning", NODE)
    assert reasons(sessions, h.alert_id) == [f"cross_check:{reason}"]
    assert len(rows(sessions, NotificationOutbox)) == 2  # the health alert is notified too
    pipe.handle(EVENTS, raw)  # redelivery: no second health alert
    assert len(health(sessions)) == 1


def test_nearby_measurements_that_agree_raise_nothing(
    env: Env, sessions: sessionmaker[Session]
) -> None:
    pipe, _, _ = env
    for k in range(4):  # 20 s above the limit before the event
        store(pipe, window(T0 + timedelta(seconds=5 * (k + 1)), 18.0))
    pipe.handle(EVENTS, event("threshold_entered", T0 + timedelta(seconds=20)))
    assert health(sessions) == []


def test_nearby_measurement_below_the_limit_disagrees(
    env: Env, sessions: sessionmaker[Session]
) -> None:
    pipe, _, _ = env
    for k in range(4):  # windows fully inside the confirmation span, all far below
        store(pipe, window(T0 + timedelta(seconds=5 * (k + 1)), 3.0))
    pipe.handle(EVENTS, event("threshold_entered", T0 + timedelta(seconds=20)))
    (h,) = health(sessions)
    assert reasons(sessions, h.alert_id) == ["cross_check:measurement_disagrees"]
    assert only_alert(sessions, "active_power_threshold").status == "open"


def test_windows_outside_the_span_or_not_valid_are_not_evidence(
    env: Env, sessions: sessionmaker[Session]
) -> None:
    pipe, _, _ = env
    store(pipe, window(T0 + timedelta(seconds=5), 3.0))  # before the 10 s span
    store(pipe, window(T0 + timedelta(seconds=15), 3.0, quality="degraded"))
    pipe.handle(EVENTS, event("threshold_entered", T0 + timedelta(seconds=20)))
    assert health(sessions) == []


def test_cleared_event_is_checked_against_the_clear_threshold(
    env: Env, sessions: sessionmaker[Session]
) -> None:
    pipe, _, _ = env
    pipe.handle(EVENTS, event("threshold_entered", T0 + timedelta(seconds=20)))
    pipe.handle(
        EVENTS, event("threshold_cleared", T0 + timedelta(seconds=40), threshold_value=15.0)
    )
    (h,) = health(sessions)
    assert reasons(sessions, h.alert_id) == ["cross_check:config_mismatch"]
    assert only_alert(sessions, "active_power_threshold").status == "resolved"


# ---- operations points (panel 7) ---------------------------------------------------------


def test_each_transition_writes_an_alert_transition_point(env: Env) -> None:
    pipe, writer, _ = env
    pipe.handle(EVENTS, event("threshold_entered", T0 + timedelta(seconds=20)))
    pipe.handle(EVENTS, event("threshold_cleared", T0 + timedelta(seconds=40)))
    lines = writer.lines("operations", "alert_transition")
    assert len(lines) == 2
    opened, resolved = lines
    for tag in (f"node_id={NODE}", "kind=active_power_threshold", "severity=warning"):
        assert tag in opened
    assert "to_status=open" in opened
    assert "to_status=resolved" in resolved
    assert 'notification_state="pending"' in opened
    assert 'from_status=""' in opened
    assert 'from_status="open"' in resolved
    assert "observed_value=18.5" in opened
    assert 'event_observed_at="2026-11-25T15:00:20.000Z"' in opened  # node time, for latency
    assert 'event_observed_at="2026-11-25T15:00:40.000Z"' in resolved
    assert "threshold_value=15" in opened


def test_acknowledge_with_writer_writes_the_point_after_commit(
    env: Env, sessions: sessionmaker[Session]
) -> None:
    pipe, _, _ = env
    pipe.handle(EVENTS, event("threshold_entered", T0 + timedelta(seconds=20)))
    alert_id = only_alert(sessions, "active_power_threshold").alert_id
    ops = FakeWriter()

    def ack_then_fail() -> None:
        with transaction(sessions) as s:
            alerts.acknowledge(s, alert_id, "operator", T0 + timedelta(seconds=50), writer=ops)
            raise RuntimeError

    with pytest.raises(RuntimeError):  # rolled back: no point
        ack_then_fail()
    assert ops.lines("operations", "alert_transition") == []
    with transaction(sessions) as s:
        alerts.acknowledge(s, alert_id, "operator", T0 + timedelta(seconds=50), writer=ops)
    (line,) = ops.lines("operations", "alert_transition")
    assert "to_status=acknowledged" in line
    assert 'actor="operator"' in line


def test_operations_write_failure_never_blocks_alert_handling(
    env: Env, sessions: sessionmaker[Session]
) -> None:
    pipe, writer, _ = env
    writer.fail = True
    assert pipe.handle(EVENTS, event("threshold_entered", T0 + timedelta(seconds=20))).result == (
        "opened"
    )
    assert only_alert(sessions, "active_power_threshold").status == "open"


def test_over_range_breach_opens_a_degraded_threshold_alert(
    env: Env, sessions: sessionmaker[Session]
) -> None:
    """FR-012 overload rule: the node confirmed on out-of-range readings."""
    pipe, _, _ = env
    raw = event(
        "threshold_entered", T0 + timedelta(seconds=20), measured_value=31.0, quality="degraded"
    )
    assert pipe.handle(EVENTS, raw).result == "opened"
    a = only_alert(sessions, "active_power_threshold")
    assert (a.status, a.quality, a.observed_value) == ("open", "degraded", 31.0)
    assert health(sessions) == []  # agrees with the stored config; not a disagreement
