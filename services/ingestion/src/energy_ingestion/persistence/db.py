"""SQLite engine, session factory, and ORM tables (data-model.md, T021-T022).

The Alembic migration `0001_initial` is the source of the physical schema; these
mappings must match it (checked by `tests/test_migrations.py`).
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Dialect,
    Engine,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    create_engine,
    event,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from sqlalchemy.types import TypeDecorator

IDENTIFIER_CHECK = (
    "length({c}) BETWEEN 1 AND 32 AND {c} GLOB '[a-z0-9]*' AND {c} NOT GLOB '*[^a-z0-9-]*'"
)


def utc_now() -> datetime:
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator[datetime]):
    """Stored as RFC 3339 UTC text with milliseconds and `Z`; naive values are refused."""

    impl = String(24)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> str | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("timestamps must be timezone-aware")
        return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")

    def process_result_value(self, value: str | None, dialect: Dialect) -> datetime | None:
        return None if value is None else datetime.fromisoformat(value)


def _enum(*values: str, name: str) -> Enum:
    return Enum(*values, name=name, native_enum=False, create_constraint=True, length=32)


class Base(DeclarativeBase):
    pass


class MonitoringNode(Base):
    __tablename__ = "monitoring_node"
    __table_args__ = (CheckConstraint(IDENTIFIER_CHECK.format(c="node_id"), name="node_id_format"),)

    node_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(80))
    certificate_subject: Mapped[str] = mapped_column(String(128), unique=True)
    hardware_revision: Mapped[str] = mapped_column(String(64))
    firmware_version: Mapped[str | None] = mapped_column(String(64))
    calibration_revision: Mapped[str | None] = mapped_column(String(64))
    last_seen_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    last_valid_observed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    status: Mapped[str] = mapped_column(
        _enum("provisioning", "online", "stale", "offline", "degraded", name="node_status"),
        default="provisioning",
    )


class Circuit(Base):
    __tablename__ = "circuit"
    __table_args__ = (
        CheckConstraint(IDENTIFIER_CHECK.format(c="circuit_id"), name="circuit_id_format"),
        CheckConstraint(
            "calibrated_voltage_min_v < calibrated_voltage_max_v", name="voltage_range_order"
        ),
        CheckConstraint(
            "calibrated_current_min_a < calibrated_current_max_a", name="current_range_order"
        ),
    )

    circuit_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    node_id: Mapped[str] = mapped_column(ForeignKey("monitoring_node.node_id"), unique=True)
    display_name: Mapped[str] = mapped_column(String(80))
    nominal_voltage_v: Mapped[Decimal] = mapped_column(Numeric(8, 3), default=Decimal(12))
    calibrated_voltage_min_v: Mapped[Decimal] = mapped_column(Numeric(8, 3), default=Decimal(10))
    calibrated_voltage_max_v: Mapped[Decimal] = mapped_column(Numeric(8, 3), default=Decimal(16))
    calibrated_current_min_a: Mapped[Decimal] = mapped_column(Numeric(8, 3), default=Decimal("0.5"))
    calibrated_current_max_a: Mapped[Decimal] = mapped_column(Numeric(8, 3), default=Decimal("2.0"))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class CalibrationArtifact(Base):
    __tablename__ = "calibration_artifact"
    __table_args__ = (
        CheckConstraint(
            "(calibration_kind = 'nominal' AND reference_meter_id IS NULL) OR "
            "(calibration_kind = 'reference' AND reference_meter_id IS NOT NULL)",
            name="reference_meter_matches_kind",
        ),
        CheckConstraint(
            "(accepted_at IS NULL) = (accepted_by IS NULL)", name="acceptance_complete"
        ),
        CheckConstraint("length(dataset_manifest_sha256) = 64", name="manifest_sha256_length"),
    )

    calibration_revision: Mapped[str] = mapped_column(String(64), primary_key=True)
    node_id: Mapped[str] = mapped_column(ForeignKey("monitoring_node.node_id"))
    hardware_revision: Mapped[str] = mapped_column(String(64))
    firmware_commit: Mapped[str] = mapped_column(String(64))
    calibration_kind: Mapped[str] = mapped_column(
        _enum("nominal", "reference", name="calibration_kind")
    )
    reference_meter_id: Mapped[str | None] = mapped_column(String(64))
    current_sensor_variant: Mapped[str] = mapped_column(
        _enum("05B", "20A", "30A", name="current_sensor_variant")
    )
    voltage_gain: Mapped[Decimal] = mapped_column(Numeric(18, 9))
    current_gain: Mapped[Decimal] = mapped_column(Numeric(18, 9))
    phase_correction_samples: Mapped[Decimal] = mapped_column(Numeric(10, 6))
    zero_noise_current_a: Mapped[Decimal] = mapped_column(Numeric(10, 6))
    procedure_version: Mapped[str] = mapped_column(String(64))
    dataset_manifest_sha256: Mapped[str] = mapped_column(String(64))
    accepted_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    accepted_by: Mapped[str | None] = mapped_column(String(80))


class ThresholdConfiguration(Base):
    __tablename__ = "threshold_configuration"
    __table_args__ = (
        CheckConstraint(
            "active_power_limit_w > 0 AND active_power_limit_w <= 25", name="limit_mvp_range"
        ),
        CheckConstraint(
            "clear_below_w >= 0 AND clear_below_w < active_power_limit_w", name="clear_below_limit"
        ),
        CheckConstraint("confirm_ms BETWEEN 1000 AND 300000", name="confirm_ms_range"),
        CheckConstraint("clear_ms BETWEEN 1000 AND 300000", name="clear_ms_range"),
        CheckConstraint("config_version >= 1", name="config_version_positive"),
    )

    node_id: Mapped[str] = mapped_column(ForeignKey("monitoring_node.node_id"), primary_key=True)
    config_version: Mapped[int] = mapped_column(Integer, primary_key=True)
    circuit_id: Mapped[str] = mapped_column(ForeignKey("circuit.circuit_id"))
    active_power_limit_w: Mapped[Decimal] = mapped_column(Numeric(10, 3))
    confirm_ms: Mapped[int] = mapped_column(Integer, default=10000)
    clear_below_w: Mapped[Decimal] = mapped_column(Numeric(10, 3))
    clear_ms: Mapped[int] = mapped_column(Integer)
    severity: Mapped[str] = mapped_column(_enum("warning", "critical", name="threshold_severity"))
    local_warning_enabled: Mapped[bool] = mapped_column(Boolean)
    effective_at: Mapped[datetime] = mapped_column(UTCDateTime())
    created_by: Mapped[str] = mapped_column(String(80))


class IngestionLedger(Base):
    __tablename__ = "ingestion_ledger"
    __table_args__ = (
        UniqueConstraint("node_id", "boot_id", "sequence", name="uq_ledger_identity"),
        CheckConstraint("length(payload_sha256) = 64", name="sha256_length"),
        CheckConstraint("state != 'stored' OR stored_at IS NOT NULL", name="stored_has_time"),
        CheckConstraint("state != 'rejected' OR reject_code IS NOT NULL", name="rejected_has_code"),
        CheckConstraint("ack_count >= 0", name="ack_count_non_negative"),
    )

    message_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    node_id: Mapped[str] = mapped_column(String(32))
    boot_id: Mapped[str] = mapped_column(String(36))
    sequence: Mapped[int] = mapped_column(Integer)
    payload_sha256: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(_enum("received", "stored", "rejected", name="ledger_state"))
    received_at: Mapped[datetime] = mapped_column(UTCDateTime())
    stored_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    reject_code: Mapped[str | None] = mapped_column(String(64))
    reject_detail: Mapped[str | None] = mapped_column(String(256))
    ack_count: Mapped[int] = mapped_column(Integer, default=0)


class Alert(Base):
    __tablename__ = "alert"

    alert_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(36), unique=True)
    node_id: Mapped[str] = mapped_column(String(32))
    circuit_id: Mapped[str | None] = mapped_column(String(32))
    kind: Mapped[str] = mapped_column(
        _enum(
            "active_power_threshold",
            "measurement_quality",
            "node_offline",
            "pipeline_health",
            name="alert_kind",
        )
    )
    severity: Mapped[str] = mapped_column(_enum("warning", "critical", name="alert_severity"))
    status: Mapped[str] = mapped_column(
        _enum("open", "acknowledged", "resolved", name="alert_status")
    )
    opened_at: Mapped[datetime] = mapped_column(UTCDateTime())
    acknowledged_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    observed_value: Mapped[float | None] = mapped_column()
    threshold_value: Mapped[float | None] = mapped_column()
    unit: Mapped[str | None] = mapped_column(String(8))
    quality: Mapped[str | None] = mapped_column(
        _enum("valid", "degraded", "invalid", name="alert_quality")
    )


class AlertTransition(Base):
    """Append-only audit row; UPDATE and DELETE are blocked by triggers."""

    __tablename__ = "alert_transition"

    transition_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    alert_id: Mapped[str] = mapped_column(ForeignKey("alert.alert_id"))
    from_status: Mapped[str | None] = mapped_column(String(16))
    to_status: Mapped[str] = mapped_column(String(16))
    actor: Mapped[str] = mapped_column(String(80))
    reason: Mapped[str] = mapped_column(String(256))
    at: Mapped[datetime] = mapped_column(UTCDateTime())


class NotificationOutbox(Base):
    __tablename__ = "notification_outbox"
    __table_args__ = (
        UniqueConstraint("alert_id", "destination_type", name="uq_outbox_alert_destination"),
        CheckConstraint("attempt_count >= 0", name="attempt_count_non_negative"),
    )

    delivery_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    alert_id: Mapped[str] = mapped_column(ForeignKey("alert.alert_id"))
    destination_type: Mapped[str] = mapped_column(String(32))
    state: Mapped[str] = mapped_column(
        _enum("pending", "sending", "delivered", "failed_terminal", name="outbox_state")
    )
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    last_error_code: Mapped[str | None] = mapped_column(String(64))
    delivered_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


def sqlite_url(path: str | None = None) -> str:
    return f"sqlite:///{path or os.environ.get('SQLITE_PATH', 'energy.sqlite')}"


def make_engine(url: str | None = None) -> Engine:
    engine = create_engine(url or sqlite_url(), future=True)

    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_conn: Any, _record: Any) -> None:
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.execute("PRAGMA synchronous=FULL")
        cur.close()

    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)


@contextmanager
def transaction(factory: sessionmaker[Session]) -> Iterator[Session]:
    """One unit of work: commit on success, roll back on any error."""
    with factory() as session, session.begin():
        yield session
