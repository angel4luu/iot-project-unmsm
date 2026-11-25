"""T039: ingest pipeline validation, ledger transitions, and ACK rules."""

import json
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session, sessionmaker

from energy_ingestion.contracts.validate import contracts_dir, validate_payload
from energy_ingestion.mqtt.pipeline import IngestPipeline
from energy_ingestion.persistence.db import (
    CalibrationArtifact,
    IngestionLedger,
    MonitoringNode,
    transaction,
)
from tests.fakes import FakeClock, FakePublisher, FakeWriter

pytestmark = pytest.mark.unit
TOPIC = "unmsm/energy/v1/nodes/node-001/measurements"
ACK_TOPIC = "unmsm/energy/v1/nodes/node-001/acks/measurements"
VALID = (contracts_dir() / "examples" / "valid-measurement.json").read_bytes()
INVALID = (contracts_dir() / "examples" / "invalid-measurement.json").read_bytes()
MID = "123e4567-e89b-42d3-a456-426614174000"


Env = tuple[IngestPipeline, FakeWriter, FakePublisher]


@pytest.fixture
def env(sessions: sessionmaker[Session]) -> Env:
    writer, pub = FakeWriter(), FakePublisher()
    return IngestPipeline(sessions, writer, pub, clock=FakeClock()), writer, pub


def acks(pub: FakePublisher) -> list[dict[str, object]]:
    out = []
    for topic, payload, qos, retain in pub.sent:
        assert topic == ACK_TOPIC
        assert (qos, retain) == (1, False)
        validate_payload("measurement-ack", payload)
        out.append(json.loads(payload))
    return out


def ledger_row(sessions: sessionmaker[Session]) -> IngestionLedger:
    with sessions() as s:
        row = s.get(IngestionLedger, MID)
        assert row is not None
        return row


def test_new_measurement_is_stored_then_acknowledged(
    env: Env, sessions: sessionmaker[Session]
) -> None:
    pipe, writer, pub = env
    out = pipe.handle(TOPIC, VALID)
    assert out.result == "accepted"
    assert len(writer.lines("energy_raw", "electrical_measurement")) == 1
    (ack,) = acks(pub)
    assert ack["status"] == "accepted"
    assert ack["stored_at"]
    row = ledger_row(sessions)
    assert (row.state, row.ack_count) == ("stored", 1)


def test_retry_of_stored_message_is_duplicate_without_rewrite(
    env: Env, sessions: sessionmaker[Session]
) -> None:
    pipe, writer, pub = env
    pipe.handle(TOPIC, VALID)
    out = pipe.handle(TOPIC, VALID)
    assert out.result == "duplicate"
    assert len(writer.lines("energy_raw", "electrical_measurement")) == 1
    first, second = acks(pub)
    assert second["status"] == "duplicate"
    assert second["stored_at"] == first["stored_at"]
    assert ledger_row(sessions).ack_count == 2


def test_contract_violation_is_terminally_rejected(
    env: Env, sessions: sessionmaker[Session]
) -> None:
    pipe, writer, pub = env
    assert pipe.handle(TOPIC, INVALID).result == "rejected"
    assert pipe.handle(TOPIC, INVALID).result == "rejected"  # retry: same answer
    assert writer.lines("energy_raw", "electrical_measurement") == []
    a1, a2 = acks(pub)
    assert a1["status"] == a2["status"] == "rejected"
    assert a1["reason_code"] == "schema_violation"
    row = ledger_row(sessions)
    assert (row.state, row.reject_code, row.ack_count) == ("rejected", "schema_violation", 2)


def test_unidentifiable_garbage_gets_no_ack_but_an_event(env: Env) -> None:
    pipe, writer, pub = env
    assert pipe.handle(TOPIC, b"not json").result == "rejected"
    assert pub.sent == []
    (line,) = writer.lines("operations", "ingest_event")
    assert 'reason="invalid_json"' in line


def test_same_identity_with_other_bytes_is_a_conflict(
    env: Env, sessions: sessionmaker[Session]
) -> None:
    pipe, writer, pub = env
    pipe.handle(TOPIC, VALID)
    altered = VALID.replace(b"20.4", b"20.5")
    out = pipe.handle(TOPIC, altered)
    assert (out.result, out.reason) == ("conflict", "identity_conflict")
    assert acks(pub)[-1]["status"] == "rejected"
    assert len(writer.lines("energy_raw", "electrical_measurement")) == 1  # nothing overwritten
    assert ledger_row(sessions).state == "stored"
    assert writer.lines("operations", "ingest_event")
    assert pipe.metrics.totals["conflict"] == 1


def test_invalid_bytes_reusing_a_stored_identity_is_a_conflict(
    env: Env, sessions: sessionmaker[Session]
) -> None:
    pipe, _, _ = env
    pipe.handle(TOPIC, VALID)
    assert pipe.handle(TOPIC, INVALID).result == "conflict"
    assert ledger_row(sessions).state == "stored"


