"""T099: container-only health API (/healthz, /readyz, /metrics)."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from energy_ingestion.health import api
from energy_ingestion.health.metrics import PipelineMetrics
from energy_ingestion.health.node_status import NodeStatusTracker

pytestmark = pytest.mark.unit
T0 = datetime(2026, 10, 14, 17, 0, 0, tzinfo=UTC)


def client(problems: list[str], now: datetime = T0) -> tuple[TestClient, PipelineMetrics]:
    metrics, tracker = PipelineMetrics(), NodeStatusTracker()
    tracker.on_measurement("node-001", T0, T0)
    app = api.create_app(metrics, tracker, lambda: problems, clock=lambda: now)
    return TestClient(app), metrics


def test_healthz_is_always_alive() -> None:
    c, _ = client(["no broker heartbeat"])
    assert c.get("/healthz").json() == {"status": "alive"}


def test_readyz_200_when_ready() -> None:
    c, _ = client([])
    r = c.get("/readyz")
    assert (r.status_code, r.json()["status"]) == (200, "ready")


def test_readyz_503_lists_problems() -> None:
    c, _ = client(["no broker heartbeat", "sqlite: OperationalError"])
    r = c.get("/readyz")
    assert r.status_code == 503
    assert r.json()["problems"] == ["no broker heartbeat", "sqlite: OperationalError"]


def test_metrics_show_counters_latency_and_node_states() -> None:
    c, metrics = client([], now=T0 + timedelta(seconds=20))
    metrics.count("received")
    metrics.count("accepted")
    metrics.latency(12.5)
    body = c.get("/metrics").json()
    assert body["pipeline"]["received_total"] == 1
    assert body["pipeline"]["accepted_total"] == 1
    assert body["pipeline"]["ingest_latency_ms_p50"] == 12.5
    assert body["nodes"] == {"node-001": "stale"}


def test_no_api_docs_are_exposed() -> None:
    c, _ = client([])
    assert c.get("/docs").status_code == 404
    assert c.get("/openapi.json").status_code == 404


def test_binds_to_loopback_only() -> None:
    assert api.HOST == "127.0.0.1"
