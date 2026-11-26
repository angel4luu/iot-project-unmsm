"""Transactional notification delivery and the generic webhook adapter (T079/T085).

The alert transaction owns outbox-row creation. This worker only claims existing
rows and delivers them; it never creates a second delivery for an alert.
"""

from __future__ import annotations

import json
import logging
import os
import random
import re
import ssl
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit

from influxdb_client import Point, WritePrecision
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session, sessionmaker

from energy_ingestion.logging import get_logger, log_event
from energy_ingestion.persistence.db import Alert, NotificationOutbox
from energy_ingestion.persistence.influx import OPERATIONS_BUCKET, PointWriter

LOG = get_logger("notifications")
INITIAL_BACKOFF_S = 2.0
MAX_BACKOFF_S = 300.0
MAX_ATTEMPTS = 8  # One initial delivery plus at most seven retries.
LEASE_TIMEOUT_S = 60.0
MAX_BATCH = 100
_SAFE_ERROR = re.compile(r"^(?:timeout|tls_error|network_error|delivery_error|http_[0-9]{3})$")


class DeliveryError(Exception):
    """A redacted webhook failure and its retry classification."""

    def __init__(self, error_code: str, *, retryable: bool) -> None:
        self.error_code = error_code if _SAFE_ERROR.fullmatch(error_code) else "delivery_error"
        self.retryable = retryable
        super().__init__(self.error_code)


class Sender(Protocol):
    def __call__(self, payload: dict[str, Any], alert_id: str) -> None: ...


