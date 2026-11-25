"""Daily Parquet export of accepted measurements with a manifest (T073).

Plan > Future Dataset and Evaluation Design: before the raw 30-day expiry, an
export creates an immutable daily Parquet snapshot of accepted measurements and a
manifest with the exact query, UTC interval, schema/calibration/firmware
revisions, quality exclusions, controlled-load labels, file hashes, code commit,
and environment-lock hash. Reruns create a new version (`v2`, `v3`, ...) and never
overwrite an earlier one.

The snapshot keeps every stored window of the UTC day, including `degraded` and
`invalid` ones (their quality travels with each row), unless `--exclude-quality`
names states to leave out; the manifest records the rule and the counts. Values
are not validated (nominal calibration, no reference meter).

InfluxDB is not published on the host, so queries run through `influx query`
inside the InfluxDB container with the read-only Grafana token, as the
integration tests do. Usage (from the repository root):

    uv run --project services/ingestion python experiments/export/export_daily.py \
        --node node-001 --date 2026-11-24 [--labels loads.csv] [--out experiments/data/export]

`--labels` is a CSV with `start_utc,end_utc,load_label` rows (controlled-load
sessions, half-open intervals); windows outside every interval get no label.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import platform
import re
import subprocess
import sys
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

REPO = Path(__file__).resolve().parents[2]
CONTRACTS = REPO / "specs" / "001-energy-monitoring-system" / "contracts"
INFLUX_CONTAINER = "unmsm-energy-influxdb-1"
INFLUX_ORG = "unmsm-energy"
TOKEN_FILE = REPO / "infrastructure" / "secrets" / "influx-grafana-token"
NODE_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")
QUALITY_STATES = ("valid", "degraded", "invalid")

# Snapshot columns, in order: (column, Arrow type, Influx column)
COLUMNS: tuple[tuple[str, pa.DataType, str], ...] = (
    ("window_end", pa.timestamp("ms", tz="UTC"), "_time"),
    ("node_id", pa.string(), "node_id"),
    ("circuit_id", pa.string(), "circuit_id"),
    ("boot_id", pa.string(), "boot_id"),
    ("sequence", pa.int64(), "sequence"),
    ("message_id", pa.string(), "message_id"),
    ("quality", pa.string(), "quality"),
    ("quality_flags", pa.string(), "quality_flags"),
    ("valid_sample_ratio", pa.float64(), "valid_sample_ratio"),
    ("calibration_revision", pa.string(), "calibration_revision"),
    ("validation", pa.string(), "validation"),
    ("clock_source", pa.string(), "clock_source"),
    ("last_sync_age_s", pa.int64(), "last_sync_age_s"),
    ("duration_ms", pa.int64(), "duration_ms"),
    ("sample_count", pa.int64(), "sample_count"),
    ("uptime_ms", pa.int64(), "uptime_ms"),
    ("voltage_rms_V", pa.float64(), "voltage_rms_V"),
    ("current_rms_A", pa.float64(), "current_rms_A"),
    ("active_power_W", pa.float64(), "active_power_W"),
    ("active_energy_import_total_Wh", pa.float64(), "active_energy_import_total_Wh"),
    ("counter_id", pa.string(), "counter_id"),
    ("receive_lag_ms", pa.float64(), "receive_lag_ms"),
    ("load_label", pa.string(), ""),
)
SCHEMA = pa.schema([(name, typ) for name, typ, _ in COLUMNS])

FluxRunner = Callable[[str], str]


# ---- queries -------------------------------------------------------------------------


def day_interval(day: date) -> tuple[datetime, datetime]:
    start = datetime(day.year, day.month, day.day, tzinfo=UTC)
    return start, start + timedelta(days=1)


def _rfc3339(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def measurement_query(node: str, start: datetime, stop: datetime) -> str:
    return (
        'from(bucket: "energy_raw")\n'
        f"    |> range(start: {_rfc3339(start)}, stop: {_rfc3339(stop)})\n"
        '    |> filter(fn: (r) => r._measurement == "electrical_measurement"'
        f' and r.node_id == "{node}")\n'
        '    |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")\n'
        "    |> group()\n"
        '    |> sort(columns: ["_time", "boot_id", "sequence"])\n'
    )


def firmware_query(node: str, start: datetime, stop: datetime) -> str:
    return (
        'from(bucket: "operations")\n'
        f"    |> range(start: {_rfc3339(start)}, stop: {_rfc3339(stop)})\n"
        '    |> filter(fn: (r) => r._measurement == "node_status"'
        f' and r.node_id == "{node}" and r._field == "firmware_version")\n'
        "    |> group()\n"
        '    |> distinct(column: "_value")\n'
    )


def docker_runner(container: str = INFLUX_CONTAINER, token_file: Path = TOKEN_FILE) -> FluxRunner:
    def run(query: str) -> str:
        token = token_file.read_text(encoding="utf-8").strip()
        r = subprocess.run(  # noqa: S603 - fixed command; the query goes to stdin
            [  # noqa: S607 - docker from PATH, as the Makefile uses it
                "docker",
                "exec",
                "-i",
                "-e",
                "INFLUX_TOKEN",
                container,
                "influx",
                "query",
                "--org",
                INFLUX_ORG,
                "--raw",
                "-",
            ],
            input=query,
            capture_output=True,
            text=True,
            check=False,
            env={**os.environ, "INFLUX_TOKEN": token},
        )
        if r.returncode != 0:
            raise RuntimeError(f"flux query failed: {r.stderr.strip()[:300]}")
        return r.stdout

    return run


def parse_annotated_csv(text: str) -> list[dict[str, str]]:
    """Every data row of every table in InfluxDB annotated CSV, as a dict."""
    rows: list[dict[str, str]] = []
    header: list[str] | None = None
    for record in csv.reader(io.StringIO(text)):
        if not record or not any(record):
            header = None
            continue
        if record[0].startswith("#"):
            header = None
            continue
        if header is None:
            header = record
            continue
        rows.append(dict(zip(header, record, strict=False)))
    return rows


# ---- labels and table ------------------------------------------------------------------


@dataclass(frozen=True)
class LoadLabel:
    start: datetime
    end: datetime
    label: str


def _utc(text: str) -> datetime:
    t = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if t.tzinfo is None:
        raise ValueError(f"timestamp without timezone: {text!r}")
    return t.astimezone(UTC)


def load_labels(path: Path | None) -> list[LoadLabel]:
    if path is None:
        return []
    with path.open(newline="", encoding="utf-8") as f:
        out = [
            LoadLabel(_utc(r["start_utc"]), _utc(r["end_utc"]), r["load_label"].strip())
            for r in csv.DictReader(f)
        ]
    for lab in out:
        if not lab.start < lab.end or not lab.label:
            raise ValueError(f"bad label interval: {lab}")
    return out


def _label_for(t: datetime, labels: Sequence[LoadLabel]) -> str | None:
    for lab in labels:
        if lab.start <= t < lab.end:
            return lab.label
    return None


def _convert(text: str | None, typ: pa.DataType) -> Any:
    if text is None or text == "":
        return None
    if pa.types.is_timestamp(typ):
        return _utc(text)
    if pa.types.is_integer(typ):
        return int(float(text))
    if pa.types.is_floating(typ):
        return float(text)
    return text


def build_table(
    rows: Sequence[dict[str, str]], labels: Sequence[LoadLabel], exclude: frozenset[str]
) -> tuple[pa.Table, Counter[str]]:
    """Rows in observation order; returns the table and the excluded counts by quality."""
    excluded: Counter[str] = Counter()
    columns: dict[str, list[Any]] = {name: [] for name, _, _ in COLUMNS}
    for row in rows:
        quality = row.get("quality", "")
        if quality in exclude:
            excluded[quality] += 1
            continue
        end = _utc(row["_time"])
        for name, typ, source in COLUMNS:
            value = (
                _label_for(end, labels) if name == "load_label" else _convert(row.get(source), typ)
            )
            columns[name].append(value)
    table = pa.Table.from_pydict(columns, schema=SCHEMA)
    return table, excluded


# ---- output and manifest ---------------------------------------------------------------


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(*args: str) -> str | None:
    cmd = ["git", "-C", str(REPO), *args]
    r = subprocess.run(cmd, capture_output=True, text=True, check=False)  # noqa: S603
    return r.stdout.strip() if r.returncode == 0 else None


def next_version_dir(base: Path) -> Path:
    """`v1`, `v2`, ...: a rerun never overwrites an earlier snapshot."""
    n = 1
    while (base / f"v{n}").exists():
        n += 1
    path = base / f"v{n}"
    path.mkdir(parents=True)
    return path


def schema_version() -> str:
    doc = json.loads((CONTRACTS / "measurement.schema.json").read_text(encoding="utf-8"))
    return str(doc["properties"]["schema_version"].get("const", doc.get("$id", "unknown")))


def export_day(
    node: str,
    day: date,
    out: Path,
    runner: FluxRunner,
    labels_path: Path | None = None,
    exclude: frozenset[str] = frozenset(),
) -> Path:
    """Writes `<out>/<node>/<day>/vN/{measurements.parquet,manifest.json}`; returns vN."""
    if not NODE_RE.fullmatch(node):
        raise ValueError(f"invalid node id {node!r}")
    if not exclude <= set(QUALITY_STATES):
        raise ValueError(f"unknown quality state in {sorted(exclude)}")
    start, stop = day_interval(day)
    m_query, f_query = measurement_query(node, start, stop), firmware_query(node, start, stop)
    rows = parse_annotated_csv(runner(m_query))
    firmware = sorted(
        {r["_value"] for r in parse_annotated_csv(runner(f_query)) if r.get("_value")}
    )
    labels = load_labels(labels_path)
    table, excluded = build_table(rows, labels, exclude)

    vdir = next_version_dir(out / node / day.isoformat())
    data_path = vdir / "measurements.parquet"
    pq.write_table(table, data_path, compression="zstd", write_statistics=True)

    qualities = Counter(table.column("quality").to_pylist())
    files = [{"path": data_path.name, "rows": table.num_rows, "sha256": _sha256(data_path)}]
    if labels_path is not None:
        files.append({"path": str(labels_path), "role": "labels", "sha256": _sha256(labels_path)})
    status = _git("status", "--porcelain")
    manifest = {
        "kind": "raw_daily_snapshot",
        "node_id": node,
        "interval_utc": {"start": _rfc3339(start), "stop": _rfc3339(stop), "closed": "start"},
        "queries": {"measurements": m_query, "firmware_versions": f_query},
        "measurement_schema_version": schema_version(),
        "calibration_revisions": sorted(
            {r for r in table.column("calibration_revision").to_pylist() if r}
        ),
        "firmware_versions": firmware,
        "quality": {
            "excluded_states": sorted(exclude),
            "excluded_counts": dict(sorted(excluded.items())),
            "included_counts": {q: qualities.get(q, 0) for q in QUALITY_STATES},
            "note": "values are not validated (nominal calibration, no reference meter)",
        },
        "load_labels": [
            {"start_utc": _rfc3339(x.start), "end_utc": _rfc3339(x.end), "label": x.label}
            for x in labels
        ],
        "files": files,
        "code": {"commit": _git("rev-parse", "HEAD"), "dirty": bool(status)},
        "environment": {
            "uv_lock_sha256": _sha256(REPO / "services" / "ingestion" / "uv.lock"),
            "python": platform.python_version(),
            "pyarrow": pa.__version__,
        },
        "created_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "arguments": {
            "node": node,
            "date": day.isoformat(),
            "labels": str(labels_path) if labels_path else None,
            "exclude_quality": sorted(exclude),
        },
    }
    (vdir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return vdir


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    ap.add_argument("--node", required=True)
    ap.add_argument("--date", required=True, type=date.fromisoformat, help="UTC day, YYYY-MM-DD")
    ap.add_argument("--labels", type=Path)
    ap.add_argument("--exclude-quality", action="append", default=[], choices=QUALITY_STATES)
    ap.add_argument("--out", type=Path, default=REPO / "experiments" / "data" / "export")
    a = ap.parse_args(argv)
    vdir = export_day(
        a.node, a.date, a.out, docker_runner(), a.labels, frozenset(a.exclude_quality)
    )
    print(vdir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
