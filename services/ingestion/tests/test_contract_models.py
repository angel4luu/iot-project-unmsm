"""T012: the Pydantic models mirror the normative schemas without divergence."""

import json
from pathlib import Path

import pytest

from energy_ingestion.contracts.models import MODELS, ThresholdConfig, parse
from energy_ingestion.contracts.validate import ContractError, contracts_dir

pytestmark = pytest.mark.unit
REPO = Path(__file__).resolve().parents[3]


def _valid(name: str) -> Path:
    if name == "measurement":
        return contracts_dir() / "examples" / "valid-measurement.json"
    return REPO / "tests" / "fixtures" / "telemetry" / f"valid-{name}.json"


@pytest.mark.parametrize("name", sorted(MODELS))
def test_model_fields_equal_schema_properties(name: str) -> None:
    schema = json.loads((contracts_dir() / f"{name}.schema.json").read_text())
    model = MODELS[name]
    aliases = {f.alias or key for key, f in model.model_fields.items()}
    assert aliases == set(schema["properties"])


@pytest.mark.parametrize("name", sorted(MODELS))
def test_valid_fixture_round_trips(name: str) -> None:
    raw = _valid(name).read_bytes()
    obj = parse(MODELS[name], name, raw)
    dumped = obj.model_dump(mode="json", by_alias=True, exclude_unset=True)
    original = json.loads(raw)
    assert set(dumped) == set(original)


def test_schema_runs_before_model() -> None:
    raw = (REPO / "tests/fixtures/telemetry/invalid-threshold-config.json").read_bytes()
    with pytest.raises(ContractError):
        parse(ThresholdConfig, "threshold-config", raw)


def test_model_must_match_schema_name() -> None:
    with pytest.raises(TypeError):
        parse(ThresholdConfig, "node-status", b"{}")
