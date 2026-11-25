"""Phase 2 service skeleton: inbound validation result codes and readiness."""

from pathlib import Path

import pytest
from alembic import command

from energy_ingestion.contracts.validate import contracts_dir
from energy_ingestion.health import ready
from energy_ingestion.service import handle
from tests.conftest import alembic_config

pytestmark = pytest.mark.unit
TOPIC = "unmsm/energy/v1/nodes/node-001/measurements"


def test_valid_measurement_is_valid() -> None:
    raw = (contracts_dir() / "examples" / "valid-measurement.json").read_bytes()
    assert handle(TOPIC, raw) == "valid"


@pytest.mark.parametrize(
    ("topic", "raw"),
    [
        (TOPIC, b"{}"),
        (TOPIC.replace("node-001", "node-002"), None),  # identity mismatch
        ("unmsm/energy/v1/nodes/node-001/config", None),  # not inbound
        ("other/topic", b"{}"),
    ],
)
def test_bad_messages_are_rejected(topic: str, raw: bytes | None) -> None:
    raw = raw or (contracts_dir() / "examples" / "valid-measurement.json").read_bytes()
    assert handle(topic, raw) == "rejected"


def test_readiness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = tmp_path / "energy.sqlite"
    monkeypatch.setenv("SQLITE_PATH", str(db))
    monkeypatch.setattr(ready, "HEARTBEAT_FILE", tmp_path / "hb")
    assert set(ready.check()) == {"no broker heartbeat", "sqlite: OperationalError"}
    command.upgrade(alembic_config(f"sqlite:///{db}"), "head")
    ready.beat()
    assert ready.check() == []
    assert ready.main() == 0