def test_payload_node_must_match_topic(env: Env) -> None:
    pipe, writer, pub = env
    out = pipe.handle(TOPIC.replace("node-001", "node-002"), VALID)
    assert (out.result, out.reason) == ("rejected", "identity_mismatch")
    assert writer.lines("energy_raw", "electrical_measurement") == []
    (topic, payload, _, _) = pub.sent[0]
    assert topic.endswith("/node-002/acks/measurements")  # only the sender hears about it
    assert json.loads(payload)["node_id"] == "node-002"


def test_no_ack_when_storage_fails_then_resume_on_redelivery(
    env: Env, sessions: sessionmaker[Session]
) -> None:
    pipe, writer, pub = env
    writer.fail = True
    with pytest.raises(ConnectionError):
        pipe.handle(TOPIC, VALID)
    assert pub.sent == []
    assert ledger_row(sessions).state == "received"
    writer.fail = False
    assert pipe.handle(TOPIC, VALID).result == "accepted"
    assert ledger_row(sessions).state == "stored"
    assert [a["status"] for a in acks(pub)] == ["accepted"]


@pytest.mark.parametrize(
    ("kind", "accepted", "label"),
    [
        (None, False, "not_validated"),
        ("nominal", True, "not_validated"),
        ("reference", False, "not_validated"),
        ("reference", True, "validated"),
    ],
)
def test_validation_label_comes_from_the_registry(
    sessions: sessionmaker[Session], kind: str | None, accepted: bool, label: str
) -> None:
    if kind is not None:
        with transaction(sessions) as s:
            s.add(
                MonitoringNode(
                    node_id="node-001",
                    display_name="n",
                    certificate_subject="CN=node-001",
                    hardware_revision="a",
                )
            )
            s.flush()
            s.add(
                CalibrationArtifact(
                    calibration_revision="cal-node-001-2026-10-14-r1",
                    node_id="node-001",
                    hardware_revision="a",
                    firmware_commit="0" * 40,
                    calibration_kind=kind,
                    reference_meter_id="meter-1" if kind == "reference" else None,
                    current_sensor_variant="20A",
                    voltage_gain=Decimal(1),
                    current_gain=Decimal(1),
                    phase_correction_samples=Decimal("0.5"),
                    zero_noise_current_a=Decimal("0.05"),
                    procedure_version="v1",
                    dataset_manifest_sha256="a" * 64,
                    accepted_at=FakeClock()() if accepted else None,
                    accepted_by="operator" if accepted else None,
                )
            )
    writer, pub = FakeWriter(), FakePublisher()
    IngestPipeline(sessions, writer, pub, clock=FakeClock()).handle(TOPIC, VALID)
    (line,) = writer.lines("energy_raw", "electrical_measurement")
    assert f'validation="{label}"' in line


def test_status_updates_tracker_and_writes_operations_point(env: Env) -> None:
    pipe, writer, _ = env
    raw = json.loads(
        (contracts_dir().parents[2] / "tests/fixtures/telemetry/valid-node-status.json").read_text()
    )
    out = pipe.handle("unmsm/energy/v1/nodes/node-001/status", json.dumps(raw).encode())
    assert out.result == "valid"
    assert "node-001" in pipe.tracker.nodes
    assert writer.lines("operations", "node_status")


def test_events_are_validated(env: Env) -> None:
    pipe, _, _ = env
    topic = "unmsm/energy/v1/nodes/node-001/events"
    assert pipe.handle(topic, b"{}").result == "rejected"


def test_unknown_topic_is_rejected(env: Env) -> None:
    pipe, _, pub = env
    assert pipe.handle("unmsm/energy/v1/nodes/node-001/config", VALID).result == "rejected"
    assert pipe.handle("elsewhere", VALID).result == "rejected"
    assert pub.sent == []


def test_metrics_count_every_result(env: Env) -> None:
    pipe, _, _ = env
    pipe.handle(TOPIC, VALID)
    pipe.handle(TOPIC, VALID)
    pipe.handle(TOPIC, b"x")
    snap = pipe.metrics.snapshot()
    assert (
        snap["received_total"],
        snap["accepted_total"],
        snap["duplicate_total"],
        snap["rejected_total"],
    ) == (3, 1, 1, 1)
    assert "ingest_latency_ms_p50" in snap


def test_first_measurement_writes_the_online_transition_at_once(env: Env) -> None:
    pipe, writer, _ = env
    pipe.handle(TOPIC, VALID)
    (line,) = writer.lines("operations", "node_status")
    assert 'state="online"' in line
    pipe.handle(TOPIC, VALID)  # duplicate: no transition, no extra point
    assert len(writer.lines("operations", "node_status")) == 1
