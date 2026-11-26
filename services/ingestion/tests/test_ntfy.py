"""T109: ntfy notification format on top of the webhook sender (decision 6)."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from energy_ingestion.notifications.outbox import WebhookSender, ntfy_payload

pytestmark = pytest.mark.unit
ALERT_ID = "9c84e72c-13d3-48f0-bc5e-bfa68aa6a12a"
TOPIC = "test-topic-0123456789abcdef"  # dummy; real topics come only from the secret file
PAYLOAD: dict[str, Any] = {
    "alert_id": ALERT_ID,
    "kind": "active_power_threshold",
    "severity": "warning",
    "status": "open",
    "node_id": "node-001",
    "circuit_id": "lab-load-001",
    "opened_at": "2026-11-30T15:00:11.400Z",
    "observed_value": 18.234,
    "threshold_value": 15.0,
    "unit": "W",
    "quality": "valid",
    "validation": "not_validated",
}


def topic_file(tmp_path: Path, topic: str = TOPIC) -> Path:
    path = tmp_path / "notification-token"
    path.write_text(topic + "\n", encoding="utf-8")
    return path


def test_threshold_alert_message_in_spanish() -> None:
    body = ntfy_payload(PAYLOAD, TOPIC)
    assert body["topic"] == TOPIC
    assert body["title"] == "Alerta: potencia sobre el límite"
    assert body["message"].splitlines() == [
        "Nodo node-001, circuito lab-load-001.",
        "Medido 18,2 W; límite 15,0 W.",
        "Calidad: válida.",
        "Abierta: 2026-11-30 15:00:11.400 UTC.",
        "Valores no validados.",
        f"ID: {ALERT_ID}",
    ]
    assert (body["priority"], body["tags"]) == (4, ["warning", "zap"])


def test_critical_and_non_threshold_alerts() -> None:
    body = ntfy_payload(
        {
            **PAYLOAD,
            "kind": "pipeline_health",
            "severity": "critical",
            "observed_value": None,
            "threshold_value": None,
            "unit": None,
            "quality": None,
            "circuit_id": None,
        },
        TOPIC,
    )
    assert body["title"] == "Alerta crítica: falla en la cadena de monitoreo"
    assert (body["priority"], body["tags"]) == (5, ["rotating_light"])
    assert body["message"].splitlines()[0] == "Nodo node-001, circuito -."
    assert not any(line.startswith(("Medido", "Calidad")) for line in body["message"].splitlines())


def test_degraded_over_range_alert_says_so() -> None:
    body = ntfy_payload({**PAYLOAD, "quality": "degraded", "observed_value": 30.0}, TOPIC)
    assert "Calidad: degradada." in body["message"].splitlines()


def test_sender_posts_ntfy_json_to_the_server_root_without_bearer(tmp_path: Path) -> None:
    received: list[tuple[str, dict[str, str], dict[str, Any]]] = []

    class Receiver(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            body = self.rfile.read(int(self.headers["Content-Length"]))
            received.append((self.path, dict(self.headers.items()), json.loads(body)))
            self.send_response(200)
            self.end_headers()

        def log_message(self, _format: str, *_args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Receiver)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        env = {
            "NOTIFICATION_WEBHOOK_URL": f"http://127.0.0.1:{server.server_port}",
            "NOTIFICATION_TOKEN_FILE": str(topic_file(tmp_path)),
            "NOTIFICATION_FORMAT": "ntfy",
        }
        sender = WebhookSender.from_env(env)
        assert sender is not None
        sender(PAYLOAD, ALERT_ID)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    ((path, headers, body),) = received
    lowered = {k.lower(): v for k, v in headers.items()}
    assert path == "/"  # the topic travels in the body, never in the URL
    assert "authorization" not in lowered
    assert lowered["idempotency-key"] == ALERT_ID
    assert body == ntfy_payload(PAYLOAD, TOPIC)


def test_default_format_is_generic(tmp_path: Path) -> None:
    env = {
        "NOTIFICATION_WEBHOOK_URL": "https://hooks.example.invalid/alerts",
        "NOTIFICATION_TOKEN_FILE": str(topic_file(tmp_path)),
    }
    sender = WebhookSender.from_env(env)
    assert sender is not None
    assert sender._fmt == "generic"


@pytest.mark.parametrize("topic", ["alerts", "unmsm_grupo-5", "x" * 64])
def test_short_topics_chosen_by_the_team_are_accepted(tmp_path: Path, topic: str) -> None:
    WebhookSender("https://ntfy.sh", topic_file(tmp_path, topic), fmt="ntfy")


@pytest.mark.parametrize("topic", ["has space", "alertas-energía", "a/b", "x" * 65])
def test_malformed_topics_are_refused_without_echo(tmp_path: Path, topic: str) -> None:
    with pytest.raises(ValueError, match="ntfy topic") as exc:
        WebhookSender("https://ntfy.sh", topic_file(tmp_path, topic), fmt="ntfy")
    assert topic not in str(exc.value)


@pytest.mark.parametrize("url", ["https://ntfy.sh/some-topic", "https://ntfy.sh/?t=1"])
def test_ntfy_url_must_be_the_server_root(tmp_path: Path, url: str) -> None:
    with pytest.raises(ValueError, match="server root"):
        WebhookSender(url, topic_file(tmp_path), fmt="ntfy")


def test_unknown_format_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="format"):
        WebhookSender("https://ntfy.sh", topic_file(tmp_path), fmt="telegram")
