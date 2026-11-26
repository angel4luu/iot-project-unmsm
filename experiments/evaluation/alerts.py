"""Alert run evaluation for experiment E2 (T087 support, T108; SC-004, FR-011-FR-013).

The operator switches the 12 V bulb on and off in timed episodes and writes them in
an episode log; the server's alerts for that interval come from
`experiments/export/alerts_run.py`. This script checks one against the other:

- enough_episodes: >= 5 bulb-on and >= 5 bulb-off episodes with the server up, and
  >= 1 bulb-on episode with the ingestion service stopped;
- on_alerts_once: every bulb-on episode has exactly one threshold alert whose node
  event lies in [start + confirm_ms, end] (+- the clock tolerance);
- no_early_alert: no threshold alert before start + confirm_ms in a bulb-on episode,
  so the cold-filament inrush did not alert;
- off_quiet: no threshold alert in a bulb-off episode;
- alerts_cleared: every bulb-on alert was resolved by the node;
- local_warning: the operator saw the red LED and buzzer in every bulb-on episode
  (also with the server stopped) and in no bulb-off episode;
- remote_within_10s: with the server up, node event to alert opened plus the 5 s
  dashboard refresh is <= 10 s, and so is node event to webhook delivery when one was
  delivered;
- no_health_alerts: no `pipeline_health` alert during the run.

The local warning time itself is not measured here: the firmware turns it on in the
block that confirms and the display refreshes every 0.5 s (simulated evidence, T080);
on the bench it is observed, not timed. Values are not validated.

Episode log CSV: `episode,kind,server,start_utc,end_utc,local_warning_seen,notes`
with kind `on`/`off`, server `up`/`down`, ISO 8601 UTC times, and `yes`/`no`.

Standard library only:
    python experiments/evaluation/alerts.py --episodes E.csv --export X.json \
        --run-id 2026-11-30-a --out experiments/data/e2 \
        --manifest experiments/manifests/alerts-20261130.json
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
import statistics
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

CLOCK_TOLERANCE = timedelta(seconds=5)  # operator's phone clock vs node clock
DASHBOARD_REFRESH_S = 5.0
REMOTE_BOUND_S = 10.0
MIN_ON, MIN_OFF, MIN_DOWN = 5, 5, 1
EPISODE_FIELDS = (
    "episode", "kind", "server", "start_utc", "end_utc", "local_warning_seen", "notes",
)  # fmt: skip

CHECKS = (
    ("enough_episodes", f">= {MIN_ON} on, >= {MIN_OFF} off (server up), >= {MIN_DOWN} on, down"),
    ("on_alerts_once", "exactly one threshold alert per bulb-on episode, after confirm_ms"),
    ("no_early_alert", "no alert before start + confirm_ms (inrush does not alert)"),
    ("off_quiet", "no threshold alert in a bulb-off episode"),
    ("alerts_cleared", "every bulb-on alert resolved by the node"),
    ("local_warning", "LED and buzzer seen in every on episode and in no off episode"),
    ("remote_within_10s", "event to dashboard (opened + 5 s refresh) and to webhook <= 10 s"),
    ("no_health_alerts", "no pipeline_health alert during the run"),
)


def parse_time(text: str) -> datetime:
    t = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    if t.tzinfo is None:
        raise ValueError(f"time without zone: {text!r}")
    return t.astimezone(UTC)


@dataclass(frozen=True)
class Episode:
    number: int
    kind: str  # on | off
    server: str  # up | down
    start: datetime
    end: datetime
    local_warning_seen: bool
    notes: str


def read_episodes(path: Path) -> list[Episode]:
    out = []
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            kind, server = row["kind"].strip(), row["server"].strip()
            seen = row["local_warning_seen"].strip().lower()
            if (
                kind not in ("on", "off")
                or server not in ("up", "down")
                or seen not in ("yes", "no")
            ):
                raise ValueError(f"episode {row['episode']}: bad kind/server/local_warning_seen")
            ep = Episode(
                int(row["episode"]),
                kind,
                server,
                parse_time(row["start_utc"]),
                parse_time(row["end_utc"]),
                seen == "yes",
                (row.get("notes") or "").strip(),
            )
            if ep.end <= ep.start:
                raise ValueError(f"episode {ep.number}: end before start")
            out.append(ep)
    return out


def _t(doc: dict[str, Any], key: str) -> datetime | None:
    value = doc.get(key)
    return parse_time(value) if value else None


def evaluate(episodes: list[Episode], export: dict[str, Any]) -> dict[str, Any]:
    confirm = timedelta(milliseconds=int(export["config"]["confirm_ms"]))
    alerts = export["alerts"]
    threshold = [a for a in alerts if a["kind"] == "active_power_threshold"]
    health = [a for a in alerts if a["kind"] == "pipeline_health"]
    failures: dict[str, list[str]] = {name: [] for name, _ in CHECKS}

    on_up = [e for e in episodes if e.kind == "on" and e.server == "up"]
    off_up = [e for e in episodes if e.kind == "off" and e.server == "up"]
    on_down = [e for e in episodes if e.kind == "on" and e.server == "down"]
    if len(on_up) < MIN_ON or len(off_up) < MIN_OFF or len(on_down) < MIN_DOWN:
        failures["enough_episodes"].append(
            f"{len(on_up)} on, {len(off_up)} off, {len(on_down)} on with server down"
        )

    def in_span(a: dict[str, Any], lo: datetime, hi: datetime) -> bool:
        t = _t(a, "event_observed_at")
        return t is not None and lo <= t <= hi

    remote_dashboard: list[float] = []
    remote_webhook: list[float] = []
    per_episode = []
    for ep in episodes:
        record: dict[str, Any] = {"episode": ep.number, "kind": ep.kind, "server": ep.server}
        if ep.kind == "on":
            hits = [
                a
                for a in threshold
                if in_span(a, ep.start + confirm - CLOCK_TOLERANCE, ep.end + CLOCK_TOLERANCE)
            ]
            early = [
                a for a in threshold if in_span(a, ep.start, ep.start + confirm - CLOCK_TOLERANCE)
            ]
            record["alert_ids"] = [a["alert_id"] for a in hits]
            if len(hits) != 1:
                failures["on_alerts_once"].append(f"episode {ep.number}: {len(hits)} alerts")
            if early:
                failures["no_early_alert"].append(f"episode {ep.number}: {len(early)} early")
            for a in hits:
                if a["status"] != "resolved":
                    failures["alerts_cleared"].append(f"episode {ep.number}: {a['status']}")
                observed, opened = _t(a, "event_observed_at"), _t(a, "opened_at")
                delivered = _t(a, "delivered_at")
                if observed is None or opened is None:
                    continue
                dash = (opened - observed).total_seconds() + DASHBOARD_REFRESH_S
                record["event_to_dashboard_s"] = round(dash, 3)
                if delivered is not None:
                    record["event_to_webhook_s"] = round((delivered - observed).total_seconds(), 3)
                if ep.server == "up":
                    remote_dashboard.append(dash)
                    if dash > REMOTE_BOUND_S:
                        failures["remote_within_10s"].append(f"episode {ep.number}: {dash:.1f} s")
                    if delivered is not None:
                        hook = (delivered - observed).total_seconds()
                        remote_webhook.append(hook)
                        if hook > REMOTE_BOUND_S:
                            failures["remote_within_10s"].append(
                                f"episode {ep.number}: webhook {hook:.1f} s"
                            )
            if not ep.local_warning_seen:
                failures["local_warning"].append(f"episode {ep.number}: not seen")
        else:
            hits = [a for a in threshold if in_span(a, ep.start + CLOCK_TOLERANCE, ep.end)]
            record["alert_ids"] = [a["alert_id"] for a in hits]
            if hits:
                failures["off_quiet"].append(f"episode {ep.number}: {len(hits)} alerts")
            if ep.local_warning_seen:
                failures["local_warning"].append(f"episode {ep.number}: seen with bulb off")
        per_episode.append(record)
    if health:
        failures["no_health_alerts"].append(f"{len(health)} pipeline_health alerts")

    def stats(xs: list[float]) -> dict[str, Any]:
        if not xs:
            return {"count": 0}
        return {"count": len(xs), "p50": round(statistics.median(xs), 3), "max": round(max(xs), 3)}

    return {
        "checks": [
            {"name": n, "rule": rule, "passed": not failures[n], "failures": failures[n]}
            for n, rule in CHECKS
        ],
        "passed": all(not f for f in failures.values()),
        "episodes": per_episode,
        "event_to_dashboard_s": stats(remote_dashboard),
        "event_to_webhook_s": stats(remote_webhook),
        "threshold_alerts": len(threshold),
        "pipeline_health_alerts": len(health),
    }


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def markdown(run_id: str, result: dict[str, Any], config: dict[str, Any]) -> str:
    lines = [
        f"# E2 alert run {run_id}",
        "",
        "Values are not validated (nominal calibration, no reference meter).",
        "",
        f"Config v{config['config_version']}: limit {config['limit_W']} W, "
        f"clear below {config['clear_below_W']} W, confirm {config['confirm_ms']} ms, "
        f"clear {config['clear_ms']} ms.",
        "",
        "| Check | Rule | Result |",
        "|---|---|---|",
    ]
    for c in result["checks"]:
        verdict = "pass" if c["passed"] else "FAIL: " + "; ".join(c["failures"])
        lines.append(f"| {c['name']} | {c['rule']} | {verdict} |")
    d = result["event_to_dashboard_s"]
    lines += ["", f"Event to dashboard (s): {json.dumps(d)}", ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    p.add_argument("--episodes", type=Path, required=True)
    p.add_argument("--export", type=Path, required=True)
    p.add_argument("--run-id", required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--manifest", type=Path, required=True)
    args = p.parse_args(argv)
    export = json.loads(args.export.read_text(encoding="utf-8"))
    result = evaluate(read_episodes(args.episodes), export)
    args.out.mkdir(parents=True, exist_ok=True)
    report = args.out / f"e2-{args.run_id}.md"
    report.write_text(markdown(args.run_id, result, export["config"]), encoding="utf-8")
    roles = (
        ("episodes", args.episodes),
        ("export", args.export),
        ("script", Path(__file__).resolve()),
        ("report_md", report),
    )
    manifest = {
        "experiment": "E2",
        "run_id": args.run_id,
        "validation": "not_validated",
        "node_id": export.get("node_id"),
        "utc_interval": export.get("utc_interval"),
        "config": export["config"],
        "result": result,
        "files": [{"role": r, "path": str(f), "sha256": sha256(f)} for r, f in roles],
        "environment": {"python": platform.python_version(), "platform": platform.platform()},
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(report.read_text(encoding="utf-8"))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
