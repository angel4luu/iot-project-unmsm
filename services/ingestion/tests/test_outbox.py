"""T079: notification outbox retries, idempotency, and webhook safety."""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from energy_ingestion.notifications.outbox import (
    MAX_ATTEMPTS,
    DeliveryError,
    NotificationWorker,
    WebhookSender,
)
from energy_ingestion.persistence.db import Alert, AlertTransition, NotificationOutbox
from energy_ingestion.persistence.influx import OPERATIONS_BUCKET
from tests.fakes import FakeClock, FakeWriter

NOW = datetime(2026, 11, 25, 12, 0, tzinfo=UTC)
ALERT_ID = "9c84e72c-13d3-48f0-bc5e-bfa68aa6a12a"


def insert_alert(sessions: sessionmaker[Session], *, state: str = "pending") -> None:
    with sessions.begin() as session:
        session.add(
            Alert(
                alert_id=ALERT_ID,
                event_id="124b6e12-5126-49f4-a8ac-d78f9b40b1db",
                node_id="node-001",
                circuit_id="lab-load-001",
                kind="active_power_threshold",
                severity="warning",
                status="open",
                opened_at=NOW - timedelta(seconds=5),
                observed_value=17.25,
                threshold_value=15.0,
                unit="W",
                quality="valid",
            )
        )
        session.add(
            AlertTransition(
                alert_id=ALERT_ID,
                from_status=None,
                to_status="open",
                actor="system",
                reason="confirmed threshold",
                at=NOW - timedelta(seconds=5),
            )
        )
        session.add(
            NotificationOutbox(
                delivery_id="dbcc6795-8e89-4486-b90b-5c0068c875ea",
                alert_id=ALERT_ID,
                destination_type="webhook",
                state=state,
                attempt_count=0,
                next_attempt_at=NOW if state == "pending" else NOW - timedelta(seconds=1),
            )
        )


class FixedRng:
    def __init__(self, value: float = 1.0) -> None:
        self.value = value

    def uniform(self, low: float, high: float) -> float:
        assert low <= self.value <= high
        return self.value


class FakeSender:
    def __init__(self, outcomes: list[Exception | None] | None = None) -> None:
        self.outcomes = list(outcomes or [])
        self.calls: list[tuple[dict[str, Any], str]] = []

    def __call__(self, payload: dict[str, Any], alert_id: str) -> None:
        self.calls.append((payload, alert_id))
        outcome = self.outcomes.pop(0) if self.outcomes else None
        if outcome is not None:
            raise outcome


def get_outbox(sessions: sessionmaker[Session]) -> NotificationOutbox:
    with sessions() as session:
        return session.scalar(select(NotificationOutbox))  # type: ignore[return-value]


def make_worker(
    sessions: sessionmaker[Session],
    sender: FakeSender | None,
    writer: FakeWriter | None = None,
    *,
    rng: FixedRng | None = None,
    max_attempts: int = MAX_ATTEMPTS,
) -> tuple[NotificationWorker, FakeWriter]:
    point_writer = writer or FakeWriter()
    return (
        NotificationWorker(
            sessions,
            sender,
            point_writer,
            clock=FakeClock(NOW),
            rng=rng or FixedRng(),
            max_attempts=max_attempts,
        ),
        point_writer,
    )


def test_pending_sending_delivered_and_operations_points(
    sessions: sessionmaker[Session],
) -> None:
    insert_alert(sessions)
    sender = FakeSender()
    worker, writer = make_worker(sessions, sender)

    assert worker.run_once() == 1

    row = get_outbox(sessions)
    assert (row.state, row.delivered_at, row.last_error_code) == ("delivered", NOW, None)
    assert row.next_attempt_at is None
    assert len(sender.calls) == 1
    payload, alert_id = sender.calls[0]
    assert alert_id == ALERT_ID
    assert payload == {
        "alert_id": ALERT_ID,
        "kind": "active_power_threshold",
        "severity": "warning",
        "status": "open",
        "node_id": "node-001",
        "circuit_id": "lab-load-001",
        "opened_at": "2026-11-25T11:59:55.000Z",
        "observed_value": 17.25,
        "threshold_value": 15.0,
        "unit": "W",
        "quality": "valid",
        "validation": "not_validated",
    }
    points = [line for line in writer.lines(OPERATIONS_BUCKET, "alert_notification")]
    assert len(points) == 2
    assert ",state=sending " in points[0]
    assert ",state=delivered " in points[1]


def test_retry_uses_exponential_backoff_with_bounded_jitter(
    sessions: sessionmaker[Session],
) -> None:
    insert_alert(sessions)
    sender = FakeSender([DeliveryError("http_503", retryable=True)])
    worker, _ = make_worker(sessions, sender, rng=FixedRng(1.25))

    assert worker.run_once() == 1

    row = get_outbox(sessions)
    assert row.state == "pending"
    assert row.attempt_count == 1
    assert row.last_error_code == "http_503"
    assert row.next_attempt_at == NOW + timedelta(seconds=2.5)


