"""T023: one JSON object per line, UTC, standard fields, secrets redacted."""

import io
import json
import logging

import pytest

from energy_ingestion.logging import REDACTED, configure, get_logger, log_event

pytestmark = pytest.mark.unit


def _capture(**fields: object) -> dict[str, object]:
    buf = io.StringIO()
    configure(stream=buf)
    log_event(get_logger("ingest"), "measurement_stored", **fields)
    line = buf.getvalue().strip()
    assert "\n" not in line
    doc = json.loads(line)
    assert isinstance(doc, dict)
    return doc


def test_standard_fields_and_utc() -> None:
    doc = _capture(
        node_id="node-001",
        message_id="123e4567-e89b-42d3-a456-426614174000",
        result="accepted",
        latency_ms=12.5,
    )
    assert doc["component"] == "ingest"
    assert doc["event"] == "measurement_stored"
    assert doc["level"] == "info"
    assert isinstance(doc["ts"], str)
    assert doc["ts"].endswith("Z")
    assert doc["node_id"] == "node-001"
    assert doc["latency_ms"] == 12.5


@pytest.mark.parametrize("key", ["token", "influx_token", "password", "api_key", "payload"])
def test_secret_bearing_fields_are_redacted(key: str) -> None:
    doc = _capture(**{key: "s3cr3t-value"})
    assert doc[key] == REDACTED
    assert "s3cr3t-value" not in json.dumps(doc)


def test_payload_hash_is_kept() -> None:
    assert _capture(payload_sha256="ab" * 32)["payload_sha256"] == "ab" * 32


def test_level_is_respected() -> None:
    buf = io.StringIO()
    configure(level=logging.WARNING, stream=buf)
    log_event(get_logger("x"), "quiet")
    assert buf.getvalue() == ""
