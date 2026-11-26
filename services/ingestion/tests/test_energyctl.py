"""T099: `energyctl` node and calibration registration, and the 25 W threshold bound."""

import json
import sys
import types
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml
from sqlalchemy import select, text
from sqlalchemy.exc import DatabaseError
from sqlalchemy.orm import Session, sessionmaker

from energy_ingestion.cli.energyctl import main
from energy_ingestion.persistence.db import (
    Alert,
    CalibrationArtifact,
    MonitoringNode,
    ThresholdConfiguration,
)
from tests.conftest import REPO

pytestmark = pytest.mark.unit
EXAMPLE = REPO / "config" / "calibration.example.yaml"
THRESHOLD = REPO / "tests" / "fixtures" / "telemetry" / "valid-threshold-config.json"


def cli(capsys: pytest.CaptureFixture[str], db_url: str, *args: str) -> tuple[int, Any, str]:
    code = main(["--db", db_url, *args])
    out, err = capsys.readouterr()
    lines = [json.loads(line) for line in out.splitlines()]
    return code, lines, err


def register_node(capsys: pytest.CaptureFixture[str], db_url: str) -> None:
    code, _, _ = cli(
        capsys,
        db_url,
        "node",
        "register",
        "--node-id",
        "node-001",
        "--display-name",
        "Bench node",
        "--hardware-revision",
        "proto-a",
        "--circuit-id",
        "lab-load-001",
    )
    assert code == 0


def write_yaml(tmp_path: Path, doc: dict[str, Any], name: str = "f.yaml") -> Path:
    path = tmp_path / name
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    return path


def calibration(**changes: Any) -> dict[str, Any]:
    doc = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
    doc.update(changes)
    return {k: v for k, v in doc.items() if v is not ...}


# ---- nodes -----------------------------------------------------------------------


@pytest.mark.usefixtures("engine")
def test_node_register_creates_node_and_circuit(
    capsys: pytest.CaptureFixture[str], db_url: str, sessions: sessionmaker[Session]
) -> None:
    register_node(capsys, db_url)
    with sessions() as s:
        node = s.get(MonitoringNode, "node-001")
        assert node is not None
        assert node.certificate_subject == "CN=node-001"
        assert node.status == "provisioning"


@pytest.mark.usefixtures("engine")
def test_node_register_twice_fails(capsys: pytest.CaptureFixture[str], db_url: str) -> None:
    register_node(capsys, db_url)
    args = ["--node-id", "node-001", "--display-name", "x", "--hardware-revision", "a"]
    code = main(["--db", db_url, "node", "register", *args])
    assert code == 2
    assert "already exists" in capsys.readouterr().err


@pytest.mark.usefixtures("engine")
def test_node_id_format_is_checked(capsys: pytest.CaptureFixture[str], db_url: str) -> None:
    args = ["--node-id", "Node_1", "--display-name", "x", "--hardware-revision", "a"]
    code = main(["--db", db_url, "node", "register", *args])
    assert code == 2


# ---- calibration -----------------------------------------------------------------


@pytest.mark.usefixtures("engine")
def test_example_calibration_registers_as_nominal_not_validated(
    capsys: pytest.CaptureFixture[str], db_url: str, sessions: sessionmaker[Session]
) -> None:
    register_node(capsys, db_url)
    code, (out,), _ = cli(capsys, db_url, "calibration", "register", str(EXAMPLE))
    assert (code, out["kind"]) == (0, "nominal")
    code, (row,), _ = cli(capsys, db_url, "calibration", "list")
    assert row["validation"] == "not_validated"
    assert row["accepted_at"] is None
    with sessions() as s:
        cal = s.get(CalibrationArtifact, out["registered"])
        assert cal is not None
        assert cal.reference_meter_id is None


@pytest.mark.usefixtures("engine")
def test_accepting_nominal_keeps_it_not_validated(
    capsys: pytest.CaptureFixture[str], db_url: str, sessions: sessionmaker[Session]
) -> None:
    register_node(capsys, db_url)
    _, (out,), _ = cli(capsys, db_url, "calibration", "register", str(EXAMPLE))
    rev = out["registered"]
    code, (acc,), _ = cli(capsys, db_url, "calibration", "accept", rev, "--by", "operator A")
    assert (code, acc["validation"]) == (0, "not_validated")
    with sessions() as s:
        node = s.get(MonitoringNode, "node-001")
        assert node is not None
        assert node.calibration_revision == rev
    code, _, err = cli(capsys, db_url, "calibration", "accept", rev, "--by", "operator B")
    assert code == 2
    assert "already accepted" in err


@pytest.mark.usefixtures("engine")
def test_accepted_calibration_is_immutable_in_the_database(
    capsys: pytest.CaptureFixture[str], db_url: str, sessions: sessionmaker[Session]
) -> None:
    register_node(capsys, db_url)
    _, (out,), _ = cli(capsys, db_url, "calibration", "register", str(EXAMPLE))
    cli(capsys, db_url, "calibration", "accept", out["registered"], "--by", "operator A")
    with pytest.raises(DatabaseError), sessions() as s, s.begin():
        s.execute(text("UPDATE calibration_artifact SET accepted_by = 'someone else'"))


