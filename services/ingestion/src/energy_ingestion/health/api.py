"""Container-only health and metrics API (T055).

Bound to 127.0.0.1:8080 inside the ingestion container; never published by
Compose (only 8883 and 443 are). Routes:

- `GET /healthz`: the process is alive (always 200 while it serves).
- `GET /readyz`: 200 when connected to the broker and the migrated SQLite opens,
  503 with the problems otherwise.
- `GET /metrics`: pipeline counters and latency, and the derived state of each node.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from energy_ingestion.health.metrics import PipelineMetrics
from energy_ingestion.health.node_status import NodeStatusTracker, derive_state

HOST = "127.0.0.1"
PORT = 8080


def create_app(
    metrics: PipelineMetrics,
    tracker: NodeStatusTracker,
    readiness: Callable[[], list[str]],
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> FastAPI:
    app = FastAPI(title="energy-ingestion health", docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "alive"}

    @app.get("/readyz")
    def readyz() -> JSONResponse:
        problems = readiness()
        body = {"status": "ready" if not problems else "not_ready", "problems": problems}
        return JSONResponse(body, status_code=200 if not problems else 503)

    @app.get("/metrics")
    def metrics_view() -> dict[str, Any]:
        now = clock()
        return {
            "pipeline": metrics.snapshot(),
            "nodes": {
                node_id: derive_state(view, now) for node_id, view in list(tracker.nodes.items())
            },
        }

    return app


def serve_in_thread(app: FastAPI, host: str = HOST, port: int = PORT) -> uvicorn.Server:
    """Run the API on a daemon thread; call `.should_exit = True` to stop it."""
    server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="warning"))
    threading.Thread(target=server.run, name="health-api", daemon=True).start()
    return server
