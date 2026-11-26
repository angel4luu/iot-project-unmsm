"""E2 alert run evaluation (T108): known answers for experiments/evaluation/alerts.py."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load():
    path = ROOT / "experiments" / "evaluation" / "alerts.py"
    spec = importlib.util.spec_from_file_location("alerts_eval", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["alerts_eval"] = module
    spec.loader.exec_module(module)
    return module


ev = _load()
T0 = datetime(2026, 11, 30, 15, 0, tzinfo=UTC)
CONFIG = {
    "config_version": 2,
    "limit_W": 15.0,
    "clear_below_W": 14.25,
    "confirm_ms": 10000,
    "clear_ms": 10000,
}


def iso(t: datetime) -> str:
    return t.isoformat().replace("+00:00", "Z")


def plan(n_on=5, n_off=5, n_down=1):
    """Alternating 60 s episodes with 30 s gaps; server-down episodes go last."""
    kinds = []
    for k in range(max(n_on, n_off)):
        if k < n_on:
            kinds.append(("on", "up"))
        if k < n_off:
            kinds.append(("off", "up"))
    kinds += [("on", "down")] * n_down
    out = []
    for n, (kind, server) in enumerate(kinds, start=1):
        start = T0 + timedelta(seconds=90 * (n - 1))
        out.append(
            ev.Episode(n, kind, server, start, start + timedelta(seconds=60), kind == "on", "")
        )
    return out


def alert_for(ep, n, after_s=11.0, latency_s=0.4, status="resolved", webhook_s=None):
    observed = ep.start + timedelta(seconds=after_s)
    a = {
        "alert_id": f"a{n}",
        "kind": "active_power_threshold",
        "status": status,
        "event_observed_at": iso(observed),
        "opened_at": iso(observed + timedelta(seconds=latency_s)),
    }
    if webhook_s is not None:
        a["delivered_at"] = iso(observed + timedelta(seconds=webhook_s))
    return a


def good_run():
    episodes = plan()
    alerts = [alert_for(e, e.number) for e in episodes if e.kind == "on"]
    # The server-down alert arrives late, after restart: latency is not checked.
    alerts[-1]["opened_at"] = iso(episodes[-1].end + timedelta(seconds=40))
    return episodes, {"config": CONFIG, "alerts": alerts}


def failed(result):
    return {c["name"] for c in result["checks"] if not c["passed"]}


def test_good_run_passes():
    episodes, export = good_run()
    result = ev.evaluate(episodes, export)
    assert failed(result) == set()
    assert result["passed"]
    assert result["event_to_dashboard_s"]["count"] == 5
    assert result["event_to_dashboard_s"]["max"] == 5.4


def test_too_few_episodes():
    episodes = plan(n_on=4, n_down=0)
    alerts = [alert_for(e, e.number) for e in episodes if e.kind == "on"]
    assert failed(ev.evaluate(episodes, {"config": CONFIG, "alerts": alerts})) == {
        "enough_episodes"
    }


def test_missing_and_duplicate_alerts():
    episodes, export = good_run()
    export["alerts"].pop(0)
    export["alerts"].append(alert_for(episodes[2], 99, after_s=40))
    result = ev.evaluate(episodes, export)
    assert failed(result) == {"on_alerts_once"}
    names = {c["name"]: c["failures"] for c in result["checks"]}
    assert names["on_alerts_once"] == ["episode 1: 0 alerts", "episode 3: 2 alerts"]


def test_inrush_alert_before_confirm_is_early():
    episodes, export = good_run()
    export["alerts"].append(alert_for(episodes[0], 98, after_s=1.0))
    assert failed(ev.evaluate(episodes, export)) == {"no_early_alert"}


def test_alert_in_off_episode():
    episodes, export = good_run()
    export["alerts"].append(alert_for(episodes[1], 97, after_s=30))
    assert failed(ev.evaluate(episodes, export)) == {"off_quiet"}


def test_clock_tolerance_at_the_episode_edges():
    episodes, export = good_run()
    # 4 s late against the operator's clock: still inside the on episode's tolerance,
    # and the off episode ignores its first 5 s (the previous bulb-on tail).
    export["alerts"][0]["event_observed_at"] = iso(episodes[0].end + timedelta(seconds=4))
    export["alerts"][0]["opened_at"] = iso(episodes[0].end + timedelta(seconds=4.3))
    assert failed(ev.evaluate(episodes, export)) == set()


def test_unresolved_alert():
    episodes, export = good_run()
    export["alerts"][1]["status"] = "open"
    assert failed(ev.evaluate(episodes, export)) == {"alerts_cleared"}


def test_local_warning_observations():
    episodes, export = good_run()
    bad = [
        replace(e, local_warning_seen=e.kind == "off") if e.number in (1, 2) else e
        for e in episodes
    ]
    result = ev.evaluate(bad, export)
    assert failed(result) == {"local_warning"}
    (check,) = [c for c in result["checks"] if c["name"] == "local_warning"]
    assert check["failures"] == ["episode 1: not seen", "episode 2: seen with bulb off"]


def test_remote_bound_includes_dashboard_refresh():
    episodes, export = good_run()
    export["alerts"][0]["opened_at"] = iso(
        ev.parse_time(export["alerts"][0]["event_observed_at"]) + timedelta(seconds=5.1)
    )
    assert failed(ev.evaluate(episodes, export)) == {"remote_within_10s"}


def test_webhook_latency_is_checked_when_delivered():
    episodes, export = good_run()
    export["alerts"][0] = alert_for(episodes[0], 1, webhook_s=2.0)
    export["alerts"][2] = alert_for(episodes[4], 5, webhook_s=12.0)
    result = ev.evaluate(episodes, export)
    assert failed(result) == {"remote_within_10s"}
    assert result["event_to_webhook_s"] == {"count": 2, "p50": 7.0, "max": 12.0}


def test_health_alert_fails_the_run():
    episodes, export = good_run()
    export["alerts"].append({"alert_id": "h", "kind": "pipeline_health", "status": "open"})
    assert failed(ev.evaluate(episodes, export)) == {"no_health_alerts"}


def test_cli_writes_report_and_manifest(tmp_path):
    episodes, export = good_run()
    log = tmp_path / "episodes.csv"
    with log.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(ev.EPISODE_FIELDS)
        for e in episodes:
            seen = "yes" if e.local_warning_seen else "no"
            w.writerow([e.number, e.kind, e.server, iso(e.start), iso(e.end), seen, ""])
    export_path = tmp_path / "export.json"
    export_path.write_text(json.dumps({**export, "node_id": "node-01"}), encoding="utf-8")
    out = tmp_path / "out"
    manifest_path = tmp_path / "manifests" / "alerts-test.json"
    args = [
        "--episodes", str(log),
        "--export", str(export_path),
        "--run-id", "fixture",
        "--out", str(out),
        "--manifest", str(manifest_path),
    ]  # fmt: skip
    assert ev.main(args) == 0
    assert "not validated" in (out / "e2-fixture.md").read_text()
    manifest = json.loads(manifest_path.read_text())
    assert manifest["validation"] == "not_validated"
    assert manifest["result"]["passed"]
    for entry in manifest["files"]:
        assert hashlib.sha256(Path(entry["path"]).read_bytes()).hexdigest() == entry["sha256"]
    assert {e["role"] for e in manifest["files"]} == {"episodes", "export", "script", "report_md"}

    export["alerts"].pop(0)
    export_path.write_text(json.dumps(export), encoding="utf-8")
    assert ev.main(args) == 1


def test_bad_episode_rows_are_rejected(tmp_path):
    log = tmp_path / "e.csv"
    log.write_text(
        ",".join(ev.EPISODE_FIELDS)
        + "\n1,on,up,2026-11-30T15:00:00Z,2026-11-30T15:01:00Z,maybe,\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="episode 1"):
        ev.read_episodes(log)


# ---- exporter (experiments/export/alerts_run.py) -----------------------------------


def _load_exporter():
    sys.path.insert(0, str(ROOT / "experiments" / "export"))
    spec = importlib.util.spec_from_file_location(
        "alerts_run", ROOT / "experiments" / "export" / "alerts_run.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["alerts_run"] = module
    spec.loader.exec_module(module)
    return module


FLUX_CSV = """#group,false,false,true,true,false,false,false
#datatype,string,long,dateTime:RFC3339,dateTime:RFC3339,dateTime:RFC3339,string,string
#default,_result,,,,,,
,result,table,_start,_stop,_time,alert_id,event_observed_at
,,0,2026-11-30T15:00:00Z,2026-11-30T15:30:00Z,2026-11-30T15:00:11.400Z,a1,2026-11-30T15:00:11.000Z
,,0,2026-11-30T15:00:00Z,2026-11-30T15:30:00Z,2026-11-30T15:03:11.000Z,a2,
"""


def _db(config=CONFIG):
    def note(state, at):
        return {"destination_type": "webhook", "state": state, "delivered_at": at}

    return {
        "config": config,
        "alerts": [
            {"alert_id": "a1", "kind": "active_power_threshold", "notifications": [
                note("delivered", "2026-11-30T15:00:12.000Z")
            ]},
            {"alert_id": "a2", "kind": "active_power_threshold", "notifications": [
                note("pending", None)
            ]},
        ],
    }  # fmt: skip


def test_export_merges_node_event_times_and_deliveries():
    ex = _load_exporter()
    queries = []

    def flux(q):
        queries.append(q)
        return FLUX_CSV

    since, until = T0, T0 + timedelta(minutes=30)
    doc = ex.export("node-001", since, until, lambda *_: _db(), flux)
    a1, a2 = doc["alerts"]
    assert (a1["event_observed_at"], a1["delivered_at"]) == (
        "2026-11-30T15:00:11.000Z",
        "2026-11-30T15:00:12.000Z",
    )
    assert (a2["event_observed_at"], a2["delivered_at"]) == (None, None)
    assert doc["utc_interval"] == {
        "since": "2026-11-30T15:00:00.000Z",
        "until": "2026-11-30T15:30:00.000Z",
    }
    assert doc["validation"] == "not_validated"
    assert 'r.node_id == "node-001"' in queries[0]
    assert 'r.to_status == "open"' in queries[0]


def test_export_needs_a_threshold_configuration():
    ex = _load_exporter()
    with pytest.raises(SystemExit, match="no threshold configuration"):
        ex.export("node-001", T0, T0 + timedelta(minutes=1), lambda *_: _db(None), lambda q: "")


def test_export_never_overwrites(tmp_path):
    ex = _load_exporter()
    out = tmp_path / "x.json"
    out.write_text("{}")
    with pytest.raises(SystemExit):
        ex.main(
            [
                "--node",
                "node-001",
                "--since",
                iso(T0),
                "--until",
                iso(T0 + timedelta(1)),
                "--out",
                str(out),
            ]
        )
    assert out.read_text() == "{}"
