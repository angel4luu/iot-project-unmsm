"""Fixtures for ingestion unit tests: a migrated, throwaway SQLite database."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from energy_ingestion.persistence.db import make_engine, make_session_factory

SERVICE_DIR = Path(__file__).resolve().parents[1]
REPO = SERVICE_DIR.parents[1]


def alembic_config(url: str) -> Config:
    cfg = Config(str(SERVICE_DIR / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


@pytest.fixture
def db_url(tmp_path: Path) -> str:
    return f"sqlite:///{tmp_path / 'energy.sqlite'}"


@pytest.fixture
def engine(db_url: str) -> Iterator[Engine]:
    command.upgrade(alembic_config(db_url), "head")
    eng = make_engine(db_url)
    yield eng
    eng.dispose()


@pytest.fixture
def sessions(engine: Engine) -> sessionmaker[Session]:
    return make_session_factory(engine)
