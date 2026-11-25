"""Service wiring: periodic housekeeping and readiness."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy.orm import Session, sessionmaker

from energy_ingestion.health import ready
from energy_ingestion.mqtt.pipeline import IngestPipeline
from energy_ingestion.service import Housekeeping
from tests.conftest import alembic_config
from tests.fakes import FakeClock, FakePublisher, FakeWriter

pytestmark = pytest.mark.unit
T0 = datetime(2026, 10, 14, 17, 0, 0, tzinfo=UTC)


def housekeeping(sessions: sessionmaker[Session]) -> tuple[Housekeeping, FakeWriter, list[int]]:
    writer, beats = FakeWriter(), []
    pipe = IngestPipeline(sessions, writer, FakePublisher(), clock=FakeClock())
    pipe.tracker.on_measurement("node-001", T0, T0)
    return Housekeeping(pipe, writer, beat=lambda: beats.append(1)), writer, beats


def run(hk: Housekeeping, seconds: int, connected: bool = True) -> None:
    for s in range(seconds):
        hk.tick(T0 + timedelta(seconds=s), connected)


def test_status_every_5_s_metrics_every_10_s_beat_every_10_s(
    sessions: sessionmaker[Session],
) -> None:
    hk, writer, beats = housekeeping(sessions)
    run(hk, 30)
    assert len(writer.lines("operations", "node_status")) == 6
    assert len(writer.lines("operations", "pipeline")) == 3
    assert len(beats) == 3


def test_timers_move_the_node_to_offline(sessions: sessionmaker[Session]) -> None:
    hk, writer, _ = housekeeping(sessions)
    run(hk, 36)
    states = [
        line.split('state="')[1].split('"')[0] for line in writer.lines("operations", "node_status")
    ]
    assert states[0] == "online"
    assert "stale" in states
    assert states[-1] == "offline"


def test_no_beat_while_disconnected(sessions: sessionmaker[Session]) -> None:
    hk, _, beats = housekeeping(sessions)
    run(hk, 20, connected=False)
    assert beats == []


def test_operations_write_failure_does_not_raise(sessions: sessionmaker[Session]) -> None:
    hk, writer, _ = housekeeping(sessions)
    writer.fail = True
    run(hk, 11)  # must not raise


def test_readiness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = tmp_path / "energy.sqlite"
    monkeypatch.setenv("SQLITE_PATH", str(db))
    monkeypatch.setattr(ready, "HEARTBEAT_FILE", tmp_path / "hb")
    assert set(ready.check()) == {"no broker heartbeat", "sqlite: OperationalError"}
    command.upgrade(alembic_config(f"sqlite:///{db}"), "head")
    ready.beat()
    assert ready.check() == []
    assert ready.main() == 0
