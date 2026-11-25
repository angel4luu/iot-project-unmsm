"""Typed views of the five MQTT v1 payloads (T012).

Validation is always done first by `validate.validate_payload` against the
normative JSON Schemas; these models only give typed access to documents that
already passed. They forbid extra fields so a schema/model drift fails loudly
in `tests/test_contract_models.py`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from energy_ingestion.contracts.validate import validate_payload

QualityState = Literal["valid", "degraded", "invalid"]
ClockSource = Literal["sntp", "holdover", "unsynchronized"]
QualityFlag = Literal[
    "clock_unsynchronized",
    "calibration_missing",
    "sample_gap",
    "adc_crc_error",
    "adc_clipped",
    "sensor_disconnected",
    "out_of_range",
    "polarity_reversed",
    "energy_continuity_uncertain",
]


class _Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


class Window(_Contract):
    start: datetime
    end: datetime
    duration_ms: int
    sample_count: int


class Clock(_Contract):
    source: ClockSource
    last_sync_age_s: int | None


class Voltage(_Contract):
    value: float | None
    unit: Literal["V"]


class Current(_Contract):
    value: float | None
    unit: Literal["A"]


class Power(_Contract):
    value: float | None
    unit: Literal["W"]


class Energy(_Contract):
    value: float | None
    unit: Literal["Wh"]
    counter_id: UUID


class Quantities(_Contract):
    voltage_rms: Voltage
    current_rms: Current
    active_power: Power
    active_energy_import_total: Energy


class Quality(_Contract):
    state: QualityState
    flags: tuple[QualityFlag, ...]
    valid_sample_ratio: float
    calibration_revision: str | None


class Measurement(_Contract):
    schema_version: Literal["1.0.0"]
    message_id: UUID
    node_id: str
    circuit_id: str
    boot_id: UUID
    sequence: int
    window: Window
    clock: Clock
    measurements: Quantities
    quality: Quality
    uptime_ms: int


class NodeStatus(_Contract):
    schema_version: Literal["1.0.0"]
    node_id: str
    boot_id: UUID
    observed_at: datetime
    state: Literal["online", "degraded", "offline"]
    firmware_version: str
    hardware_revision: str
    calibration_revision: str | None
    clock_source: ClockSource
    acquisition_state: Literal["sampling", "degraded", "stopped"]
    pending_records: int
    oldest_pending_age_s: int
    last_valid_window_end: datetime | None
    last_error_code: str | None


class NodeEvent(_Contract):
    schema_version: Literal["1.0.0"]
    event_id: UUID
    node_id: str
    circuit_id: str
    boot_id: UUID
    sequence: int
    observed_at: datetime
    event_type: Literal["threshold_entered", "threshold_cleared", "measurement_quality_changed"]
    severity: Literal["info", "warning", "critical"]
    config_version: int
    measured_value: float | None
    threshold_value: float | None
    unit: Literal["W", "none"]
    quality: QualityState
    local_warning_active: bool
    reason_code: str | None = None


class ThresholdConfig(_Contract):
    schema_version: Literal["1.0.0"]
    config_version: int
    node_id: str
    circuit_id: str
    effective_at: datetime
    active_power_limit_w: float = Field(alias="active_power_limit_W")
    confirm_ms: int = 10000
    clear_below_w: float = Field(alias="clear_below_W")
    clear_ms: int
    severity: Literal["warning", "critical"]
    local_warning_enabled: bool


class MeasurementAck(_Contract):
    schema_version: Literal["1.0.0"]
    acknowledged_at: datetime
    message_id: UUID
    node_id: str
    boot_id: UUID
    sequence: int
    status: Literal["accepted", "duplicate", "rejected"]
    reason_code: str | None
    stored_at: datetime | None = None


MODELS: dict[str, type[_Contract]] = {
    "measurement": Measurement,
    "node-status": NodeStatus,
    "node-event": NodeEvent,
    "threshold-config": ThresholdConfig,
    "measurement-ack": MeasurementAck,
}


def parse[M: _Contract](model: type[M], name: str, raw: bytes) -> M:
    """Validate `raw` against schema `name`, then build the typed model."""
    if MODELS[name] is not model:
        raise TypeError(f"{model.__name__} does not mirror schema {name}")
    return model.model_validate(validate_payload(name, raw))
