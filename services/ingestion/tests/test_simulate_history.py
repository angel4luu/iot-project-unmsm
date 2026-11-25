"""Offline acceptance checks for the reproducible seven-day history dataset."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from energy_ingestion.cli.simulate import SimulatedNode

START = datetime(2026, 11, 16, 5, tzinfo=UTC)
DURATION = timedelta(days=7)
WINDOWS = 120_960
LIMA = ZoneInfo("America/Lima")


def summarize(seed: int = 740_251) -> tuple[dict[datetime, float], list[dict[str, object]], str]:
    node = SimulatedNode("history", START, node_id="sim-history", seed=seed)
    readings: list[dict[str, object]] = []
    hourly: dict[datetime, float] = defaultdict(float)
    last: dict[str, float] = {}
    digest = hashlib.sha256()
    for message in node.messages(DURATION):
        if message.kind != "measurement":
            continue
        payload = json.loads(message.payload)
        readings.append(payload)
        digest.update(message.payload + b"\n")
        total = payload["measurements"]["active_energy_import_total"]["value"]
        if total is None:
            continue
        counter_id = payload["measurements"]["active_energy_import_total"]["counter_id"]
        if counter_id in last:
            delta = total - last[counter_id]
            if delta >= 0:
                end = datetime.fromisoformat(payload["window"]["end"].replace("Z", "+00:00"))
                bucket = (
                    (end - timedelta(milliseconds=1))
                    .astimezone(LIMA)
                    .replace(minute=0, second=0, microsecond=0)
                )
                hourly[bucket] += delta
        last[counter_id] = total
    return hourly, readings, digest.hexdigest()


def test_history_dataset_has_reproducible_unique_peak_and_reset() -> None:
    hourly, readings, digest = summarize()
    ordered = sorted(hourly.items(), key=lambda item: (-item[1], item[0]))
    peak_time, peak_wh = ordered[0]
    runner_up = ordered[1][1]
    assert len(readings) == WINDOWS
    assert peak_time == datetime(2026, 11, 19, 18, tzinfo=LIMA)
    assert peak_wh >= runner_up * 1.10
    assert peak_wh == pytest.approx(23.8622, abs=1e-12)  # stable fixed-seed answer
    peak_windows = [
        p
        for p in readings
        if (t := datetime.fromisoformat(p["window"]["start"].replace("Z", "+00:00")))
        and t.astimezone(LIMA).date().isoformat() == "2026-11-19"
        and t.astimezone(LIMA).hour == 18
        and p["quality"]["state"] == "valid"
    ]
    assert peak_windows
    assert all(
        10 <= p["measurements"]["voltage_rms"]["value"] <= 16
        and 0.5 <= p["measurements"]["current_rms"]["value"] <= 2.0
        and 22.0 <= p["measurements"]["active_power"]["value"] <= 26.0
        for p in peak_windows
    )
    off_window = next(
        p
        for p in readings
        if p["quality"]["state"] == "valid" and p["measurements"]["active_power"]["value"] == 0.0
    )
    assert off_window["measurements"]["current_rms"]["value"] == 0.0
    midpoint = WINDOWS // 2
    assert readings[midpoint - 1]["boot_id"] != readings[midpoint]["boot_id"]
    assert readings[midpoint]["sequence"] == 0
    assert readings[midpoint]["measurements"]["active_energy_import_total"]["value"] == 0.0
    counter_ids = {r["measurements"]["active_energy_import_total"]["counter_id"] for r in readings}
    assert len(counter_ids) == 2
    assert readings[0]["measurements"]["active_energy_import_total"]["value"] == 0.0
    counters = {counter: [] for counter in counter_ids}
    for payload in readings:
        counters[payload["measurements"]["active_energy_import_total"]["counter_id"]].append(
            payload
        )
    assert any(
        p["measurements"]["active_energy_import_total"]["value"] == 0.0
        for p in counters[next(iter(counter_ids))][:1]
    ) or any(
        p["measurements"]["active_energy_import_total"]["value"] == 0.0
        for group in counters.values()
        for p in group[:1]
    )
    invalid = sum(p["quality"]["state"] == "invalid" for p in readings)
    assert 0.0049 <= invalid / WINDOWS <= 0.0051
    assert all(
        p["measurements"]["active_power"]["value"] is None
        and p["quality"]["flags"] in (["sensor_disconnected"], ["sample_gap"])
        for p in readings
        if p["quality"]["state"] == "invalid"
    )
    assert all(
        datetime.fromisoformat(p["window"]["end"].replace("Z", "+00:00")) < datetime.now(UTC)
        for p in readings
    )
    assert digest == summarize()[2]
