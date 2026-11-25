"""Shared paths for repository-level tests."""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRACTS_DIR = REPO_ROOT / "specs" / "001-energy-monitoring-system" / "contracts"
TELEMETRY_FIXTURES = REPO_ROOT / "tests" / "fixtures" / "telemetry"


@pytest.fixture(scope="session")
def contracts_dir() -> Path:
    return CONTRACTS_DIR
