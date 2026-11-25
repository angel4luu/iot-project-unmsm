"""Idempotent InfluxDB writes of measurement windows (T022).

One point per window, timestamped at `window.end` (the canonical observation
time) with millisecond precision. Tags are only `node_id`, `circuit_id`,
`quality`, and `calibration_revision`; UUIDs stay fields. Writing the same window
twice replaces the same point, so a retried write is harmless.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol

from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS

from energy_ingestion.contracts.models import Measurement

MEASUREMENT = "energy_window"
RAW_BUCKET = "energy_raw"
OPERATIONS_BUCKET = "operations"
TAG_KEYS = frozenset({"node_id", "circuit_id", "quality", "calibration_revision"})
NO_CALIBRATION = "none"


def measurement_point(m: Measurement) -> Point:
    q = m.measurements
    point = (
        Point(MEASUREMENT)
        .tag("node_id", m.node_id)
        .tag("circuit_id", m.circuit_id)
        .tag("quality", m.quality.state)
        .tag("calibration_revision", m.quality.calibration_revision or NO_CALIBRATION)
        .time(m.window.end, WritePrecision.MS)
        .field("message_id", str(m.message_id))
        .field("boot_id", str(m.boot_id))
        .field("sequence", m.sequence)
        .field("duration_ms", m.window.duration_ms)
        .field("sample_count", m.window.sample_count)
        .field("valid_sample_ratio", float(m.quality.valid_sample_ratio))
        .field("quality_flags", ",".join(sorted(m.quality.flags)))
        .field("clock_source", m.clock.source)
        .field("uptime_ms", m.uptime_ms)
        .field("counter_id", str(q.active_energy_import_total.counter_id))
    )
    if m.clock.last_sync_age_s is not None:
        point.field("last_sync_age_s", m.clock.last_sync_age_s)
    values = {
        "voltage_rms_V": q.voltage_rms.value,
        "current_rms_A": q.current_rms.value,
        "active_power_W": q.active_power.value,
        "active_energy_import_total_Wh": q.active_energy_import_total.value,
    }
    for name, value in values.items():
        if value is not None:  # invalid windows carry nulls; never copy old values
            point.field(name, float(value))
    return point


class PointWriter(Protocol):
    def write(self, bucket: str, point: Point) -> None: ...


class InfluxWriter:
    """Synchronous writer: returns only after InfluxDB confirmed the write."""

    def __init__(self, url: str, org: str, token: str) -> None:
        self._client = InfluxDBClient(url=url, token=token, org=org)
        self._api = self._client.write_api(write_options=SYNCHRONOUS)
        self._org = org

    @classmethod
    def from_env(cls) -> InfluxWriter:
        token = Path(os.environ["INFLUX_TOKEN_FILE"]).read_text(encoding="utf-8").strip()
        return cls(os.environ["INFLUX_URL"], os.environ["INFLUX_ORG"], token)

    def write(self, bucket: str, point: Point) -> None:
        self._api.write(bucket=bucket, org=self._org, record=point)

    def write_measurement(self, m: Measurement) -> None:
        self.write(RAW_BUCKET, measurement_point(m))

    def close(self) -> None:
        self._client.close()
