"""T099: `energyctl` node and calibration registration, and the 25 W threshold bound."""

import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError
from sqlalchemy.orm import Session, sessionmaker

from energy_ingestion.cli.energyctl import main
from energy_ingestion.persistence.db import CalibrationArtifact, MonitoringNode
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