@pytest.mark.usefixtures("engine")
def test_revisions_cannot_be_registered_twice(
    capsys: pytest.CaptureFixture[str], db_url: str
) -> None:
    register_node(capsys, db_url)
    cli(capsys, db_url, "calibration", "register", str(EXAMPLE))
    code, _, err = cli(capsys, db_url, "calibration", "register", str(EXAMPLE))
    assert code == 2
    assert "immutable" in err


@pytest.mark.usefixtures("engine")
def test_calibration_needs_a_registered_node(
    capsys: pytest.CaptureFixture[str], db_url: str
) -> None:
    code, _, err = cli(capsys, db_url, "calibration", "register", str(EXAMPLE))
    assert code == 2
    assert "not registered" in err


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"surprise": 1}, "unknown calibration fields"),
        ({"current_gain": ...}, "missing calibration fields"),
        ({"calibration_kind": "reference"}, "reference_meter_id"),
        ({"reference_meter_id": "meter-1"}, "reference_meter_id"),
        ({"current_sensor_variant": "50A"}, "current_sensor_variant"),
        ({"voltage_gain": 0}, "voltage_gain"),
        ({"current_gain": "nan"}, "finite"),
        ({"current_gain": True}, "number"),
        ({"dataset_manifest_sha256": "abc"}, "dataset_manifest_sha256"),
        ({"firmware_commit": "HEAD"}, "firmware_commit"),
        ({"phase_correction_samples": 9}, "phase_correction_samples"),
    ],
)
@pytest.mark.usefixtures("engine")
def test_invalid_calibration_files_are_refused(
    capsys: pytest.CaptureFixture[str],
    db_url: str,
    tmp_path: Path,
    changes: dict[str, Any],
    message: str,
) -> None:
    register_node(capsys, db_url)
    path = write_yaml(tmp_path, calibration(**changes))
    code, out, err = cli(capsys, db_url, "calibration", "register", str(path))
    assert (code, out) == (2, [])
    assert message in err


# ---- thresholds ------------------------------------------------------------------


def threshold(**changes: Any) -> dict[str, Any]:
    doc = json.loads(THRESHOLD.read_text(encoding="utf-8"))
    doc.update(changes)
    return dict(doc)


def test_valid_threshold_file_passes(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    path = write_yaml(tmp_path, threshold())
    assert main(["threshold", "validate", str(path)]) == 0
    assert json.loads(capsys.readouterr().out)["limit_W"] == 15.0


def test_yaml_timestamp_is_accepted(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    path = tmp_path / "t.yaml"
    body = yaml.safe_dump(threshold()).replace(
        "'2026-10-14T17:00:00.000Z'", "2026-10-14T17:00:00.000Z"
    )
    path.write_text(body, encoding="utf-8")
    assert main(["threshold", "validate", str(path)]) == 0


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"active_power_limit_W": 25.5}, "above the MVP bound of 25 W"),
        ({"active_power_limit_W": 400.0}, "above the MVP bound of 25 W"),
        ({"clear_below_W": 15.0}, "clear_below_W"),
        ({"active_power_limit_W": 0}, "schema_violation"),
        ({"severity": "panic"}, "schema_violation"),
    ],
)
def test_threshold_bounds(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, changes: dict[str, Any], message: str
) -> None:
    path = write_yaml(tmp_path, threshold(**changes))
    assert main(["threshold", "validate", str(path)]) == 2
    assert message in capsys.readouterr().err


def test_limit_of_exactly_25_w_is_allowed(tmp_path: Path) -> None:
    path = write_yaml(tmp_path, threshold(active_power_limit_W=25.0))
    assert main(["threshold", "validate", str(path)]) == 0


