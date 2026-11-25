"""Daily Parquet export (T073): content, order, labels, exclusions, manifest, versions.

InfluxDB is replaced by a fake Flux runner that returns annotated CSV in the shape
`influx query --raw` prints. The reproduction test against the stack is T106.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import pyarrow.parquet as pq
import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load():
    path = ROOT / "experiments" / "export" / "export_daily.py"
    spec = importlib.util.spec_from_file_location("export_daily", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["export_daily"] = module
    spec.loader.exec_module(module)
    return module


ex = _load()
DAY = date(2026, 11, 24)
FIELDS = [
    "_time", "active_energy_import_total_Wh", "active_power_W", "boot_id", "calibration_revision",
    "circuit_id", "clock_source", "counter_id", "current_rms_A", "duration_ms",
    "last_sync_age_s", "message_id", "node_id", "quality", "quality_flags", "receive_lag_ms",
    "sample_count", "sequence", "uptime_ms", "valid_sample_ratio", "validation", "voltage_rms_V",
]  # fmt: skip


def row(t: str, seq: int, quality: str = "valid", boot: str = "b1", power: str = "20.4") -> dict:
    invalid = quality == "invalid"
    return {
        "_time": t,
        "active_energy_import_total_Wh": "" if invalid else f"{seq * 0.028:.4f}",
        "active_power_W": "" if invalid else power,
        "boot_id": boot,
        "calibration_revision": "node-001-nominal-r1",
        "circuit_id": "lab-load-001",
        "clock_source": "sntp",
        "counter_id": "c1",
        "current_rms_A": "" if invalid else "1.619",
        "duration_ms": "5000",
        "last_sync_age_s": "30",
        "message_id": f"m-{boot}-{seq}",
        "node_id": "node-001",
        "quality": quality,
        "quality_flags": "sample_gap" if invalid else "",
        "receive_lag_ms": "120",
        "sample_count": "0" if invalid else "20000",
        "sequence": str(seq),
        "uptime_ms": str(5000 * (seq + 1)),
        "valid_sample_ratio": "0" if invalid else "1",
        "validation": "not_validated",
        "voltage_rms_V": "" if invalid else "12.6",
    }


def annotated(rows: list[dict], columns: list[str]) -> str:
    lines = [
        "#group," + ",".join(["false"] * (len(columns) + 2)),
        "#datatype," + ",".join(["string", "long", *["string"] * len(columns)]),
        "#default,_result," + "," * len(columns),
        ",result,table," + ",".join(columns),
    ]
    for r in rows:
        lines.append(",,0," + ",".join(r.get(c, "") for c in columns))
    return "\r\n".join(lines) + "\r\n\r\n"


ROWS = [
    row("2026-11-24T10:00:05Z", 0),
    row("2026-11-24T10:00:10Z", 1, "invalid"),
    row("2026-11-24T10:00:15Z", 2, "degraded"),
    row("2026-11-24T12:00:00Z", 0, boot="b2"),
]


class FakeRunner:
    def __init__(self, rows: list[dict] = ROWS, firmware: tuple[str, ...] = ("0.1.0",)) -> None:
        self.rows, self.firmware, self.queries = rows, firmware, []

    def __call__(self, query: str) -> str:
        self.queries.append(query)
        if '"operations"' in query:
            return annotated([{"_value": f} for f in self.firmware], ["_value"])
        return annotated(self.rows, FIELDS)


def test_queries_cover_the_utc_day_and_sort_by_observation_time():
    start, stop = ex.day_interval(DAY)
    q = ex.measurement_query("node-001", start, stop)
    assert "range(start: 2026-11-24T00:00:00Z, stop: 2026-11-25T00:00:00Z)" in q
    assert 'sort(columns: ["_time", "boot_id", "sequence"])' in q
    assert 'r.node_id == "node-001"' in q


def test_parse_annotated_csv_handles_several_tables():
    text = annotated([{"_value": "a"}], ["_value"]) + annotated([{"_value": "b"}], ["_value"])
    assert [r["_value"] for r in ex.parse_annotated_csv(text)] == ["a", "b"]


def test_snapshot_keeps_every_window_with_types_and_nulls(tmp_path):
    vdir = ex.export_day("node-001", DAY, tmp_path, FakeRunner())
    t = pq.read_table(vdir / "measurements.parquet")
    assert t.schema == ex.SCHEMA
    assert t.column("quality").to_pylist() == ["valid", "invalid", "degraded", "valid"]
    assert t.column("active_power_W").to_pylist()[1] is None  # invalid: null, never a copy
    assert t.column("sequence").to_pylist() == [0, 1, 2, 0]
    assert t.column("window_end").to_pylist()[0] == datetime(2026, 11, 24, 10, 0, 5, tzinfo=UTC)
    assert t.column("load_label").to_pylist() == [None] * 4


def test_labels_and_exclusions(tmp_path):
    labels = tmp_path / "loads.csv"
    labels.write_text(
        "start_utc,end_utc,load_label\n"
        "2026-11-24T10:00:00Z,2026-11-24T10:00:10Z,bulb-12v-20w on\n"
        "2026-11-24T11:00:00Z,2026-11-24T13:00:00Z,bulb off\n"
    )
    vdir = ex.export_day(
        "node-001", DAY, tmp_path / "out", FakeRunner(), labels, frozenset({"invalid"})
    )
    t = pq.read_table(vdir / "measurements.parquet")
    # 10:00:10 is the end of the first interval (half-open) and is excluded anyway
    assert t.column("load_label").to_pylist() == ["bulb-12v-20w on", None, "bulb off"]
    m = json.loads((vdir / "manifest.json").read_text())
    assert m["quality"]["excluded_states"] == ["invalid"]
    assert m["quality"]["excluded_counts"] == {"invalid": 1}
    assert m["quality"]["included_counts"] == {"valid": 2, "degraded": 1, "invalid": 0}
    assert [x["label"] for x in m["load_labels"]] == ["bulb-12v-20w on", "bulb off"]
    assert {f.get("role") for f in m["files"]} == {None, "labels"}


def test_manifest_records_what_reproduction_needs(tmp_path):
    runner = FakeRunner(firmware=("0.1.0", "0.1.1"))
    vdir = ex.export_day("node-001", DAY, tmp_path, runner)
    m = json.loads((vdir / "manifest.json").read_text())
    assert m["interval_utc"] == {
        "start": "2026-11-24T00:00:00Z",
        "stop": "2026-11-25T00:00:00Z",
        "closed": "start",
    }
    assert m["queries"]["measurements"] == runner.queries[0]  # the exact query text
    assert m["measurement_schema_version"] == "1.0.0"
    assert m["calibration_revisions"] == ["node-001-nominal-r1"]
    assert m["firmware_versions"] == ["0.1.0", "0.1.1"]
    (data,) = [f for f in m["files"] if f["path"] == "measurements.parquet"]
    assert data["rows"] == 4
    assert data["sha256"] == hashlib.sha256((vdir / data["path"]).read_bytes()).hexdigest()
    assert len(m["code"]["commit"]) == 40
    assert isinstance(m["code"]["dirty"], bool)
    assert len(m["environment"]["uv_lock_sha256"]) == 64
    assert "not validated" in m["quality"]["note"]


def test_reruns_create_new_versions_with_identical_data(tmp_path):
    v1 = ex.export_day("node-001", DAY, tmp_path, FakeRunner())
    v2 = ex.export_day("node-001", DAY, tmp_path, FakeRunner())
    assert (v1.name, v2.name) == ("v1", "v2")
    a = (v1 / "measurements.parquet").read_bytes()
    assert a == (v2 / "measurements.parquet").read_bytes()  # deterministic bytes


def test_empty_day_still_writes_a_manifest(tmp_path):
    vdir = ex.export_day("node-001", DAY, tmp_path, FakeRunner(rows=[]))
    assert pq.read_table(vdir / "measurements.parquet").num_rows == 0
    assert json.loads((vdir / "manifest.json").read_text())["files"][0]["rows"] == 0


@pytest.mark.parametrize("node", ["Node-001", 'x") |> drop(', "a"])
def test_node_id_is_validated_before_it_reaches_a_query(tmp_path, node):
    with pytest.raises(ValueError, match="invalid node id"):
        ex.export_day(node, DAY, tmp_path, FakeRunner())


def test_unknown_quality_state_is_refused(tmp_path):
    with pytest.raises(ValueError, match="unknown quality"):
        ex.export_day("node-001", DAY, tmp_path, FakeRunner(), exclude=frozenset({"bogus"}))
