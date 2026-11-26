"""Ingestion service entry point: `python -m energy_ingestion.service`.

Applies migrations, then runs the MQTT subscriber (persistent session, manual
PUBACK; `mqtt/client.py`) feeding the ingest pipeline (validate, ledger,
InfluxDB, application ACK; `mqtt/pipeline.py`). A once-per-second loop:

- writes the broker heartbeat file read by the container healthcheck;
- every 5 s, re-derives node states (stale/offline timers) and writes the
  `node_status` heartbeat points;
- every 10 s, flushes the `pipeline` counters and latency point;
- bounces the broker connection after a deferred message, for redelivery.

The health API listens on 127.0.0.1:8080 inside the container only.
"""

from __future__ import annotations

import os
import signal
import ssl
import sys
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import paho.mqtt.client as mqtt
from alembic import command
from alembic.config import Config

from energy_ingestion.health import api, ready
from energy_ingestion.health.metrics import FLUSH_S, PipelineMetrics
from energy_ingestion.health.node_status import HEARTBEAT_S, NodeStatusTracker
from energy_ingestion.logging import configure, get_logger, log_event
from energy_ingestion.mqtt.client import CLIENT_ID, IngestClient
from energy_ingestion.mqtt.pipeline import IngestPipeline
from energy_ingestion.notifications.outbox import NotificationWorker, build_sender_from_env
from energy_ingestion.persistence.db import make_engine, make_session_factory, sqlite_url
from energy_ingestion.persistence.influx import OPERATIONS_BUCKET, InfluxWriter, PointWriter

LOG = get_logger("ingest")
SERVICE_DIR = Path(__file__).resolve().parents[2]
BROKER_BEAT_S = 10.0


def migrate() -> None:
    cfg = Config(str(SERVICE_DIR / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", sqlite_url())
    command.upgrade(cfg, "head")


def paho_client() -> mqtt.Client:
    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=CLIENT_ID,
        protocol=mqtt.MQTTv5,
    )
    ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=os.environ["MQTT_CA_FILE"])
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(os.environ["MQTT_CERT_FILE"], os.environ["MQTT_KEY_FILE"])
    client.tls_set_context(ctx)
    client.reconnect_delay_set(min_delay=1, max_delay=30)
    return client


class Housekeeping:
    """The periodic duties of the main loop; pure apart from the writer and clock."""

    def __init__(
        self,
        pipeline: IngestPipeline,
        writer: PointWriter,
        beat: Callable[[], None] = ready.beat,
        notification_worker: NotificationWorker | None = None,
    ) -> None:
        self.pipeline = pipeline
        self.writer = writer
        self.beat = beat
        self.notification_worker = notification_worker
        self._last: dict[str, datetime] = {}

    def _due(self, name: str, every_s: float, now: datetime) -> bool:
        last = self._last.get(name)
        if last is not None and (now - last).total_seconds() < every_s:
            return False
        self._last[name] = now
        return True

    def tick(self, now: datetime, connected: bool) -> None:
        if connected and self._due("beat", BROKER_BEAT_S, now):
            self.beat()
        if self._due("status", HEARTBEAT_S, now):
            for t in self.pipeline.tracker.tick(now):
                log_event(LOG, "node_state_changed", node_id=t.node_id, result=t.new, reason=t.old)
            self._write("node_status", lambda: self.pipeline.write_status(now))
        if self._due("metrics", FLUSH_S, now):
            point = self.pipeline.metrics.flush_point(now)
            self._write("pipeline", lambda: self.writer.write(OPERATIONS_BUCKET, point))
        worker = self.notification_worker
        if worker is not None and self._due("notifications", 2.0, now):

            def run_notifications() -> None:
                worker.run_once()

            self._write("notifications", run_notifications)

    def _write(self, what: str, action: Callable[[], None]) -> None:
        try:
            action()
        except Exception as exc:  # operations data never stops ingestion
            log_event(LOG, "operations_write_failed", reason=f"{what}: {type(exc).__name__}")


def main() -> int:
    configure()
    migrate()
    log_event(LOG, "migrations_applied")
    engine = make_engine()
    writer = InfluxWriter.from_env()
    ingest = IngestClient(paho_client())
    pipeline = IngestPipeline(
        make_session_factory(engine),
        writer,
        ingest.publish,
        PipelineMetrics(),
        NodeStatusTracker(),
    )
    ingest.handler = pipeline.handle
    try:
        notification_sender = build_sender_from_env()
    except ValueError as exc:
        notification_sender = None
        log_event(LOG, "notification_webhook_configuration_invalid", reason=str(exc))
    notification_worker = NotificationWorker(
        make_session_factory(engine), notification_sender, writer
    )
    housekeeping = Housekeeping(pipeline, writer, notification_worker=notification_worker)
    health = api.serve_in_thread(api.create_app(pipeline.metrics, pipeline.tracker, ready.check))

    stop = threading.Event()

    def _stop(*_: Any) -> None:
        stop.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, _stop)
    ingest.connect(
        os.environ.get("MQTT_HOST", "mosquitto"), int(os.environ.get("MQTT_PORT", "8883"))
    )
    ingest.client.loop_start()
    try:
        while not stop.wait(1.0):
            housekeeping.tick(datetime.now(UTC), ingest.connected.is_set())
            ingest.maybe_redeliver()
    finally:
        ready.HEARTBEAT_FILE.unlink(missing_ok=True)
        health.should_exit = True
        ingest.client.loop_stop()
        ingest.client.disconnect()
        writer.close()
        engine.dispose()
        log_event(LOG, "stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
