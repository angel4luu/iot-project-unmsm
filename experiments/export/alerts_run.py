"""Export of one alert run (experiment E2) for experiments/evaluation/alerts.py (T108).

Collects, for one node and one UTC interval:

- from SQLite (inside the ingestion container, read only): every alert opened in the
  interval with its transitions and notification outbox rows, and the threshold
  configuration in force at the end of the interval;
- from the InfluxDB `operations` bucket (read-only Grafana token, as export_daily.py
  does): the node's event time (`event_observed_at`) of each alert's `open`
  transition, for the event-to-alert latency.

Neither container is published on the host, so both queries run through
`docker exec`; no token or secret is printed or written. Usage (repository root):

    uv run --project services/ingestion python experiments/export/alerts_run.py \
        --node node-001 --since 2026-11-30T15:00:00Z --until 2026-11-30T15:30:00Z \
        --out experiments/data/e2/export-2026-11-30-a.json
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from export_daily import NODE_RE, docker_runner, parse_annotated_csv

INGESTION_CONTAINER = "unmsm-energy-ingestion-1"

# Runs inside the ingestion container (its own package and SQLITE_PATH); prints JSON.
SQLITE_SCRIPT = r"""
import json, sys
from sqlalchemy import select
from sqlalchemy.orm import Session
from energy_ingestion.contracts.models import wire_time
from energy_ingestion.persistence.db import (
    Alert, AlertTransition, NotificationOutbox, ThresholdConfiguration, make_engine,
)
node, since, until = sys.argv[1], *(
    __import__("datetime").datetime.fromisoformat(a.replace("Z", "+00:00")) for a in sys.argv[2:4]
)
t = lambda v: wire_time(v) if v is not None else None
f = lambda v: float(v) if v is not None else None
with Session(make_engine()) as s:
    alerts = s.scalars(
        select(Alert).where(Alert.node_id == node, Alert.opened_at >= since,
                            Alert.opened_at <= until).order_by(Alert.opened_at)
    ).all()
    out = []
    for a in alerts:
        trs = s.scalars(select(AlertTransition).where(AlertTransition.alert_id == a.alert_id)
                        .order_by(AlertTransition.transition_id)).all()
        box = s.scalars(select(NotificationOutbox)
                        .where(NotificationOutbox.alert_id == a.alert_id)).all()
        out.append({
            "alert_id": a.alert_id, "event_id": a.event_id, "kind": a.kind,
            "severity": a.severity, "status": a.status, "quality": a.quality,
            "opened_at": t(a.opened_at), "acknowledged_at": t(a.acknowledged_at),
            "resolved_at": t(a.resolved_at), "observed_value": f(a.observed_value),
            "threshold_value": f(a.threshold_value),
            "transitions": [{"from": r.from_status, "to": r.to_status, "actor": r.actor,
                             "reason": r.reason, "at": t(r.at)} for r in trs],
            "notifications": [{"destination_type": n.destination_type, "state": n.state,
                               "attempt_count": n.attempt_count,
                               "last_error_code": n.last_error_code,
                               "delivered_at": t(n.delivered_at)} for n in box],
        })
    cfg = s.scalars(
        select(ThresholdConfiguration).where(ThresholdConfiguration.node_id == node,
                                             ThresholdConfiguration.effective_at <= until)
        .order_by(ThresholdConfiguration.config_version.desc())
    ).first()
    config = None if cfg is None else {
        "config_version": cfg.config_version, "limit_W": f(cfg.active_power_limit_w),
        "clear_below_W": f(cfg.clear_below_w), "confirm_ms": cfg.confirm_ms,
        "clear_ms": cfg.clear_ms, "severity": cfg.severity,
        "local_warning_enabled": cfg.local_warning_enabled,
        "effective_at": t(cfg.effective_at), "created_by": cfg.created_by,
    }
json.dump({"alerts": out, "config": config}, sys.stdout)
"""

SqliteRunner = Callable[[str, datetime, datetime], dict[str, Any]]
FluxRunner = Callable[[str], str]


def wire(t: datetime) -> str:
    return t.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _utc(text: str) -> datetime:
    t = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if t.tzinfo is None:
        raise ValueError(f"timestamp without timezone: {text!r}")
    return t.astimezone(UTC)


def docker_sqlite(container: str = INGESTION_CONTAINER) -> SqliteRunner:
    def run(node: str, since: datetime, until: datetime) -> dict[str, Any]:
        r = subprocess.run(  # noqa: S603 - fixed command; the script goes to stdin
            ["docker", "exec", "-i", container, "python", "-", node, wire(since), wire(until)],  # noqa: S607
            input=SQLITE_SCRIPT,
            capture_output=True,
            text=True,
            check=False,
        )
        if r.returncode != 0:
            raise RuntimeError(f"sqlite export failed: {r.stderr.strip()[-300:]}")
        doc: dict[str, Any] = json.loads(r.stdout)
        return doc

    return run


def flux_open_events(node: str, since: datetime, until: datetime) -> str:
    # Points are timed at the server transition; a small margin keeps late opens.
    return (
        'from(bucket: "operations")\n'
        f"    |> range(start: {wire(since)}, stop: {wire(until)})\n"
        '    |> filter(fn: (r) => r._measurement == "alert_transition"'
        f' and r.node_id == "{node}" and r.to_status == "open")\n'
        '    |> filter(fn: (r) => r._field == "alert_id" or r._field == "event_observed_at")\n'
        "    |> group()\n"
        '    |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")\n'
    )


def merge(sqlite: dict[str, Any], flux_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Alerts with the node event time and the first webhook delivery time added."""
    observed = {
        r["alert_id"]: r["event_observed_at"]
        for r in flux_rows
        if r.get("alert_id") and r.get("event_observed_at")
    }
    out = []
    for a in sqlite["alerts"]:
        delivered = sorted(
            n["delivered_at"]
            for n in a["notifications"]
            if n["state"] == "delivered" and n["delivered_at"]
        )
        out.append(
            {
                **a,
                "event_observed_at": observed.get(a["alert_id"]),
                "delivered_at": delivered[0] if delivered else None,
            }
        )
    return out


def export(
    node: str,
    since: datetime,
    until: datetime,
    sqlite: SqliteRunner,
    flux: FluxRunner,
) -> dict[str, Any]:
    db = sqlite(node, since, until)
    if db["config"] is None:
        raise SystemExit(f"no threshold configuration for {node} before {wire(until)}")
    query = flux_open_events(node, since, until)
    alerts = merge(db, parse_annotated_csv(flux(query)))
    return {
        "experiment": "E2",
        "node_id": node,
        "utc_interval": {"since": wire(since), "until": wire(until)},
        "validation": "not_validated",
        "config": db["config"],
        "alerts": alerts,
        "flux_query": query,
        "created_at": wire(datetime.now(UTC)),
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    p.add_argument("--node", required=True)
    p.add_argument("--since", type=_utc, required=True)
    p.add_argument("--until", type=_utc, required=True)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args(argv)
    if not NODE_RE.match(args.node):
        p.error("bad node id")
    if not args.since < args.until:
        p.error("--since must be before --until")
    if args.out.exists():
        p.error(f"{args.out} exists; evidence is never overwritten")
    doc = export(args.node, args.since, args.until, docker_sqlite(), docker_runner())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    kinds = [a["kind"] for a in doc["alerts"]]
    print(f"{args.out}: {len(kinds)} alerts ({kinds.count('active_power_threshold')} threshold)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
