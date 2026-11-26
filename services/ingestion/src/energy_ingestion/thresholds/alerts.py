"""Node events to audited alerts (T084; plan, Threshold and alert lifecycle).

Server state machine (data-model, Alert):

    (event)      --threshold_entered / quality lost--> open
    open         --operator receipt------------------> acknowledged
    open         --physical clear--------------------> resolved
    acknowledged --physical clear--------------------> resolved

- `threshold_entered` opens an `active_power_threshold` alert; `threshold_cleared`
  resolves the node's unresolved threshold alerts. Acknowledgment records operator
  receipt only and never clears the physical condition.
- `measurement_quality_changed` to `invalid`/`degraded` opens one
  `measurement_quality` alert per node (while one is unresolved, further losses
  are absorbed); back to `valid` resolves it.
- The source `event_id` is unique per alert, so a redelivered event changes
  nothing. Each opened alert gets exactly one webhook `NotificationOutbox` row in
  the same transaction (contract item 1); the worker delivers it.
- Every state change appends an `AlertTransition` (append-only) and one
  `alert_transition` point for the dashboard (contract item 5). The point is written
  only after the transaction commits, and a failed write is logged, never raised.
- Threshold events are cross-checked against the stored `ThresholdConfiguration`
  of the event's `config_version` and against the nearby valid 5 s windows. A
  disagreement opens a `pipeline_health` alert (derived event id, so it is
  idempotent too) and leaves the node's alert exactly as the node reported it.

`acknowledge()` and `list_alerts()` are the interface `energyctl alert` uses.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from influxdb_client import Point, WritePrecision
from sqlalchemy import event as sa_event
from sqlalchemy import select
from sqlalchemy.orm import Session

from energy_ingestion.contracts.models import NodeEvent
from energy_ingestion.logging import get_logger, log_event
from energy_ingestion.persistence.db import (
    Alert,
    AlertTransition,
    NotificationOutbox,
    ThresholdConfiguration,
)
from energy_ingestion.persistence.influx import OPERATIONS_BUCKET, PointWriter

LOG = get_logger("alerts")
STATUSES = ("open", "acknowledged", "resolved")
UNRESOLVED = ("open", "acknowledged")
DESTINATION = "webhook"
TRANSITION_MEASUREMENT = "alert_transition"
# Namespace of the derived event ids of cross-check health alerts (fixed forever).
HEALTH_NAMESPACE = uuid.UUID("6f1c2b0e-3d4a-4b7e-9c55-2f8e1d0a7b31")
VALUE_TOLERANCE = 0.0005  # W; the node sends three decimals
WINDOW_TOLERANCE_W = 0.01  # rounding of the 5 s mean against the limit
SPAN_SLACK = timedelta(milliseconds=500)  # block vs window boundary jitter
_POINTS_KEY = "alert_points"


@dataclass(frozen=True)
class RecentWindow:
    """A stored valid 5 s window, kept in memory for the cross-check."""

    start: datetime
    end: datetime
    power_w: float


@dataclass(frozen=True)
class EventResult:
    result: str  # opened | resolved | duplicate | ignored
    alert_id: str | None = None
    health_alert_id: str | None = None


# ---- operations points ----------------------------------------------------------------


def _notification_state(session: Session, alert_id: str) -> str:
    box = session.scalar(
        select(NotificationOutbox).where(
            NotificationOutbox.alert_id == alert_id,
            NotificationOutbox.destination_type == DESTINATION,
        )
    )
    return box.state if box is not None else "none"


def transition_point(alert: Alert, t: AlertTransition, notification_state: str) -> Point:
    point = (
        Point(TRANSITION_MEASUREMENT)
        .tag("node_id", alert.node_id)
        .tag("kind", alert.kind)
        .tag("severity", alert.severity)
        .tag("to_status", t.to_status)
        .field("alert_id", alert.alert_id)
        .field("from_status", t.from_status or "")
        .field("actor", t.actor)
        .field("reason", t.reason)
        .field("notification_state", notification_state)
        .time(t.at, WritePrecision.MS)
    )
    if alert.observed_value is not None:
        point.field("observed_value", float(alert.observed_value))
    if alert.threshold_value is not None:
        point.field("threshold_value", float(alert.threshold_value))
    return point


def take_points(session: Session) -> list[Point]:
    """Points of this unit of work; write them only after it committed."""
    points: list[Point] = session.info.pop(_POINTS_KEY, [])
    return points


def write_points(writer: PointWriter, points: Sequence[Point]) -> None:
    for point in points:
        try:
            writer.write(OPERATIONS_BUCKET, point)
        except Exception as exc:  # operations data never blocks alert handling
            log_event(LOG, "alert_point_write_failed", reason=type(exc).__name__)


def _write_after_commit(session: Session, writer: PointWriter) -> None:
    def _flush(_session: Session) -> None:
        write_points(writer, take_points(session))

    def _drop(_session: Session) -> None:
        take_points(session)

    sa_event.listen(session, "after_commit", _flush, once=True)
    sa_event.listen(session, "after_rollback", _drop, once=True)


def _transition(
    session: Session, alert: Alert, to_status: str, actor: str, reason: str, at: datetime
) -> AlertTransition:
    from_status = None if to_status == "open" else alert.status
    t = AlertTransition(
        alert_id=alert.alert_id,
        from_status=from_status,
        to_status=to_status,
        actor=actor[:80],
        reason=reason[:256],
        at=at,
    )
    alert.status = to_status
    session.add(t)
    session.flush()
    session.info.setdefault(_POINTS_KEY, []).append(
        transition_point(alert, t, _notification_state(session, alert.alert_id))
    )
    return t


# ---- opening and resolving ---------------------------------------------------------------


def _open(
    session: Session,
    *,
    event_id: str,
    node_id: str,
    circuit_id: str | None,
    kind: str,
    severity: str,
    observed: float | None,
    threshold: float | None,
    unit: str | None,
    quality: str | None,
    actor: str,
    reason: str,
    at: datetime,
) -> Alert:
    alert = Alert(
        alert_id=str(uuid.uuid4()),
        event_id=event_id,
        node_id=node_id,
        circuit_id=circuit_id,
        kind=kind,
        severity=severity,
        status="open",
        opened_at=at,
        observed_value=observed,
        threshold_value=threshold,
        unit=unit,
        quality=quality,
    )
    session.add(alert)
    session.add(
        NotificationOutbox(
            delivery_id=str(uuid.uuid4()),
            alert_id=alert.alert_id,
            destination_type=DESTINATION,
            state="pending",
            attempt_count=0,
            next_attempt_at=at,
        )
    )
    session.flush()
    _transition(session, alert, "open", actor, reason, at)
    log_event(LOG, "alert_opened", node_id=node_id, result=kind, reason=reason)
    return alert


def _unresolved(session: Session, node_id: str, kind: str) -> list[Alert]:
    return list(
        session.scalars(
            select(Alert)
            .where(Alert.node_id == node_id, Alert.kind == kind, Alert.status.in_(UNRESOLVED))
            .order_by(Alert.opened_at)
        )
    )


def _resolve_all(
    session: Session, node_id: str, kind: str, actor: str, reason: str, at: datetime
) -> list[Alert]:
    found = _unresolved(session, node_id, kind)
    for alert in found:
        alert.resolved_at = at
        _transition(session, alert, "resolved", actor, reason, at)
    return found


# ---- cross-check -------------------------------------------------------------------------


def cross_check(
    ev: NodeEvent, config: ThresholdConfiguration | None, recent: Sequence[RecentWindow]
) -> str | None:
    """Reason the event disagrees with the stored config or the measurements, else None.

    A window lying entirely inside the confirmation (or clearing) span consists only
    of blocks the node saw above the limit (or below the clear threshold), so its
    mean must be too. Windows not yet received are simply not evidence.
    """
    if ev.event_type not in ("threshold_entered", "threshold_cleared"):
        return None
    if config is None:
        return "config_unknown"
    entered = ev.event_type == "threshold_entered"
    expected = float(config.active_power_limit_w if entered else config.clear_below_w)
    if ev.threshold_value is None or abs(ev.threshold_value - expected) > VALUE_TOLERANCE:
        return "config_mismatch"
    value = ev.measured_value
    if value is None or (value <= expected if entered else value >= expected):
        return "value_not_above_limit" if entered else "value_not_below_clear"
    span_ms = config.confirm_ms if entered else config.clear_ms
    lo = ev.observed_at - timedelta(milliseconds=span_ms) - SPAN_SLACK
    hi = ev.observed_at + SPAN_SLACK
    for w in recent:
        if w.start < lo or w.end > hi:
            continue
        agrees = (
            w.power_w > expected - WINDOW_TOLERANCE_W
            if entered
            else w.power_w < expected + WINDOW_TOLERANCE_W
        )
        if not agrees:
            return "measurement_disagrees"
    return None


def _health_alert(
    session: Session,
    ev: NodeEvent,
    config: ThresholdConfiguration | None,
    reason: str,
    at: datetime,
) -> Alert | None:
    event_id = str(uuid.uuid5(HEALTH_NAMESPACE, f"cross-check/{ev.event_id}"))
    if session.scalar(select(Alert).where(Alert.event_id == event_id)) is not None:
        return None
    stored: float | None = None
    if config is not None:
        stored = float(
            config.active_power_limit_w
            if ev.event_type == "threshold_entered"
            else config.clear_below_w
        )
    log_event(LOG, "cross_check_disagreement", node_id=ev.node_id, reason=reason)
    return _open(
        session,
        event_id=event_id,
        node_id=ev.node_id,
        circuit_id=ev.circuit_id,
        kind="pipeline_health",
        severity="warning",
        observed=ev.measured_value,
        threshold=stored,
        unit="W",
        quality=ev.quality,
        actor="system:cross-check",
        reason=f"cross_check:{reason}",
        at=at,
    )


# ---- entry points ------------------------------------------------------------------------


def handle_event(
    session: Session, ev: NodeEvent, now: datetime, recent: Sequence[RecentWindow] = ()
) -> EventResult:
    """Apply one validated node event; idempotent on `event_id`."""
    event_id = str(ev.event_id)
    existing = session.scalar(select(Alert).where(Alert.event_id == event_id))
    if existing is not None:
        return EventResult("duplicate", existing.alert_id)
    actor = f"node:{ev.node_id}"
    health_id: str | None = None
    if ev.event_type in ("threshold_entered", "threshold_cleared"):
        config = session.get(ThresholdConfiguration, (ev.node_id, ev.config_version))
        disagreement = cross_check(ev, config, recent)
        if disagreement is not None:
            h = _health_alert(session, ev, config, disagreement, now)
            health_id = h.alert_id if h is not None else None

    if ev.event_type == "threshold_entered":
        alert = _open(
            session,
            event_id=event_id,
            node_id=ev.node_id,
            circuit_id=ev.circuit_id,
            kind="active_power_threshold",
            severity=ev.severity if ev.severity in ("warning", "critical") else "warning",
            observed=ev.measured_value,
            threshold=ev.threshold_value,
            unit=ev.unit if ev.unit == "W" else None,
            quality=ev.quality,
            actor=actor,
            reason="threshold_entered",
            at=now,
        )
        return EventResult("opened", alert.alert_id, health_id)
    if ev.event_type == "threshold_cleared":
        done = _resolve_all(
            session, ev.node_id, "active_power_threshold", actor, "threshold_cleared", now
        )
        return EventResult(
            "resolved" if done else "ignored", done[-1].alert_id if done else None, health_id
        )
    # measurement_quality_changed
    if ev.quality == "valid":
        done = _resolve_all(
            session, ev.node_id, "measurement_quality", actor, ev.reason_code or "quality", now
        )
        return EventResult("resolved" if done else "ignored", done[-1].alert_id if done else None)
    if _unresolved(session, ev.node_id, "measurement_quality"):
        return EventResult("ignored")
    alert = _open(
        session,
        event_id=event_id,
        node_id=ev.node_id,
        circuit_id=ev.circuit_id,
        kind="measurement_quality",
        severity="critical" if ev.severity == "critical" else "warning",
        observed=None,
        threshold=None,
        unit=None,
        quality=ev.quality,
        actor=actor,
        reason=ev.reason_code or "measurement_quality_changed",
        at=now,
    )
    return EventResult("opened", alert.alert_id)


def acknowledge(
    session: Session,
    alert_id: str,
    actor: str,
    now: datetime,
    writer: PointWriter | None = None,
) -> Alert:
    """Record operator receipt (contract item 2). Never clears the physical condition.

    Raises KeyError for an unknown alert and ValueError for a resolved one; an
    already acknowledged alert is returned unchanged. With `writer`, the
    `alert_transition` point is written once the caller's transaction commits.
    """
    alert = session.get(Alert, alert_id)
    if alert is None:
        raise KeyError(alert_id)
    if alert.status == "resolved":
        raise ValueError(f"alert {alert_id} is already resolved")
    if alert.status == "acknowledged":
        return alert
    alert.acknowledged_at = now
    _transition(session, alert, "acknowledged", actor, "operator_receipt", now)
    if writer is not None:
        _write_after_commit(session, writer)
    return alert


def list_alerts(session: Session, status: str | None = None) -> list[Alert]:
    """Alerts, newest first, optionally only one status."""
    query = select(Alert).order_by(Alert.opened_at.desc(), Alert.alert_id)
    if status is not None:
        if status not in STATUSES:
            raise ValueError(f"unknown status {status!r}")
        query = query.where(Alert.status == status)
    return list(session.scalars(query))


__all__: list[str] = [
    "EventResult",
    "RecentWindow",
    "acknowledge",
    "cross_check",
    "handle_event",
    "list_alerts",
    "take_points",
    "transition_point",
    "write_points",
]
