"""Initial SQLite schema (T021, data-model.md).

Tables: monitoring_node, circuit, calibration_artifact, threshold_configuration,
ingestion_ledger, alert, alert_transition, notification_outbox. Timestamps are
RFC 3339 UTC text. WAL mode is set on every connection (persistence/db.py).
Triggers make alert_transition append-only and calibration_artifact immutable
except for the one-time acceptance fields.

Revision ID: 0001
Revises:
Create Date: 2026-11-25 11:19:25.680922
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


TRIGGERS = (
    """CREATE TRIGGER alert_transition_no_update BEFORE UPDATE ON alert_transition
    BEGIN SELECT RAISE(ABORT, 'alert_transition is append-only'); END""",
    """CREATE TRIGGER alert_transition_no_delete BEFORE DELETE ON alert_transition
    BEGIN SELECT RAISE(ABORT, 'alert_transition is append-only'); END""",
    """CREATE TRIGGER calibration_artifact_no_delete BEFORE DELETE ON calibration_artifact
    BEGIN SELECT RAISE(ABORT, 'calibration_artifact is append-only'); END""",
    """CREATE TRIGGER calibration_artifact_immutable BEFORE UPDATE ON calibration_artifact
    WHEN OLD.accepted_at IS NOT NULL
      OR NEW.calibration_revision IS NOT OLD.calibration_revision
      OR NEW.node_id IS NOT OLD.node_id
      OR NEW.hardware_revision IS NOT OLD.hardware_revision
      OR NEW.firmware_commit IS NOT OLD.firmware_commit
      OR NEW.calibration_kind IS NOT OLD.calibration_kind
      OR NEW.reference_meter_id IS NOT OLD.reference_meter_id
      OR NEW.current_sensor_variant IS NOT OLD.current_sensor_variant
      OR NEW.voltage_gain IS NOT OLD.voltage_gain
      OR NEW.current_gain IS NOT OLD.current_gain
      OR NEW.phase_correction_samples IS NOT OLD.phase_correction_samples
      OR NEW.zero_noise_current_a IS NOT OLD.zero_noise_current_a
      OR NEW.procedure_version IS NOT OLD.procedure_version
      OR NEW.dataset_manifest_sha256 IS NOT OLD.dataset_manifest_sha256
    BEGIN SELECT RAISE(ABORT, 'calibration_artifact is immutable; create a new revision'); END""",
    """CREATE TRIGGER ingestion_ledger_terminal BEFORE UPDATE OF state ON ingestion_ledger
    WHEN OLD.state != 'received' AND NEW.state != OLD.state
    BEGIN SELECT RAISE(ABORT, 'ledger state stored/rejected is terminal'); END""",
)
TRIGGER_NAMES = (
    "alert_transition_no_update",
    "alert_transition_no_delete",
    "calibration_artifact_no_delete",
    "calibration_artifact_immutable",
    "ingestion_ledger_terminal",
)


def upgrade() -> None:
    op.create_table(
        "alert",
        sa.Column("alert_id", sa.String(length=36), nullable=False),
        sa.Column("event_id", sa.String(length=36), nullable=False),
        sa.Column("node_id", sa.String(length=32), nullable=False),
        sa.Column("circuit_id", sa.String(length=32), nullable=True),
        sa.Column(
            "kind",
            sa.Enum(
                "active_power_threshold",
                "measurement_quality",
                "node_offline",
                "pipeline_health",
                name="alert_kind",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "severity",
            sa.Enum(
                "warning",
                "critical",
                name="alert_severity",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "open",
                "acknowledged",
                "resolved",
                name="alert_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("opened_at", sa.String(length=24), nullable=False),
        sa.Column("acknowledged_at", sa.String(length=24), nullable=True),
        sa.Column("resolved_at", sa.String(length=24), nullable=True),
        sa.Column("observed_value", sa.Double(), nullable=True),
        sa.Column("threshold_value", sa.Double(), nullable=True),
        sa.Column("unit", sa.String(length=8), nullable=True),
        sa.Column(
            "quality",
            sa.Enum(
                "valid",
                "degraded",
                "invalid",
                name="alert_quality",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("alert_id"),
        sa.UniqueConstraint("event_id"),
    )
    op.create_table(
        "ingestion_ledger",
        sa.Column("message_id", sa.String(length=36), nullable=False),
        sa.Column("node_id", sa.String(length=32), nullable=False),
        sa.Column("boot_id", sa.String(length=36), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("payload_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "state",
            sa.Enum(
                "received",
                "stored",
                "rejected",
                name="ledger_state",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("received_at", sa.String(length=24), nullable=False),
        sa.Column("stored_at", sa.String(length=24), nullable=True),
        sa.Column("reject_code", sa.String(length=64), nullable=True),
        sa.Column("reject_detail", sa.String(length=256), nullable=True),
        sa.Column("ack_count", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "state != 'rejected' OR reject_code IS NOT NULL", name="rejected_has_code"
        ),
        sa.CheckConstraint("state != 'stored' OR stored_at IS NOT NULL", name="stored_has_time"),
        sa.CheckConstraint("ack_count >= 0", name="ack_count_non_negative"),
        sa.CheckConstraint("length(payload_sha256) = 64", name="sha256_length"),
        sa.PrimaryKeyConstraint("message_id"),
        sa.UniqueConstraint("node_id", "boot_id", "sequence", name="uq_ledger_identity"),
    )
    op.create_table(
        "monitoring_node",
        sa.Column("node_id", sa.String(length=32), nullable=False),
        sa.Column("display_name", sa.String(length=80), nullable=False),
        sa.Column("certificate_subject", sa.String(length=128), nullable=False),
        sa.Column("hardware_revision", sa.String(length=64), nullable=False),
        sa.Column("firmware_version", sa.String(length=64), nullable=True),
        sa.Column("calibration_revision", sa.String(length=64), nullable=True),
        sa.Column("last_seen_at", sa.String(length=24), nullable=True),
        sa.Column("last_valid_observed_at", sa.String(length=24), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "provisioning",
                "online",
                "stale",
                "offline",
                "degraded",
                name="node_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(node_id) BETWEEN 1 AND 32 AND node_id GLOB '[a-z0-9]*' AND node_id NOT GLOB '*[^a-z0-9-]*'",
            name="node_id_format",
        ),
        sa.PrimaryKeyConstraint("node_id"),
        sa.UniqueConstraint("certificate_subject"),
    )
    op.create_table(
        "alert_transition",
        sa.Column("transition_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("alert_id", sa.String(length=36), nullable=False),
        sa.Column("from_status", sa.String(length=16), nullable=True),
        sa.Column("to_status", sa.String(length=16), nullable=False),
        sa.Column("actor", sa.String(length=80), nullable=False),
        sa.Column("reason", sa.String(length=256), nullable=False),
        sa.Column("at", sa.String(length=24), nullable=False),
        sa.ForeignKeyConstraint(
            ["alert_id"],
            ["alert.alert_id"],
        ),
        sa.PrimaryKeyConstraint("transition_id"),
    )
    op.create_table(
        "calibration_artifact",
        sa.Column("calibration_revision", sa.String(length=64), nullable=False),
        sa.Column("node_id", sa.String(length=32), nullable=False),
        sa.Column("hardware_revision", sa.String(length=64), nullable=False),
        sa.Column("firmware_commit", sa.String(length=64), nullable=False),
        sa.Column(
            "calibration_kind",
            sa.Enum(
                "nominal",
                "reference",
                name="calibration_kind",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("reference_meter_id", sa.String(length=64), nullable=True),
        sa.Column(
            "current_sensor_variant",
            sa.Enum(
                "05B",
                "20A",
                "30A",
                name="current_sensor_variant",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("voltage_gain", sa.Numeric(precision=18, scale=9), nullable=False),
        sa.Column("current_gain", sa.Numeric(precision=18, scale=9), nullable=False),
        sa.Column("phase_correction_samples", sa.Numeric(precision=10, scale=6), nullable=False),
        sa.Column("zero_noise_current_a", sa.Numeric(precision=10, scale=6), nullable=False),
        sa.Column("procedure_version", sa.String(length=64), nullable=False),
        sa.Column("dataset_manifest_sha256", sa.String(length=64), nullable=False),
        sa.Column("accepted_at", sa.String(length=24), nullable=True),
        sa.Column("accepted_by", sa.String(length=80), nullable=True),
        sa.CheckConstraint(
            "(calibration_kind = 'nominal' AND reference_meter_id IS NULL) OR (calibration_kind = 'reference' AND reference_meter_id IS NOT NULL)",
            name="reference_meter_matches_kind",
        ),
        sa.CheckConstraint(
            "(accepted_at IS NULL) = (accepted_by IS NULL)", name="acceptance_complete"
        ),
        sa.CheckConstraint("length(dataset_manifest_sha256) = 64", name="manifest_sha256_length"),
        sa.ForeignKeyConstraint(
            ["node_id"],
            ["monitoring_node.node_id"],
        ),
        sa.PrimaryKeyConstraint("calibration_revision"),
    )
    op.create_table(
        "circuit",
        sa.Column("circuit_id", sa.String(length=32), nullable=False),
        sa.Column("node_id", sa.String(length=32), nullable=False),
        sa.Column("display_name", sa.String(length=80), nullable=False),
        sa.Column("nominal_voltage_v", sa.Numeric(precision=8, scale=3), nullable=False),
        sa.Column("calibrated_voltage_min_v", sa.Numeric(precision=8, scale=3), nullable=False),
        sa.Column("calibrated_voltage_max_v", sa.Numeric(precision=8, scale=3), nullable=False),
        sa.Column("calibrated_current_min_a", sa.Numeric(precision=8, scale=3), nullable=False),
        sa.Column("calibrated_current_max_a", sa.Numeric(precision=8, scale=3), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.CheckConstraint(
            "length(circuit_id) BETWEEN 1 AND 32 AND circuit_id GLOB '[a-z0-9]*' AND circuit_id NOT GLOB '*[^a-z0-9-]*'",
            name="circuit_id_format",
        ),
        sa.CheckConstraint(
            "calibrated_current_min_a < calibrated_current_max_a", name="current_range_order"
        ),
        sa.CheckConstraint(
            "calibrated_voltage_min_v < calibrated_voltage_max_v", name="voltage_range_order"
        ),
        sa.ForeignKeyConstraint(
            ["node_id"],
            ["monitoring_node.node_id"],
        ),
        sa.PrimaryKeyConstraint("circuit_id"),
        sa.UniqueConstraint("node_id"),
    )
    op.create_table(
        "notification_outbox",
        sa.Column("delivery_id", sa.String(length=36), nullable=False),
        sa.Column("alert_id", sa.String(length=36), nullable=False),
        sa.Column("destination_type", sa.String(length=32), nullable=False),
        sa.Column(
            "state",
            sa.Enum(
                "pending",
                "sending",
                "delivered",
                "failed_terminal",
                name="outbox_state",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.String(length=24), nullable=True),
        sa.Column("last_error_code", sa.String(length=64), nullable=True),
        sa.Column("delivered_at", sa.String(length=24), nullable=True),
        sa.CheckConstraint("attempt_count >= 0", name="attempt_count_non_negative"),
        sa.ForeignKeyConstraint(
            ["alert_id"],
            ["alert.alert_id"],
        ),
        sa.PrimaryKeyConstraint("delivery_id"),
        sa.UniqueConstraint("alert_id", "destination_type", name="uq_outbox_alert_destination"),
    )
    op.create_table(
        "threshold_configuration",
        sa.Column("node_id", sa.String(length=32), nullable=False),
        sa.Column("config_version", sa.Integer(), nullable=False),
        sa.Column("circuit_id", sa.String(length=32), nullable=False),
        sa.Column("active_power_limit_w", sa.Numeric(precision=10, scale=3), nullable=False),
        sa.Column("confirm_ms", sa.Integer(), nullable=False),
        sa.Column("clear_below_w", sa.Numeric(precision=10, scale=3), nullable=False),
        sa.Column("clear_ms", sa.Integer(), nullable=False),
        sa.Column(
            "severity",
            sa.Enum(
                "warning",
                "critical",
                name="threshold_severity",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("local_warning_enabled", sa.Boolean(), nullable=False),
        sa.Column("effective_at", sa.String(length=24), nullable=False),
        sa.Column("created_by", sa.String(length=80), nullable=False),
        sa.CheckConstraint(
            "active_power_limit_w > 0 AND active_power_limit_w <= 25", name="limit_mvp_range"
        ),
        sa.CheckConstraint(
            "clear_below_w >= 0 AND clear_below_w < active_power_limit_w", name="clear_below_limit"
        ),
        sa.CheckConstraint("clear_ms BETWEEN 1000 AND 300000", name="clear_ms_range"),
        sa.CheckConstraint("config_version >= 1", name="config_version_positive"),
        sa.CheckConstraint("confirm_ms BETWEEN 1000 AND 300000", name="confirm_ms_range"),
        sa.ForeignKeyConstraint(
            ["circuit_id"],
            ["circuit.circuit_id"],
        ),
        sa.ForeignKeyConstraint(
            ["node_id"],
            ["monitoring_node.node_id"],
        ),
        sa.PrimaryKeyConstraint("node_id", "config_version"),
    )

    for ddl in TRIGGERS:
        op.execute(ddl)


def downgrade() -> None:
    for name in TRIGGER_NAMES:
        op.execute(f"DROP TRIGGER IF EXISTS {name}")
    op.drop_table("threshold_configuration")
    op.drop_table("notification_outbox")
    op.drop_table("circuit")
    op.drop_table("calibration_artifact")
    op.drop_table("alert_transition")
    op.drop_table("monitoring_node")
    op.drop_table("ingestion_ledger")
    op.drop_table("alert")