def test_retry_backoff_caps_at_policy_limit(sessions: sessionmaker[Session]) -> None:
    insert_alert(sessions)
    with sessions.begin() as session:
        row = session.scalar(select(NotificationOutbox))
        assert row is not None
        row.attempt_count = 8
    sender = FakeSender([DeliveryError("timeout", retryable=True)])
    worker, _ = make_worker(sessions, sender, rng=FixedRng(1.5), max_attempts=20)

    assert worker.run_once() == 1

    row = get_outbox(sessions)
    assert row.next_attempt_at == NOW + timedelta(seconds=MAX_BACKOFF_S)


MAX_BACKOFF_S = 300


def test_non_retryable_http_error_is_terminal(sessions: sessionmaker[Session]) -> None:
    insert_alert(sessions)
    sender = FakeSender([DeliveryError("http_400", retryable=False)])
    worker, _ = make_worker(sessions, sender)

    worker.run_once()

    row = get_outbox(sessions)
    assert row.state == "failed_terminal"
    assert row.attempt_count == 1
    assert row.next_attempt_at is None
    assert row.last_error_code == "http_400"


def test_maximum_attempt_count_is_terminal(sessions: sessionmaker[Session]) -> None:
    insert_alert(sessions)
    sender = FakeSender([DeliveryError("timeout", retryable=True)])
    worker, _ = make_worker(sessions, sender, max_attempts=1)

    worker.run_once()

    row = get_outbox(sessions)
    assert row.state == "failed_terminal"
    assert row.attempt_count == 1


def test_expired_sending_lease_is_recovered(sessions: sessionmaker[Session]) -> None:
    insert_alert(sessions, state="sending")
    sender = FakeSender()
    worker, _ = make_worker(sessions, sender)

    assert worker.run_once() == 1
    assert get_outbox(sessions).state == "delivered"
    assert len(sender.calls) == 1


def test_delivery_is_idempotent_and_never_creates_rows(sessions: sessionmaker[Session]) -> None:
    insert_alert(sessions)
    sender = FakeSender()
    worker, _ = make_worker(sessions, sender)
    worker.run_once()
    worker.run_once()

    with sessions() as session:
        rows = list(session.scalars(select(NotificationOutbox)))
    assert len(rows) == 1
    assert len(sender.calls) == 1


def test_unconfigured_worker_keeps_rows_pending_and_warns_once(
    sessions: sessionmaker[Session], caplog: pytest.LogCaptureFixture
) -> None:
    insert_alert(sessions)
    worker, _ = make_worker(sessions, None)

    assert worker.run_once() == 0
    assert worker.run_once() == 0

    assert get_outbox(sessions).state == "pending"
    assert sum("notification_webhook_disabled" in r.message for r in caplog.records) == 1


def test_unexpected_sender_error_is_redacted(sessions: sessionmaker[Session]) -> None:
    insert_alert(sessions)
    sender = FakeSender([RuntimeError("https://private.invalid?token=supersecret body=secret")])
    worker, _ = make_worker(sessions, sender)

    worker.run_once()

    row = get_outbox(sessions)
    assert row.state == "pending"
    assert row.last_error_code == "delivery_error"
    assert "secret" not in row.last_error_code


def test_operations_write_failure_does_not_raise(sessions: sessionmaker[Session]) -> None:
    insert_alert(sessions)
    writer = FakeWriter(fail=True)
    worker, _ = make_worker(sessions, FakeSender(), writer)

    assert worker.run_once() == 1
    assert get_outbox(sessions).state == "delivered"


def test_webhook_sends_contract_body_and_idempotency_header(tmp_path: Path) -> None:
    received: list[tuple[dict[str, str], dict[str, Any]]] = []

    class Receiver(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            body = self.rfile.read(int(self.headers["Content-Length"]))
            received.append((dict(self.headers.items()), json.loads(body)))
            self.send_response(204)
            self.end_headers()

        def log_message(self, _format: str, *_args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Receiver)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    token_file = tmp_path / "notification-token"
    token_file.write_text("runtime-only-token", encoding="utf-8")
    try:
        sender = WebhookSender(
            f"http://127.0.0.1:{server.server_port}/alerts",
            token_file,
            timeout_s=2,
        )
        sender(
            {"alert_id": ALERT_ID, "validation": "not_validated"},
            ALERT_ID,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    headers = {key.lower(): value for key, value in received[0][0].items()}
    assert headers["idempotency-key"] == ALERT_ID
    assert headers["authorization"] == "Bearer runtime-only-token"
    assert received[0][1] == {"alert_id": ALERT_ID, "validation": "not_validated"}


@pytest.mark.parametrize("url", ["http://example.invalid/alerts", "file:///tmp/alerts"])
def test_non_local_plain_http_and_non_http_schemes_are_refused(url: str, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        WebhookSender(url, tmp_path / "token")
