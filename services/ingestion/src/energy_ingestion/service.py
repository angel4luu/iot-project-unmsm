"""Ingestion service entry point: `python -m energy_ingestion.service`.

Phase 2 scope: apply migrations, connect to Mosquitto over mutual TLS as
`svc-ingestion`, subscribe to every node's measurements/events/status, validate
each payload against the contracts, and log the result. Storage, ACKs, and
alerts are added by the user-story tasks (US1, US2). A heartbeat file drives the
container healthcheck (`python -m energy_ingestion.health.ready`).
"""

from __future__ import annotations

import os
import signal
import ssl
import sys
import threading
import time
from pathlib import Path
from typing import Any

import paho.mqtt.client as mqtt
from alembic import command
from alembic.config import Config

from energy_ingestion.contracts.topics import TOPIC_PREFIX, check_identity, parse_topic
from energy_ingestion.contracts.validate import ContractError, validate_payload
from energy_ingestion.health.ready import HEARTBEAT_FILE, beat
from energy_ingestion.logging import configure, get_logger, log_event
from energy_ingestion.persistence.db import sqlite_url
from energy_ingestion.persistence.ledger import payload_sha256

LOG = get_logger("ingest")
SERVICE_DIR = Path(__file__).resolve().parents[2]
SCHEMA_FOR_CHANNEL = {
    "measurements": "measurement",
    "events": "node-event",
    "status": "node-status",
}
HEARTBEAT_S = 10


def migrate() -> None:
    cfg = Config(str(SERVICE_DIR / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", sqlite_url())
    command.upgrade(cfg, "head")


def handle(topic: str, raw: bytes, cert_identity: str | None = None) -> str:
    """Validate one inbound message and return the result code (logged)."""
    started = time.perf_counter()
    try:
        node_id, channel = parse_topic(topic)
        if channel not in SCHEMA_FOR_CHANNEL:
            raise ContractError("topic_invalid", "not an inbound channel")
        doc = validate_payload(SCHEMA_FOR_CHANNEL[channel], raw)
        # The broker ACL already binds the certificate to the topic node_id.
        check_identity(cert_identity or node_id, topic, doc)
        result, reason = "valid", None
    except ContractError as exc:
        node_id, result, reason = None, "rejected", exc.reason_code
    log_event(
        LOG,
        "message_validated",
        node_id=node_id,
        topic_channel=topic.rsplit("/", 1)[-1],
        payload_sha256=payload_sha256(raw),
        result=result,
        reason=reason,
        latency_ms=round((time.perf_counter() - started) * 1000, 3),
    )
    return result


def _client() -> mqtt.Client:
    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id="svc-ingestion",
        protocol=mqtt.MQTTv5,
    )
    ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=os.environ["MQTT_CA_FILE"])
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(os.environ["MQTT_CERT_FILE"], os.environ["MQTT_KEY_FILE"])
    client.tls_set_context(ctx)
    return client


def main() -> int:
    configure()
    migrate()
    log_event(LOG, "migrations_applied")
    client = _client()
    connected = threading.Event()
    stop = threading.Event()

    def on_connect(c: mqtt.Client, _u: Any, _f: Any, rc: Any, _p: Any = None) -> None:
        if rc.is_failure:
            log_event(LOG, "broker_connect_failed", result="error", reason=str(rc))
            return
        for channel in SCHEMA_FOR_CHANNEL:
            c.subscribe(f"{TOPIC_PREFIX}/+/{channel}", qos=1)
        connected.set()
        log_event(LOG, "broker_connected", result="ok")

    def on_disconnect(_c: mqtt.Client, _u: Any, _f: Any, rc: Any, _p: Any = None) -> None:
        connected.clear()
        log_event(LOG, "broker_disconnected", reason=str(rc))

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect

    def on_message(_c: mqtt.Client, _u: Any, msg: mqtt.MQTTMessage) -> None:
        handle(msg.topic, bytes(msg.payload))

    client.on_message = on_message
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    client.connect_async(
        os.environ.get("MQTT_HOST", "mosquitto"), int(os.environ.get("MQTT_PORT", "8883"))
    )
    client.loop_start()
    try:
        while not stop.wait(HEARTBEAT_S if connected.is_set() else 1):
            if connected.is_set():
                beat()
    finally:
        HEARTBEAT_FILE.unlink(missing_ok=True)
        client.loop_stop()
        client.disconnect()
    return 0


if __name__ == "__main__":
    sys.exit(main())
