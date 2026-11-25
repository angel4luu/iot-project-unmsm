"""T052: persistent session, manual PUBACK after processing, redelivery on failure."""

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import paho.mqtt.client as mqtt
import pytest

from energy_ingestion.mqtt import client as mc

pytestmark = pytest.mark.unit


@dataclass
class FakePaho:
    calls: list[tuple[str, Any]] = field(default_factory=list)
    publish_rc: int = mqtt.MQTT_ERR_SUCCESS
    on_connect: Any = None
    on_disconnect: Any = None
    on_message: Any = None

    def manual_ack_set(self, on: bool) -> None:
        self.calls.append(("manual_ack", on))

    def connect_async(self, host: str, port: int, **kw: Any) -> None:
        self.calls.append(("connect", (host, port, kw)))

    def subscribe(self, subs: Any) -> None:
        self.calls.append(("subscribe", subs))

    def ack(self, mid: int, qos: int) -> None:
        self.calls.append(("ack", mid))

    def publish(self, topic: str, payload: bytes, **kw: Any) -> Any:
        self.calls.append(("publish", (topic, kw)))
        return SimpleNamespace(rc=self.publish_rc)

    def loop_stop(self) -> None:
        self.calls.append(("loop_stop", None))

    def reconnect(self) -> None:
        self.calls.append(("reconnect", None))

    def loop_start(self) -> None:
        self.calls.append(("loop_start", None))

    def names(self) -> list[str]:
        return [name for name, _ in self.calls]


class Clock:
    def __init__(self) -> None:
        self.t = 100.0

    def __call__(self) -> float:
        return self.t


def msg(mid: int = 7) -> Any:
    return SimpleNamespace(
        topic="unmsm/energy/v1/nodes/node-001/measurements", payload=b"{}", mid=mid, qos=1
    )


def make(handler: Any = None) -> tuple[mc.IngestClient, FakePaho, Clock]:
    paho, clock = FakePaho(), Clock()
    return mc.IngestClient(paho, handler, monotonic=clock), paho, clock


def test_manual_ack_and_persistent_session() -> None:
    ic, paho, _ = make()
    assert paho.calls[0] == ("manual_ack", True)
    ic.connect("mosquitto", 8883)
    _, (host, port, kw) = paho.calls[-1]
    assert (host, port, kw["clean_start"]) == ("mosquitto", 8883, False)
    assert kw["properties"].SessionExpiryInterval == 24 * 3600


def test_subscribes_qos1_to_inbound_channels_on_connect() -> None:
    ic, paho, _ = make()
    ic._on_connect(
        paho, None, SimpleNamespace(session_present=True), SimpleNamespace(is_failure=False)
    )
    _, subs = paho.calls[-1]
    assert [t for t, _ in subs] == [
        "unmsm/energy/v1/nodes/+/measurements",
        "unmsm/energy/v1/nodes/+/events",
        "unmsm/energy/v1/nodes/+/status",
    ]
    assert all(o.QoS == 1 for _, o in subs)
    assert ic.connected.is_set()


def test_puback_only_after_the_handler_finishes() -> None:
    seen: list[str] = []
    ic, paho, _ = make(lambda topic, raw: seen.append(topic))
    ic._on_message(paho, None, msg(7))
    assert seen
    assert paho.calls[-1] == ("ack", 7)


def test_failure_withholds_puback_then_bounces_after_backoff() -> None:
    def boom(topic: str, raw: bytes) -> None:
        raise ConnectionError("influx down")

    ic, paho, clock = make(boom)
    ic._on_message(paho, None, msg(9))
    assert "ack" not in paho.names()
    assert ic.redelivery_pending
    assert ic.maybe_redeliver() is False  # backoff not over
    clock.t += mc.REDELIVERY_BACKOFF_S
    assert ic.maybe_redeliver() is True
    assert paho.names()[-3:] == ["loop_stop", "reconnect", "loop_start"]
    assert not ic.redelivery_pending


def test_unwired_client_leaves_messages_in_the_session() -> None:
    ic, paho, _ = make(None)
    ic._on_message(paho, None, msg())
    assert "ack" not in paho.names()


def test_ack_publish_has_expiry_and_raises_when_not_queued() -> None:
    ic, paho, _ = make()
    ic.publish("t", b"x", 1, False)
    _, (_, kw) = paho.calls[-1]
    assert (kw["qos"], kw["retain"]) == (1, False)
    assert kw["properties"].MessageExpiryInterval == 24 * 3600
    paho.publish_rc = mqtt.MQTT_ERR_NO_CONN
    with pytest.raises(ConnectionError):
        ic.publish("t", b"x", 1, False)
