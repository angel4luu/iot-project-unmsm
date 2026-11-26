"""T079: notification retries use the migrated SQLite schema in-process."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select

from energy_ingestion.notifications.outbox import DeliveryError, NotificationWorker
from energy_ingestion.persistence.db import (
    Alert,
    NotificationOutbox,
    make_engine,
    make_session_factory,
)

pytestmark = pytest.mark.integration
NOW = datetime(2026, 11, 25, 12, 0, tzinfo=UTC)
ALERT_ID = "9c84e72c-13d3-48f0-bc5e-bfa68aa6a12a"
SERVICE_DIR = Path(__file__).resolve().parents[2] / "services" / "ingestion"


class MutableClock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


class FixedRng:
    def uniform(self, low: float, high: float) -> float:
        return 1.0


class RecoveringReceiver:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, payload: dict[str, Any], alert_id: str) -> None:
        self.calls.append((alert_id, payload))
        if len(self.calls) == 1:
            raise DeliveryError("http_503", retryable=True)


class NoopWriter:
    def write(self, _bucket: str, _point: Any) -> None:
        return


def test_outbox_retries_against_real_migrated_schema(tmp_path: Path) -> None:
    db_path = tmp_path / "notifications.sqlite"
    db_url = f"sqlite:///{db_path}"
    config = Config(str(SERVICE_DIR / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", db_url)
    command.upgrade(config, "head")
    engine = make_engine(db_url)
    sessions = make_session_factory(engine)
    try:
        with sessions.begin() as session:
            session.add(
                Alert(
                    alert_id=ALERT_ID,
                    event_id="124b6e12-5126-49f4-a8ac-d78f9b40b1db",
                    node_id="node-001",
                    circuit_id="lab-load-001",
                    kind="active_power_threshold",
                    severity="warning",
                    status="open",
                    opened_at=NOW,
                    observed_value=17.25,
                    threshold_value=15.0,
                    unit="W",
                    quality="valid",
                )
            )
            session.add(
                NotificationOutbox(
                    delivery_id="dbcc6795-8e89-4486-b90b-5c0068c875ea",
                    alert_id=ALERT_ID,
                    destination_type="webhook",
                    state="pending",
                    attempt_count=0,
                    next_attempt_at=NOW,
                )
            )

        clock = MutableClock(NOW)
        receiver = RecoveringReceiver()
        worker = NotificationWorker(
            sessions,
            receiver,
            NoopWriter(),
            clock=clock,
            rng=FixedRng(),
        )
        assert worker.run_once() == 1
        with sessions() as session:
            row = session.scalar(select(NotificationOutbox))
            assert row is not None
            assert (row.state, row.attempt_count, row.last_error_code) == (
                "pending",
                1,
                "http_503",
            )
            assert row.next_attempt_at == NOW + timedelta(seconds=2)

        clock.now += timedelta(seconds=2)
        assert worker.run_once() == 1
        with sessions() as session:
            rows = list(session.scalars(select(NotificationOutbox)))
            assert len(rows) == 1
            assert (rows[0].state, rows[0].attempt_count, rows[0].delivered_at) == (
                "delivered",
                1,
                clock.now,
            )
        assert [item[0] for item in receiver.calls] == [ALERT_ID, ALERT_ID]
        assert all(item[1]["validation"] == "not_validated" for item in receiver.calls)
    finally:
        engine.dispose()