def _utc_iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def alert_payload(alert: Alert) -> dict[str, Any]:
    """Build the stable, measurement-integrity-aware provider payload."""
    return {
        "alert_id": alert.alert_id,
        "kind": alert.kind,
        "severity": alert.severity,
        "status": alert.status,
        "node_id": alert.node_id,
        "circuit_id": alert.circuit_id,
        "opened_at": _utc_iso(alert.opened_at),
        "observed_value": alert.observed_value,
        "threshold_value": alert.threshold_value,
        "unit": alert.unit,
        "quality": alert.quality,
        "validation": "not_validated",
    }


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Do not forward the runtime bearer token to a redirect target."""

    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> Any:
        return None


class WebhookSender:
    """POST alert JSON with a runtime bearer token and alert-level idempotency."""

    def __init__(
        self,
        url: str,
        token_file: Path,
        *,
        timeout_s: float = 5.0,
        opener: Any | None = None,
    ) -> None:
        parsed = urlsplit(url)
        if parsed.scheme != "https" and not (
            parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}
        ):
            raise ValueError(
                "notification webhook URL must use HTTPS (HTTP is allowed for localhost tests)"
            )
        if not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
            raise ValueError("notification webhook URL is malformed")
        try:
            token = token_file.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise ValueError("notification token file is unavailable") from exc
        if not token:
            raise ValueError("notification token file is empty")
        self._url = url
        self._token = token
        self._timeout_s = timeout_s
        self._opener = opener or urllib.request.build_opener(_NoRedirect())

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> WebhookSender | None:
        env = os.environ if environ is None else environ
        url = env.get("NOTIFICATION_WEBHOOK_URL", "").strip()
        if not url:
            return None
        token_file = env.get("NOTIFICATION_TOKEN_FILE", "").strip()
        if not token_file:
            raise ValueError("NOTIFICATION_TOKEN_FILE is required when the webhook URL is set")
        return cls(url, Path(token_file))

    def __call__(self, payload: dict[str, Any], alert_id: str) -> None:
        request = urllib.request.Request(  # noqa: S310 - schemes and host validated above
            self._url,
            data=json.dumps(payload, separators=(",", ":"), allow_nan=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
                "Idempotency-Key": alert_id,
            },
            method="POST",
        )
        try:
            with self._opener.open(request, timeout=self._timeout_s) as response:
                status = int(response.status)
        except urllib.error.HTTPError as exc:
            code = f"http_{exc.code}"
            retryable = exc.code >= 500 or exc.code in (408, 429)
            raise DeliveryError(code, retryable=retryable) from None
        except TimeoutError:
            raise DeliveryError("timeout", retryable=True) from None
        except ssl.SSLError:
            raise DeliveryError("tls_error", retryable=True) from None
        except urllib.error.URLError as exc:
            reason = exc.reason
            if isinstance(reason, ssl.SSLError):
                code = "tls_error"
            elif isinstance(reason, TimeoutError):
                code = "timeout"
            else:
                code = "network_error"
            raise DeliveryError(code, retryable=True) from None
        except OSError:
            raise DeliveryError("network_error", retryable=True) from None
        if not 200 <= status < 300:
            raise DeliveryError(f"http_{status}", retryable=status >= 500 or status in (408, 429))


class NotificationWorker:
    """Claim due outbox rows, send them, and persist state independently of ingestion."""

    def __init__(
        self,
        sessions: sessionmaker[Session],
        sender: Sender | None,
        writer: PointWriter | None,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        rng: Any = random,
        max_attempts: int = MAX_ATTEMPTS,
        lease_timeout_s: float = LEASE_TIMEOUT_S,
        batch_size: int = MAX_BATCH,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        self.sessions = sessions
        self.sender = sender
        self.writer = writer
        self.clock = clock
        self.rng = rng
        self.max_attempts = max_attempts
        self.lease_timeout_s = lease_timeout_s
        self.batch_size = batch_size
        self._disabled_logged = False

    def run_once(self) -> int:
        """Deliver one bounded batch. All provider and operations failures are contained."""
        if self.sender is None:
            if not self._disabled_logged:
                log_event(LOG, "notification_webhook_disabled", level=logging.WARNING)
                self._disabled_logged = True
            return 0
        try:
            delivery_ids = self._claim_due()
        except Exception as exc:
            log_event(LOG, "notification_claim_failed", result="error", reason=type(exc).__name__)
            return 0
        processed = 0
        for delivery_id in delivery_ids:
            try:
                self._deliver(delivery_id)
                processed += 1
            except Exception as exc:
                # The housekeeping loop continues even after a DB/provider bug.
                log_event(
                    LOG,
                    "notification_worker_error",
                    result="error",
                    reason=type(exc).__name__,
                )
        return processed

    def _claim_due(self) -> list[str]:
        now = self.clock()
        due = or_(
            and_(
                NotificationOutbox.state == "pending",
                NotificationOutbox.next_attempt_at <= now,
            ),
            and_(
                NotificationOutbox.state == "sending",
                NotificationOutbox.next_attempt_at <= now,
            ),
        )
        claimed: list[tuple[str, str, str, int]] = []
        transitions: list[tuple[str, str, str, int, str | None]] = []
        with self.sessions.begin() as session:
            rows = list(
                session.scalars(
                    select(NotificationOutbox)
                    .where(due)
                    .order_by(NotificationOutbox.next_attempt_at, NotificationOutbox.delivery_id)
                    .limit(self.batch_size)
                )
            )
            lease_until = now + timedelta(seconds=self.lease_timeout_s)
            for row in rows:
                recovered_lease = row.state == "sending"
                if recovered_lease:
                    row.attempt_count += 1
                    row.last_error_code = "timeout"
                row.state = "sending"
                row.next_attempt_at = lease_until
                alert = session.get(Alert, row.alert_id)
                if alert is None:
                    continue
                if recovered_lease and row.attempt_count >= self.max_attempts:
                    row.state = "failed_terminal"
                    row.next_attempt_at = None
                    transitions.append(
                        (
                            row.delivery_id,
                            row.alert_id,
                            alert.node_id,
                            row.attempt_count,
                            "timeout",
                        )
                    )
                    continue
                claimed.append((row.delivery_id, row.alert_id, alert.node_id, row.attempt_count))
                if not recovered_lease:
                    transitions.append(
                        (
                            row.delivery_id,
                            row.alert_id,
                            alert.node_id,
                            row.attempt_count,
                            None,
                        )
                    )
        for _delivery_id, alert_id, node_id, attempt_count, error_code in transitions:
            state = "failed_terminal" if error_code else "sending"
            self._write_state(node_id, state, alert_id, attempt_count, error_code, now)
        return [delivery_id for delivery_id, _, _, _ in claimed]

    def _deliver(self, delivery_id: str) -> None:
        with self.sessions() as session:
            row = session.get(NotificationOutbox, delivery_id)
            if row is None or row.state != "sending":
                return
            alert = session.get(Alert, row.alert_id)
            if alert is None:
                self._finish_failure(delivery_id, "delivery_error", retryable=False)
                return
            payload = alert_payload(alert)
            alert_id = alert.alert_id
            node_id = alert.node_id

        try:
            assert self.sender is not None
            self.sender(payload, alert_id)
        except DeliveryError as exc:
            self._finish_failure(delivery_id, exc.error_code, retryable=exc.retryable)
            return
        except Exception:
            self._finish_failure(delivery_id, "delivery_error", retryable=True)
            return

        now = self.clock()
        with self.sessions.begin() as session:
            row = session.get(NotificationOutbox, delivery_id)
            if row is None or row.state != "sending":
                return
            row.state = "delivered"
            row.delivered_at = now
            row.next_attempt_at = None
            row.last_error_code = None
            attempt_count = row.attempt_count
        self._write_state(node_id, "delivered", alert_id, attempt_count, None, now)

    def _finish_failure(self, delivery_id: str, error_code: str, *, retryable: bool) -> None:
        now = self.clock()
        with self.sessions.begin() as session:
            row = session.get(NotificationOutbox, delivery_id)
            if row is None or row.state != "sending":
                return
            alert = session.get(Alert, row.alert_id)
            node_id = alert.node_id if alert is not None else "unknown"
            alert_id = row.alert_id
            attempt_count = row.attempt_count + 1
            terminal = not retryable or attempt_count >= self.max_attempts
            row.attempt_count = attempt_count
            row.last_error_code = (
                error_code if _SAFE_ERROR.fullmatch(error_code) else "delivery_error"
            )
            if terminal:
                row.state = "failed_terminal"
                row.next_attempt_at = None
            else:
                row.state = "pending"
                row.next_attempt_at = now + timedelta(seconds=self._backoff(attempt_count))
            state = row.state
        self._write_state(node_id, state, alert_id, attempt_count, error_code, now)

    def _backoff(self, attempt_count: int) -> float:
        base = min(MAX_BACKOFF_S, INITIAL_BACKOFF_S * (2 ** (attempt_count - 1)))
        jittered = base * float(self.rng.uniform(0.5, 1.5))
        return float(min(MAX_BACKOFF_S, max(1.0, jittered)))

    def _write_state(
        self,
        node_id: str,
        state: str,
        alert_id: str,
        attempt_count: int,
        error_code: str | None,
        now: datetime,
    ) -> None:
        if self.writer is None:
            return
        point: Any = Point("alert_notification")  # type: ignore[no-untyped-call]
        point.tag("node_id", node_id)
        point.tag("state", state)
        point.time(now, WritePrecision.MS)
        point.field("alert_id", alert_id)
        point.field("attempt_count", attempt_count)
        if error_code is not None:
            safe_code = error_code if _SAFE_ERROR.fullmatch(error_code) else "delivery_error"
            point.field("last_error_code", safe_code)
        try:
            self.writer.write(OPERATIONS_BUCKET, point)
        except Exception as exc:
            log_event(
                LOG,
                "notification_operations_write_failed",
                result="error",
                reason=type(exc).__name__,
            )


def build_sender_from_env() -> WebhookSender | None:
    """Return a configured sender; unset webhook configuration disables delivery."""
    return WebhookSender.from_env()
