"""Ingest pipeline (T053): validate -> ledger received -> Influx -> ledger stored -> ACK.

MQTT delivery is at least once; this pipeline gives accepted data an exactly-once
storage effect (plan, Telemetry, Delivery, and Clock Design):

- A new measurement is recorded as `received` and committed, written to InfluxDB
  as an idempotent point (keyed on window end and series tags), marked `stored`,
  and only then acknowledged `accepted`.
- If the process stops between the Influx write and `stored`, the redelivered
  message finds `received` and repeats the idempotent write (RESUME).
- A retry of a stored message is acknowledged `duplicate` without a new write.
- A contract violation is stored as `rejected` (terminal) and acknowledged
  `rejected`, so the node moves it to diagnostics instead of retrying forever.
- An identity reused with different bytes is a conflict: rejected, nothing is
  overwritten, and a data-quality/security event is recorded.

The application ACK is published only from `stored` or `rejected`. If InfluxDB
fails, the exception propagates, no ACK is sent, and the MQTT layer withholds
the PUBACK so the broker redelivers.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from influxdb_client import Point, WritePrecision
from sqlalchemy.orm import Session, sessionmaker

from energy_ingestion.contracts.models import Measurement
from energy_ingestion.contracts.topics import check_identity, parse_topic, topic_for
from energy_ingestion.contracts.validate import ContractError, validate_payload
from energy_ingestion.health.metrics import PipelineMetrics
from energy_ingestion.health.node_status import NodeStatusTracker
from energy_ingestion.logging import get_logger, log_event
from energy_ingestion.persistence import ledger
from energy_ingestion.persistence.db import CalibrationArtifact, IngestionLedger, transaction
from energy_ingestion.persistence.influx import (
    NOT_VALIDATED,
    OPERATIONS_BUCKET,
    RAW_BUCKET,
    VALIDATED,
    PointWriter,
    measurement_point,
)

LOG = get_logger("pipeline")
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
SCHEMA_FOR_CHANNEL = {
    "measurements": "measurement",
    "events": "node-event",
    "status": "node-status",
}


class Publisher(Protocol):
    def __call__(self, topic: str, payload: bytes, qos: int, retain: bool) -> None: ...


@dataclass(frozen=True)
class Outcome:
    result: str  # accepted | duplicate | rejected | conflict | valid
    reason: str | None = None
    ack: Mapping[str, Any] | None = None


def utc_ms(t: datetime) -> str:
    return t.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def validation_label(session: Session, revision: str | None) -> str:
    """`validated` only for an accepted `reference` calibration; never in the MVP."""
    if revision is None:
        return NOT_VALIDATED
    cal = session.get(CalibrationArtifact, revision)
    if cal is not None and cal.calibration_kind == "reference" and cal.accepted_at is not None:
        return VALIDATED
    return NOT_VALIDATED


def identity_hint(raw: bytes, topic_node: str) -> ledger.MessageIdentity | None:
    """Best-effort identity of a payload that failed validation, for a rejected ACK."""
    try:
        doc = json.loads(raw)
    except ValueError, UnicodeDecodeError:
        return None
    if not isinstance(doc, dict):
        return None
    mid, boot, seq = doc.get("message_id"), doc.get("boot_id"), doc.get("sequence")
    if not (
        isinstance(mid, str) and _UUID.match(mid) and isinstance(boot, str) and _UUID.match(boot)
    ):
        return None
    if not isinstance(seq, int) or isinstance(seq, bool) or not 0 <= seq <= 2**53 - 1:
        return None
    return ledger.MessageIdentity(mid, topic_node, boot, seq)


class IngestPipeline:
    def __init__(
        self,
        sessions: sessionmaker[Session],
        writer: PointWriter,
        publish: Publisher,
        metrics: PipelineMetrics | None = None,
        tracker: NodeStatusTracker | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.sessions = sessions
        self.writer = writer
        self.publish = publish
        self.metrics = metrics or PipelineMetrics()
        self.tracker = tracker or NodeStatusTracker()
        self.clock = clock

    # ---- entry point ----------------------------------------------------------------

    def handle(self, topic: str, raw: bytes) -> Outcome:
        received_at = self.clock()
        started = time.perf_counter()
        self.metrics.count("received")
        try:
            node_id, channel = parse_topic(topic)
        except ContractError as exc:
            return self._done(None, "rejected", exc.reason_code, started)
        if channel == "measurements":
            outcome = self._measurement(node_id, topic, raw, received_at)
        elif channel in ("status", "events"):
            outcome = self._other(node_id, channel, topic, raw, received_at)
        else:
            outcome = Outcome("rejected", "topic_invalid")
        return self._done(node_id, outcome.result, outcome.reason, started, outcome)

    # ---- measurements ---------------------------------------------------------------

    def _measurement(self, node_id: str, topic: str, raw: bytes, received_at: datetime) -> Outcome:
        sha = ledger.payload_sha256(raw)
        try:
            doc = validate_payload("measurement", raw)
            check_identity(node_id, topic, doc)
        except ContractError as exc:
            return self._reject(node_id, raw, sha, received_at, exc)
        m = Measurement.model_validate(doc)
        ident = ledger.MessageIdentity(str(m.message_id), m.node_id, str(m.boot_id), m.sequence)

        with transaction(self.sessions) as s:
            admission, row = ledger.admit(s, ident, sha, received_at)
            label = validation_label(s, m.quality.calibration_revision)
            stored_at = row.stored_at if row is not None else None
            reject_code = row.reject_code if row is not None else None

        if admission is ledger.Admission.CONFLICT:
            self._event(node_id, "conflict", "identity_conflict", ident.message_id, received_at)
            return self._ack(ident, "rejected", "identity_conflict", None, "conflict")
        if admission is ledger.Admission.REJECTED:
            return self._ack(ident, "rejected", reject_code, None, "rejected", count=True)
        if admission is ledger.Admission.DUPLICATE:
            self._seen(node_id, m.window.end, received_at)
            return self._ack(ident, "duplicate", None, stored_at, "duplicate", count=True)

        # NEW or RESUME: idempotent write first, then `stored`, then the ACK.
        point = measurement_point(
            m,
            validation=label,
            receive_lag_ms=_ms(received_at - m.window.end),
            store_lag_ms=_ms(self.clock() - m.window.end),
        )
        self.writer.write(RAW_BUCKET, point)
        stored_at = self.clock()
        with transaction(self.sessions) as s:
            fresh = s.get(IngestionLedger, ident.message_id)
            assert fresh is not None
            ledger.mark_stored(fresh, stored_at)
            stored_at = fresh.stored_at
        self._seen(node_id, m.window.end, received_at)
        self.metrics.latency(_ms(self.clock() - received_at))
        return self._ack(ident, "accepted", None, stored_at, "accepted", count=True)

    def _reject(
        self,
        node_id: str,
        raw: bytes,
        sha: str,
        received_at: datetime,
        exc: ContractError,
    ) -> Outcome:
        ident = identity_hint(raw, node_id)
        if ident is None:  # nothing to acknowledge: log and record the event only
            self._event(node_id, "rejected", exc.reason_code, "", received_at)
            return Outcome("rejected", exc.reason_code)
        with transaction(self.sessions) as s:
            admission, existing = ledger.classify(*ledger.lookup(s, ident), sha)
            if admission is ledger.Admission.NEW:
                ledger.record_rejection(s, ident, sha, received_at, exc.reason_code, exc.detail)
                code = exc.reason_code
            elif admission is ledger.Admission.REJECTED and existing is not None:
                code = existing.reject_code or exc.reason_code
            else:  # same identity as a stored or received message, but other bytes
                admission, code = ledger.Admission.CONFLICT, "identity_conflict"
        if admission is ledger.Admission.CONFLICT:
            self._event(node_id, "conflict", code, ident.message_id, received_at)
            return self._ack(ident, "rejected", code, None, "conflict")
        self._event(node_id, "rejected", code, ident.message_id, received_at)
        return self._ack(ident, "rejected", code, None, "rejected", count=True)

    def _ack(
        self,
        ident: ledger.MessageIdentity,
        status: str,
        reason: str | None,
        stored_at: datetime | None,
        result: str,
        count: bool = False,
    ) -> Outcome:
        ack: dict[str, Any] = {
            "schema_version": "1.0.0",
            "acknowledged_at": utc_ms(self.clock()),
            "message_id": ident.message_id,
            "node_id": ident.node_id,
            "boot_id": ident.boot_id,
            "sequence": ident.sequence,
            "status": status,
            "reason_code": reason,
        }
        if stored_at is not None:
            ack["stored_at"] = utc_ms(stored_at)
        payload = json.dumps(ack, separators=(",", ":")).encode()
        validate_payload("measurement-ack", payload)  # never publish an invalid ACK
        self.publish(topic_for(ident.node_id, "acks/measurements"), payload, 1, False)
        if count:
            with transaction(self.sessions) as s:
                row = s.get(IngestionLedger, ident.message_id)
                if row is not None:
                    ledger.count_ack(row)
        return Outcome(result, reason, ack)

    # ---- status and events ----------------------------------------------------------

    def _other(
        self, node_id: str, channel: str, topic: str, raw: bytes, received_at: datetime
    ) -> Outcome:
        try:
            doc = validate_payload(SCHEMA_FOR_CHANNEL[channel], raw)
            check_identity(node_id, topic, doc)
        except ContractError as exc:
            self._event(node_id, "rejected", exc.reason_code, "", received_at)
            return Outcome("rejected", exc.reason_code)
        if channel == "status":
            for t in self.tracker.on_status(doc, received_at):
                log_event(LOG, "node_state_changed", node_id=t.node_id, result=t.new, reason=t.old)
            self.write_status(received_at)
        # Events become alerts in user story 3 (T071+); here they are validated only.
        return Outcome("valid")

    # ---- operations points ----------------------------------------------------------

    def _seen(self, node_id: str, window_end: datetime, now: datetime) -> None:
        """A measurement is a sign of life; write the state at once if it changed."""
        transitions = self.tracker.on_measurement(node_id, window_end, now)
        for t in transitions:
            log_event(LOG, "node_state_changed", node_id=t.node_id, result=t.new, reason=t.old)
        if transitions:
            try:
                self.write_status(now)
            except Exception as exc:  # the 5 s heartbeat writes it again
                log_event(LOG, "status_write_failed", reason=type(exc).__name__)

    def write_status(self, now: datetime) -> None:
        for point in self.tracker.points(now):
            self.writer.write(OPERATIONS_BUCKET, point)

    def _event(
        self, node_id: str | None, result: str, reason: str, message_id: str, at: datetime
    ) -> None:
        point = (
            Point("ingest_event")
            .tag("node_id", node_id or "unknown")
            .tag("result", result)
            .field("reason", reason)
            .field("message_id", message_id)
            .time(at, WritePrecision.MS)
        )
        try:
            self.writer.write(OPERATIONS_BUCKET, point)
        except Exception as exc:  # operations data must never block measurement handling
            log_event(LOG, "ingest_event_write_failed", reason=type(exc).__name__)

    def _done(
        self,
        node_id: str | None,
        result: str,
        reason: str | None,
        started: float,
        outcome: Outcome | None = None,
    ) -> Outcome:
        if result in ("accepted", "duplicate", "rejected", "conflict"):
            self.metrics.count(result)
        message_id = outcome.ack.get("message_id") if outcome and outcome.ack else None
        log_event(
            LOG,
            "message_handled",
            node_id=node_id,
            message_id=message_id,
            result=result,
            reason=reason,
            latency_ms=round((time.perf_counter() - started) * 1000, 3),
        )
        return outcome or Outcome(result, reason)


def _ms(delta: Any) -> float:
    return float(delta.total_seconds() * 1000)
