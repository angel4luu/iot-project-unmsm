"""T021-T022: constraints, triggers, ledger transitions, and the Influx point."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from energy_ingestion.contracts.models import Measurement, parse
from energy_ingestion.contracts.validate import contracts_dir
from energy_ingestion.persistence import ledger
from energy_ingestion.persistence.db import (
    Alert,
    AlertTransition,
    CalibrationArtifact,
    Circuit,
    MonitoringNode,
    ThresholdConfiguration,
    transaction,
)
from energy_ingestion.persistence.influx import TAG_KEYS, measurement_point

pytestmark = pytest.mark.unit
T0 = datetime(2026, 10, 14, 17, 0, tzinfo=UTC)
IDENT = ledger.MessageIdentity(
    "123e4567-e89b-42d3-a456-426614174000", "node-001", "123e4567-e89b-42d3-8456-426614174001", 42
)


def _node(s: Session, node_id: str = "node-001") -> None:
    s.add(
        MonitoringNode(
            node_id=node_id,
            display_name="Bench node",
            certificate_subject=f"CN={node_id}",
            hardware_revision="proto-a",
        )
    )
    s.flush()  # no ORM relationships, so order the FK parent explicitly
    s.add(Circuit(circuit_id="lab-load-001", node_id=node_id, display_name="12 V bulb loop"))


def _calibration(**over: object) -> CalibrationArtifact:
    fields: dict[str, object] = {
        "calibration_revision": "cal-node-001-r1",
        "node_id": "node-001",
        "hardware_revision": "proto-a",
        "firmware_commit": "0" * 40,
        "calibration_kind": "nominal",
        "reference_meter_id": None,
        "current_sensor_variant": "20A",
        "voltage_gain": Decimal("1.0"),
        "current_gain": Decimal("1.0"),
        "phase_correction_samples": Decimal("0.5"),
        "zero_noise_current_a": Decimal("0.05"),
        "procedure_version": "plausibility-v1",
        "dataset_manifest_sha256": "a" * 64,
    }
    fields.update(over)
    return CalibrationArtifact(**fields)


def test_circuit_defaults_follow_plan_b(sessions: sessionmaker[Session]) -> None:
    with transaction(sessions) as s:
        _node(s)
    with sessions() as s:
        c = s.get(Circuit, "lab-load-001")
        assert c is not None
        assert (c.nominal_voltage_v, c.calibrated_voltage_min_v, c.calibrated_voltage_max_v) == (
            12,
            10,
            16,
        )
        assert (c.calibrated_current_min_a, c.calibrated_current_max_a) == (
            Decimal("0.5"),
            Decimal("2.0"),
        )


@pytest.mark.parametrize("node_id", ["Node-001", "-node", "node_001", "n" * 33])
def test_node_id_format_is_enforced(sessions: sessionmaker[Session], node_id: str) -> None:
    with pytest.raises(IntegrityError), transaction(sessions) as s:
        s.add(
            MonitoringNode(
                node_id=node_id,
                display_name="x",
                certificate_subject=f"CN={node_id}",
                hardware_revision="a",
            )
        )


def test_nominal_calibration_has_no_reference_meter(sessions: sessionmaker[Session]) -> None:
    with transaction(sessions) as s:
        _node(s)
    with pytest.raises(IntegrityError), transaction(sessions) as s:
        s.add(_calibration(reference_meter_id="meter-1"))


def test_calibration_is_immutable_after_acceptance(sessions: sessionmaker[Session]) -> None:
    with transaction(sessions) as s:
        _node(s)
        s.add(_calibration())
    with transaction(sessions) as s:  # one-time acceptance is allowed
        cal = s.get(CalibrationArtifact, "cal-node-001-r1")
        assert cal is not None
        cal.accepted_at, cal.accepted_by = T0, "operator"
    with pytest.raises(DBAPIError, match="immutable"), transaction(sessions) as s:
        s.execute(text("UPDATE calibration_artifact SET voltage_gain = 1.1"))
    with pytest.raises(DBAPIError, match="append-only"), transaction(sessions) as s:
        s.execute(text("DELETE FROM calibration_artifact"))


def test_coefficients_cannot_change_before_acceptance(sessions: sessionmaker[Session]) -> None:
    with transaction(sessions) as s:
        _node(s)
        s.add(_calibration())
    with pytest.raises(DBAPIError, match="immutable"), transaction(sessions) as s:
        s.execute(text("UPDATE calibration_artifact SET current_gain = 2"))


@pytest.mark.parametrize(
    ("limit", "clear"),
    [(Decimal(0), Decimal(0)), (Decimal(26), Decimal(20)), (Decimal(15), Decimal(15))],
)
def test_threshold_ranges(sessions: sessionmaker[Session], limit: Decimal, clear: Decimal) -> None:
    with transaction(sessions) as s:
        _node(s)
    with pytest.raises(IntegrityError), transaction(sessions) as s:
        s.add(
            ThresholdConfiguration(
                node_id="node-001",
                config_version=1,
                circuit_id="lab-load-001",
                active_power_limit_w=limit,
                clear_below_w=clear,
                clear_ms=10000,
                severity="warning",
                local_warning_enabled=True,
                effective_at=T0,
                created_by="operator",
            )
        )


def test_alert_transitions_are_append_only(sessions: sessionmaker[Session]) -> None:
    with transaction(sessions) as s:
        s.add(
            Alert(
                alert_id="a" * 36,
                event_id="e" * 36,
                node_id="node-001",
                kind="node_offline",
                severity="warning",
                status="open",
                opened_at=T0,
            )
        )
        s.add(
            AlertTransition(
                alert_id="a" * 36, to_status="open", actor="system", reason="opened", at=T0
            )
        )
    for sql in ("UPDATE alert_transition SET reason = 'x'", "DELETE FROM alert_transition"):
        with pytest.raises(DBAPIError, match="append-only"), transaction(sessions) as s:
            s.execute(text(sql))


def test_naive_timestamps_are_refused(sessions: sessionmaker[Session]) -> None:
    alert = Alert(
        alert_id="b" * 36,
        event_id="f" * 36,
        node_id="node-001",
        kind="node_offline",
        severity="warning",
        status="open",
        opened_at=datetime(2026, 1, 1),
    )
    with sessions() as s:
        s.add(alert)
        with pytest.raises(Exception, match="timezone-aware"):
            s.flush()


# ---- ledger ----------------------------------------------------------------------


def test_ledger_new_then_stored_then_duplicate(sessions: sessionmaker[Session]) -> None:
    with transaction(sessions) as s:
        outcome, row = ledger.admit(s, IDENT, "1" * 64, T0)
        assert outcome is ledger.Admission.NEW
        assert row is not None
        ledger.mark_stored(row, T0 + timedelta(milliseconds=200))
        ledger.count_ack(row)
    with transaction(sessions) as s:
        outcome, row = ledger.admit(s, IDENT, "1" * 64, T0 + timedelta(seconds=5))
        assert outcome is ledger.Admission.DUPLICATE
        assert row is not None
        assert row.stored_at == T0 + timedelta(milliseconds=200)
        assert row.ack_count == 1


def test_ledger_resumes_after_crash_before_stored(sessions: sessionmaker[Session]) -> None:
    with transaction(sessions) as s:
        ledger.admit(s, IDENT, "1" * 64, T0)
    with transaction(sessions) as s:
        outcome, _ = ledger.admit(s, IDENT, "1" * 64, T0)
        assert outcome is ledger.Admission.RESUME


@pytest.mark.parametrize(
    "other",
    [
        IDENT,  # same identity, different bytes
        ledger.MessageIdentity(
            "223e4567-e89b-42d3-a456-426614174000", *list(vars(IDENT).values())[1:]
        ),
        ledger.MessageIdentity(IDENT.message_id, "node-001", IDENT.boot_id, 43),
    ],
)
def test_ledger_identity_conflict(
    sessions: sessionmaker[Session], other: ledger.MessageIdentity
) -> None:
    with transaction(sessions) as s:
        ledger.admit(s, IDENT, "1" * 64, T0)
    with transaction(sessions) as s:
        outcome, _ = ledger.admit(s, other, "2" * 64, T0)
        assert outcome is ledger.Admission.CONFLICT


def test_ledger_rejection_is_terminal(sessions: sessionmaker[Session]) -> None:
    with transaction(sessions) as s:
        row = ledger.record_rejection(s, IDENT, "1" * 64, T0, "schema_violation", "x" * 999)
        assert row.reject_detail is not None
        assert len(row.reject_detail) == ledger.MAX_DETAIL
    with transaction(sessions) as s:
        outcome, _ = ledger.admit(s, IDENT, "1" * 64, T0)
        assert outcome is ledger.Admission.REJECTED
    with pytest.raises(DBAPIError, match="terminal"), transaction(sessions) as s:
        s.execute(text("UPDATE ingestion_ledger SET state = 'received'"))


def test_stored_message_cannot_be_rejected(sessions: sessionmaker[Session]) -> None:
    with transaction(sessions) as s:
        _, row = ledger.admit(s, IDENT, "1" * 64, T0)
        assert row is not None
        ledger.mark_stored(row, T0)
    with pytest.raises(ValueError, match="stored"), transaction(sessions) as s:
        ledger.record_rejection(s, IDENT, "1" * 64, T0, "late")


def test_payload_hash_is_sha256() -> None:
    assert ledger.payload_sha256(b"") == (
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )


# ---- Influx point ----------------------------------------------------------------


def _measurement() -> Measurement:
    raw = (contracts_dir() / "examples" / "valid-measurement.json").read_bytes()
    return parse(Measurement, "measurement", raw)


def test_point_tags_are_exactly_the_four_series_tags() -> None:
    point = measurement_point(_measurement())
    assert set(point._tags) == TAG_KEYS


def test_point_is_deterministic_and_keyed_on_window_end() -> None:
    m = _measurement()
    line = measurement_point(m).to_line_protocol()
    assert line == measurement_point(m).to_line_protocol()
    end_ms = int(m.window.end.timestamp() * 1000)
    assert line.endswith(f" {end_ms}")
    assert "active_power_W=20.4" in line
    assert "message_id=" in line


def test_invalid_window_writes_no_quantity_fields() -> None:
    fixture = Path(contracts_dir() / "examples" / "valid-measurement.json").read_text()
    m = Measurement.model_validate_json(fixture)
    nulls = m.measurements.model_copy(
        update={
            k: getattr(m.measurements, k).model_copy(update={"value": None})
            for k in ("voltage_rms", "current_rms", "active_power", "active_energy_import_total")
        }
    )
    invalid = m.model_copy(update={"measurements": nulls})
    line = measurement_point(invalid).to_line_protocol()
    for field in ("voltage_rms_V", "current_rms_A", "active_power_W", "active_energy"):
        assert field not in line
