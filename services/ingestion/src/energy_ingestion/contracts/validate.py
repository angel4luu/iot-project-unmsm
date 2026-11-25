"""Validate MQTT payloads against the normative JSON Schemas (T012).

The schemas are read at runtime from the feature's `contracts/` directory; this
module never keeps its own copy. Set `ENERGY_CONTRACTS_DIR` to point elsewhere
(for example, a read-only mount inside the container).
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from functools import cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError

MAX_PAYLOAD_BYTES = 16 * 1024
SCHEMA_NAMES: tuple[str, ...] = (
    "measurement",
    "node-status",
    "node-event",
    "threshold-config",
    "measurement-ack",
)
_DEFAULT_DIR = (
    Path(__file__).resolve().parents[5] / "specs" / "001-energy-monitoring-system" / "contracts"
)


class ContractError(ValueError):
    """A payload broke the contract; `reason_code` is safe to log and to ACK."""

    def __init__(self, reason_code: str, detail: str = "") -> None:
        super().__init__(f"{reason_code}: {detail}" if detail else reason_code)
        self.reason_code = reason_code
        self.detail = detail


def contracts_dir() -> Path:
    return Path(os.environ.get("ENERGY_CONTRACTS_DIR", _DEFAULT_DIR))


@cache
def _validator(name: str) -> Draft202012Validator:
    if name not in SCHEMA_NAMES:
        raise KeyError(f"unknown schema: {name}")
    schema = json.loads((contracts_dir() / f"{name}.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def schema_errors(name: str, document: object) -> list[ValidationError]:
    """All schema violations of `document`, sorted by location (empty if valid)."""
    return sorted(_validator(name).iter_errors(document), key=lambda e: (e.json_path, e.validator))


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContractError("invalid_json", f"duplicate member name {key!r}")
        result[key] = value
    return result


def _reject_constant(token: str) -> None:
    raise ContractError("invalid_json", f"non-finite number {token}")


def parse_json(raw: bytes) -> object:
    """Parse UTF-8 JSON, refusing oversize input, duplicate names, NaN, and infinities."""
    if len(raw) > MAX_PAYLOAD_BYTES:
        raise ContractError("payload_too_large", f"{len(raw)} bytes")
    try:
        text = raw.decode("utf-8")
        return json.loads(
            text, object_pairs_hook=_reject_duplicates, parse_constant=_reject_constant
        )
    except UnicodeDecodeError as exc:
        raise ContractError("invalid_json", "not UTF-8") from exc
    except json.JSONDecodeError as exc:
        raise ContractError("invalid_json", f"line {exc.lineno} column {exc.colno}") from exc


def validate_payload(name: str, raw: bytes) -> Mapping[str, Any]:
    """Parse and validate one payload; return the document or raise ContractError."""
    document = parse_json(raw)
    errors = schema_errors(name, document)
    if errors:
        first = errors[0]
        raise ContractError("schema_violation", f"{first.json_path}: {first.validator}")
    if not isinstance(document, dict):  # every schema is an object; kept for typing
        raise ContractError("schema_violation", "not an object")
    return document