def test_unreadable_files_are_usage_errors(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    assert main(["threshold", "validate", str(tmp_path / "missing.yaml")]) == 2
    bad = tmp_path / "bad.yaml"
    bad.write_text("[1, 2", encoding="utf-8")
    assert main(["threshold", "validate", str(bad)]) == 2
    assert "invalid YAML" in capsys.readouterr().err


@pytest.mark.usefixtures("engine")
def test_threshold_publish_stores_latest_config_and_publishes_retained_payload(
    capsys: pytest.CaptureFixture[str],
    db_url: str,
    tmp_path: Path,
    sessions: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    register_node(capsys, db_url)
    path = write_yaml(tmp_path, threshold())
    sent: list[tuple[str, bytes]] = []
    from energy_ingestion.cli import energyctl

    monkeypatch.setattr(
        energyctl,
        "publish_threshold_config",
        lambda node, payload: sent.append((node, payload)),
    )

    code = main(["--db", db_url, "threshold", "publish", str(path), "--by", "operator A"])

    out = json.loads(capsys.readouterr().out)
    assert code == 0
    assert out["stored"] is True
    assert out["published"] is True
    assert out["created_by"] == "operator A"
    assert sent[0][0] == "node-001"
    payload = json.loads(sent[0][1])
    assert payload["config_version"] == 1
    assert payload["active_power_limit_W"] == 15.0
    assert payload["clear_below_W"] == 12.0
    with sessions() as session:
        row = session.get(ThresholdConfiguration, ("node-001", 1))
        assert row is not None
        assert row.created_by == "operator A"
        assert row.local_warning_enabled is True


@pytest.mark.usefixtures("engine")
def test_threshold_publish_requires_strictly_increasing_version(
    capsys: pytest.CaptureFixture[str],
    db_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    register_node(capsys, db_url)
    published: list[int] = []
    from energy_ingestion.cli import energyctl

    monkeypatch.setattr(
        energyctl,
        "publish_threshold_config",
        lambda _node, payload: published.append(json.loads(payload)["config_version"]),
    )
    v1 = write_yaml(tmp_path, threshold())
    assert main(["--db", db_url, "threshold", "publish", str(v1), "--by", "op"]) == 0
    capsys.readouterr()
    duplicate = write_yaml(tmp_path, threshold(config_version=1), "duplicate.yaml")
    assert main(["--db", db_url, "threshold", "publish", str(duplicate), "--by", "op"]) == 2
    assert "greater than stored version" in capsys.readouterr().err
    v2 = write_yaml(tmp_path, threshold(config_version=2), "v2.yaml")
    assert main(["--db", db_url, "threshold", "publish", str(v2), "--by", "op"]) == 0
    assert published == [1, 2]


@pytest.mark.usefixtures("engine")
def test_threshold_show_returns_latest_stored_version(
    capsys: pytest.CaptureFixture[str],
    db_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    register_node(capsys, db_url)
    from energy_ingestion.cli import energyctl

    monkeypatch.setattr(energyctl, "publish_threshold_config", lambda _node, _payload: None)
    for version in (1, 2):
        path = write_yaml(tmp_path, threshold(config_version=version), f"v{version}.yaml")
        assert main(["--db", db_url, "threshold", "publish", str(path), "--by", "operator"]) == 0
        capsys.readouterr()

    assert main(["--db", db_url, "threshold", "show", "node-001"]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["config_version"] == 2
    assert shown["active_power_limit_W"] == "15.000"


def install_alerts_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    module = types.ModuleType("energy_ingestion.thresholds.alerts")

    def list_alerts(session: Session, status: str | None = None) -> list[Alert]:
        query = select(Alert).order_by(Alert.opened_at)
        if status is not None:
            query = query.where(Alert.status == status)
        return list(session.scalars(query))

    def acknowledge(session: Session, alert_id: str, actor: str, now: datetime) -> Alert:
        alert = session.get(Alert, alert_id)
        if alert is None:
            raise KeyError(alert_id)
        if alert.status == "resolved":
            raise ValueError(alert_id)
        alert.status = "acknowledged"
        alert.acknowledged_at = now
        return alert

    module.list_alerts = list_alerts  # type: ignore[attr-defined]
    module.acknowledge = acknowledge  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "energy_ingestion.thresholds.alerts", module)


@pytest.mark.usefixtures("engine")
def test_alert_list_filters_status_through_alerts_module(
    capsys: pytest.CaptureFixture[str],
    db_url: str,
    sessions: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    register_node(capsys, db_url)
    install_alerts_stub(monkeypatch)
    with sessions.begin() as session:
        for index, status in enumerate(("open", "resolved")):
            session.add(
                Alert(
                    alert_id=f"e7c3e07a-4cc9-45c4-a13a-00000000000{index}",
                    event_id=f"7df2d150-b153-49a1-8663-00000000000{index}",
                    node_id="node-001",
                    circuit_id="lab-load-001",
                    kind="active_power_threshold",
                    severity="warning",
                    status=status,
                    opened_at=datetime(2026, 11, 25, tzinfo=UTC),
                )
            )

    assert main(["--db", db_url, "alert", "list", "--status", "open"]) == 0
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert len(rows) == 1
    assert rows[0]["status"] == "open"


@pytest.mark.usefixtures("engine")
def test_alert_ack_calls_alert_module_contract(
    capsys: pytest.CaptureFixture[str],
    db_url: str,
    sessions: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    register_node(capsys, db_url)
    install_alerts_stub(monkeypatch)
    alert_id = "e7c3e07a-4cc9-45c4-a13a-000000000001"
    with sessions.begin() as session:
        session.add(
            Alert(
                alert_id=alert_id,
                event_id="7df2d150-b153-49a1-8663-000000000001",
                node_id="node-001",
                circuit_id="lab-load-001",
                kind="active_power_threshold",
                severity="warning",
                status="open",
                opened_at=datetime(2026, 11, 25, tzinfo=UTC),
            )
        )

    assert main(["--db", db_url, "alert", "ack", alert_id, "--by", "operator A"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "acknowledged"
    with sessions() as session:
        assert session.get(Alert, alert_id).status == "acknowledged"  # type: ignore[union-attr]
