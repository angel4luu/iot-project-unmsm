"""T097: payloads written by the firmware serializer validate against the contracts.

`firmware/test/host/test_serialize.c` (run by `make firmware-test`) writes
`tests/fixtures/telemetry/firmware-*.json` with the same serialize.c the ESP32
runs. This test validates each one against the normative schema and checks the
measurement integrity rules that a schema alone cannot express.
"""

import json
from pathlib import Path

import pytest

from energy_ingestion.contracts.validate import validate_payload
from tests.conftest import TELEMETRY_FIXTURES

pytestmark = pytest.mark.unit
SCHEMA_FOR_PREFIX = {
    "firmware-measurement": "measurement",
    "firmware-status": "node-status",
    "firmware-event": "node-event",
}
EXPECTED = {
    "firmware-measurement-valid",
    "firmware-measurement-invalid",
    "firmware-measurement-holdover",
    "firmware-measurement-unsynchronized",
    "firmware-measurement-out-of-bounds",
    "firmware-status-online",
    "firmware-status-last-will",
    "firmware-event-quality",
}


def payloads() -> list[Path]:
    return sorted(TELEMETRY_FIXTURES.glob("firmware-*.json"))


def schema_for(path: Path) -> str:
    return next(s for prefix, s in SCHEMA_FOR_PREFIX.items() if path.stem.startswith(prefix))


def test_every_expected_payload_was_written() -> None:
    assert {p.stem for p in payloads()} == EXPECTED, "run `make firmware-test` first"


@pytest.mark.parametrize("path", payloads(), ids=lambda p: p.stem)
def test_firmware_payload_matches_contract(path: Path) -> None:
    validate_payload(schema_for(path), path.read_bytes().strip())


def test_invalid_window_carries_no_values() -> None:
    doc = json.loads((TELEMETRY_FIXTURES / "firmware-measurement-invalid.json").read_text())
    assert doc["quality"]["state"] == "invalid"
    assert all(q["value"] is None for q in doc["measurements"].values())


def test_unsynchronized_window_is_not_valid_evidence() -> None:
    doc = json.loads((TELEMETRY_FIXTURES / "firmware-measurement-unsynchronized.json").read_text())
    assert doc["clock"] == {"source": "unsynchronized", "last_sync_age_s": None}
    assert doc["quality"]["state"] != "valid"
    assert "clock_unsynchronized" in doc["quality"]["flags"]
