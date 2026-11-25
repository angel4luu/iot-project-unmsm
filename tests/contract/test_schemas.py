"""T010: every normative schema accepts its valid fixture and rejects its invalid one.

The schemas are read from specs/001-energy-monitoring-system/contracts/ (no copies).
"""

import json
from pathlib import Path

import pytest

from energy_ingestion.contracts.validate import (
    MAX_PAYLOAD_BYTES,
    SCHEMA_NAMES,
    ContractError,
    schema_errors,
    validate_payload,
)
from tests.conftest import CONTRACTS_DIR, TELEMETRY_FIXTURES

FIXTURES: dict[str, tuple[Path, Path]] = {
    "measurement": (
        CONTRACTS_DIR / "examples" / "valid-measurement.json",
        CONTRACTS_DIR / "examples" / "invalid-measurement.json",
    ),
    **{
        name: (
            TELEMETRY_FIXTURES / f"valid-{name}.json",
            TELEMETRY_FIXTURES / f"invalid-{name}.json",
        )
        for name in ("node-status", "node-event", "threshold-config", "measurement-ack")
    },
}

# The one defect each invalid fixture carries: (JSON path of the error, validator keyword).
EXPECTED_DEFECTS: dict[str, set[tuple[str, str]]] = {
    "node-status": {("$.state", "enum")},
    "node-event": {("$", "required")},
    "threshold-config": {("$.active_power_limit_W", "exclusiveMinimum")},
    "measurement-ack": {("$", "required")},
}


def _load(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def test_every_schema_has_fixtures() -> None:
    assert set(FIXTURES) == set(SCHEMA_NAMES)
    on_disk = {p.name.removesuffix(".schema.json") for p in CONTRACTS_DIR.glob("*.schema.json")}
    assert on_disk == set(SCHEMA_NAMES)


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_valid_fixture_is_accepted(name: str) -> None:
    valid, _ = FIXTURES[name]
    assert schema_errors(name, _load(valid)) == []
    validate_payload(name, valid.read_bytes())


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_invalid_fixture_is_rejected(name: str) -> None:
    _, invalid = FIXTURES[name]
    assert schema_errors(name, _load(invalid))
    with pytest.raises(ContractError) as exc:
        validate_payload(name, invalid.read_bytes())
    assert exc.value.reason_code == "schema_violation"


@pytest.mark.parametrize("name", sorted(EXPECTED_DEFECTS))
def test_invalid_fixture_fails_for_its_documented_defect(name: str) -> None:
    _, invalid = FIXTURES[name]
    found = {(e.json_path, e.validator) for e in schema_errors(name, _load(invalid))}
    assert found == EXPECTED_DEFECTS[name]


def test_invalid_measurement_fails_for_missing_units_and_unrecognized_field() -> None:
    _, invalid = FIXTURES["measurement"]
    errors = schema_errors("measurement", _load(invalid))
    found = {(e.json_path, e.validator) for e in errors}
    assert ("$.measurements.voltage_rms", "required") in found
    assert any("'unit'" in e.message for e in errors if e.validator == "required")
    assert ("$", "additionalProperties") in found
    assert any("'unexpected'" in e.message for e in errors if e.validator == "additionalProperties")
    assert len(found) == 2


def test_payload_above_16_kib_is_rejected() -> None:
    valid, _ = FIXTURES["node-status"]
    doc = _load(valid)
    assert isinstance(doc, dict)
    raw = json.dumps(doc).encode()
    padded = raw[:-1] + b" " * (MAX_PAYLOAD_BYTES + 1 - len(raw)) + b"}"
    assert len(padded) == MAX_PAYLOAD_BYTES + 1
    with pytest.raises(ContractError) as exc:
        validate_payload("node-status", padded)
    assert exc.value.reason_code == "payload_too_large"


def test_payload_of_exactly_16_kib_is_size_admissible() -> None:
    valid, _ = FIXTURES["node-status"]
    raw = valid.read_bytes().rstrip()
    padded = raw[:-1] + b" " * (MAX_PAYLOAD_BYTES - len(raw)) + b"}"
    assert len(padded) == MAX_PAYLOAD_BYTES
    validate_payload("node-status", padded)


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        (b'{"a": 1, "a": 2}', "invalid_json"),  # duplicate member names
        (b'{"a": NaN}', "invalid_json"),
        (b'{"a": Infinity}', "invalid_json"),
        (b"\xff\xfe", "invalid_json"),  # not UTF-8
        (b"[1, 2", "invalid_json"),
    ],
)
def test_malformed_json_is_rejected(raw: bytes, reason: str) -> None:
    with pytest.raises(ContractError) as exc:
        validate_payload("node-status", raw)
    assert exc.value.reason_code == reason


def test_format_assertions_are_enforced() -> None:
    valid, _ = FIXTURES["node-status"]
    doc = _load(valid)
    assert isinstance(doc, dict)
    assert schema_errors("node-status", {**doc, "observed_at": "yesterday"})
    assert schema_errors("node-status", {**doc, "boot_id": "not-a-uuid"})


def test_unknown_schema_name_is_rejected() -> None:
    with pytest.raises(KeyError):
        schema_errors("no-such-schema", {})
