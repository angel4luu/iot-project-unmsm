"""MQTT subscriber with a stable persistent session (T052).

- Fixed client ID `svc-ingestion`, MQTT 5, `clean_start=False`, 24 h session
  expiry: QoS 1 messages that arrive while the service is down wait in the
  broker session.
- Manual PUBACK: a message is acknowledged to the broker only after the
  pipeline has finished with it (stored or terminally rejected). If storage
  fails, the PUBACK is withheld and the connection is bounced after a backoff,
  so the broker redelivers the unacknowledged messages from the session.
- Application ACKs go out QoS 1, not retained, with a 24 h message expiry.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any, Protocol

import paho.mqtt.client as mqtt
from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.properties import Properties
from paho.mqtt.subscribeoptions import SubscribeOptions

from energy_ingestion.contracts.topics import TOPIC_PREFIX
from energy_ingestion.logging import get_logger, log_event

LOG = get_logger("mqtt")
CLIENT_ID = "svc-ingestion"
SESSION_EXPIRY_S = 24 * 3600
ACK_EXPIRY_S = 24 * 3600
KEEPALIVE_S = 30
REDELIVERY_BACKOFF_S = 5.0
INBOUND_CHANNELS = ("measurements", "events", "status")
SUBSCRIPTIONS = tuple(f"{TOPIC_PREFIX}/+/{channel}" for channel in INBOUND_CHANNELS)


class Handler(Protocol):
    def __call__(self, topic: str, raw: bytes) -> object: ...


class IngestClient:
    """Wraps a paho client; `handler` raises only for infrastructure failures."""

    def __init__(
        self,
        client: Any,
        handler: Handler | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.client = client
        self.handler = handler
        self.monotonic = monotonic
        self.connected = threading.Event()
        self._failed_at: float | None = None
        self._lock = threading.Lock()
        client.manual_ack_set(True)
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.on_message = self._on_message

    # ---- connection -------------------------------------------------------------------

    def connect(self, host: str, port: int) -> None:
        props = Properties(PacketTypes.CONNECT)  # type: ignore[no-untyped-call]
        props.SessionExpiryInterval = SESSION_EXPIRY_S
        self.client.connect_async(
            host, port, keepalive=KEEPALIVE_S, clean_start=False, properties=props
        )

    def _on_connect(self, client: Any, _u: Any, flags: Any, rc: Any, _p: Any = None) -> None:
        if rc.is_failure:
            log_event(LOG, "broker_connect_failed", result="error", reason=str(rc))
            return
        options = SubscribeOptions(qos=1)
        client.subscribe([(topic, options) for topic in SUBSCRIPTIONS])
        self.connected.set()
        log_event(
            LOG,
            "broker_connected",
            result="ok",
            session_present=bool(getattr(flags, "session_present", False)),
        )

    def _on_disconnect(self, _c: Any, _u: Any, _f: Any, rc: Any, _p: Any = None) -> None:
        self.connected.clear()
        log_event(LOG, "broker_disconnected", reason=str(rc))

    # ---- messages ---------------------------------------------------------------------

    def _on_message(self, _c: Any, _u: Any, msg: Any) -> None:
        if self.handler is None:  # not wired yet: leave it in the session
            return
        try:
            self.handler(msg.topic, bytes(msg.payload))
        except Exception as exc:  # storage or ACK failure: withhold the PUBACK
            with self._lock:
                if self._failed_at is None:
                    self._failed_at = self.monotonic()
            log_event(LOG, "message_deferred", result="retry", reason=type(exc).__name__)
            return
        self.client.ack(msg.mid, msg.qos)

    def publish(self, topic: str, payload: bytes, qos: int, retain: bool) -> None:
        props = Properties(PacketTypes.PUBLISH)  # type: ignore[no-untyped-call]
        props.MessageExpiryInterval = ACK_EXPIRY_S
        info = self.client.publish(topic, payload, qos=qos, retain=retain, properties=props)
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            raise ConnectionError(f"publish failed: {mqtt.error_string(info.rc)}")

    # ---- redelivery -------------------------------------------------------------------

    @property
    def redelivery_pending(self) -> bool:
        return self._failed_at is not None

    def maybe_redeliver(self) -> bool:
        """After a deferred message and the backoff, reconnect to get redelivery.

        The socket is dropped without DISCONNECT, so the broker keeps the session
        and resends every unacknowledged QoS 1 message on the next connection.
        """
        with self._lock:
            due = (
                self._failed_at is not None
                and self.monotonic() - self._failed_at >= REDELIVERY_BACKOFF_S
            )
            if not due:
                return False
            self._failed_at = None
        log_event(LOG, "redelivery_requested")
        self.client.loop_stop()
        try:
            self.client.reconnect()
        except OSError as exc:  # broker unreachable: the network loop keeps retrying
            log_event(LOG, "reconnect_failed", reason=type(exc).__name__)
        self.client.loop_start()
        return True
