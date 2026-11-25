"""T021: migration 0001 creates the data-model schema, in WAL mode, with triggers."""

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Engine, inspect, text

from energy_ingestion.persistence.db import Base, make_engine
from tests.conftest import alembic_config

pytestmark = pytest.mark.unit

TABLES = {
    "monitoring_node",
    "circuit",
    "calibration_artifact",
    "threshold_configuration",
    "ingestion_ledger",
    "alert",
    "alert_transition",
    "notification_outbox",
}


def test_upgrade_creates_every_table(engine: Engine) -> None:
    assert set(inspect(engine).get_table_names()) >= TABLES


def test_models_match_migration(engine: Engine) -> None:
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []


def test_wal_mode_and_foreign_keys(engine: Engine) -> None:
    with engine.connect() as conn:
        assert conn.execute(text("PRAGMA journal_mode")).scalar() == "wal"
        assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 1


def test_downgrade_then_upgrade(db_url: str) -> None:
    cfg = alembic_config(db_url)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    eng = make_engine(db_url)
    assert not TABLES & set(inspect(eng).get_table_names())
    eng.dispose()
    command.upgrade(cfg, "head")
