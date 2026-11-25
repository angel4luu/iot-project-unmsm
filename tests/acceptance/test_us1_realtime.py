"""T042: simulated acceptance of user story 1 (SC-002, SC-006 software part).

Publishes the simulator's `normal` scenario in real time through the live stack
for `ACCEPTANCE_DURATION_S` seconds (default 60; `make acceptance-simulated`
uses 3600, the SC-002 hour), then checks:

- SC-002: at least 95 % of the scheduled 5 s summaries are visible within 10 s
  of the end of their window. Visible = stored (server store time minus window
  end, `store_lag_ms`) plus the dashboard's 5 s refresh, so the bound applied
  is store lag <= 5 s. No accepted window is stored twice.
- SC-006 (stored data): every summary carries units (canonical field names),
  its timestamp, quality, calibration revision, and `validation=not_validated`.

A JSON summary of the run is written to the ignored `experiments/data/acceptance/`.
"""

import json
import os
import secrets
import statistics
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from tests import stack

from energy_ingestion.cli.simulate import SimulatedNode

pytestmark = pytest.mark.integration
DURATION_S = int(os.environ.get("ACCEPTANCE_DURATION_S", "60"))
REFRESH_S = 5.0
VISIBLE_WITHIN_S = 10.0
EVIDENCE = stack.REPO / "experiments" / "data" / "acceptance"
UNIT_FIELDS = ("voltage_rms_V", "current_rms_A", "active_power_W", "active_energy_import_total_Wh")


def test_us1_realtime_acceptance() -> None:
    stack.require_stack()
    run_id = f"us1-{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{secrets.token_hex(2)}"
    started = datetime.now(UTC)
    node = SimulatedNode("normal", started, seed=secrets.randbits(32))
    sent: list[str] = []
    acks: dict[str, str] = {}
    with stack.sim_link() as link:
        for msg in node.messages(timedelta(seconds=DURATION_S)):
            delay = (msg.at - datetime.now(UTC)).total_seconds()
            if delay > 0:
                time.sleep(delay)
            link.publish(msg.topic, msg.payload, retain=msg.retain)
            if msg.kind == "measurement":
                sent.append(json.loads(msg.payload)["message_id"])
        for mid in sent:
            ack = link.wait_ack(mid, timeout_s=15)
            acks[mid] = ack["status"] if ack else "none"

    rows = stack.flux(
        f'from(bucket: "energy_raw") |> range(start: {started.isoformat()}, stop: now())'
        ' |> filter(fn: (r) => r._measurement == "electrical_measurement")'
        f' |> filter(fn: (r) => r.node_id == "{node.node_id}")'
        ' |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")'
    )
    ours = [r for r in rows if r.get("message_id") in set(sent)]
    stored_ids = [r["message_id"] for r in ours]
    lags_s = sorted(float(r["store_lag_ms"]) / 1000 for r in ours)
    visible = [lag for lag in lags_s if lag + REFRESH_S <= VISIBLE_WITHIN_S]
    share = len(visible) / len(sent) if sent else 0.0

    summary = {
        "run_id": run_id,
        "duration_s": DURATION_S,
        "scheduled_windows": len(sent),
        "stored_windows": len(ours),
        "duplicates_stored": len(stored_ids) - len(set(stored_ids)),
        "acks": {s: list(acks.values()).count(s) for s in set(acks.values())},
        "visible_within_10s_share": round(share, 4),
        "store_lag_s": {
            "p50": round(statistics.median(lags_s), 3) if lags_s else None,
            "p95": round(lags_s[int(0.95 * (len(lags_s) - 1))], 3) if lags_s else None,
            "max": round(lags_s[-1], 3) if lags_s else None,
        },
        "visibility_rule": "store_lag + 5 s dashboard refresh <= 10 s",
        "validation_labels": sorted({r.get("validation", "") for r in ours}),
        "note": "simulated node; values are not validated",
    }
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    Path(EVIDENCE / f"{run_id}.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary))

    assert sent, "the run published no measurements"
    # SC-002
    assert share >= 0.95, summary
    assert summary["duplicates_stored"] == 0, summary
    assert set(acks.values()) == {"accepted"}, summary
    # SC-006 (stored data)
    for r in ours:
        for field in UNIT_FIELDS:
            assert r.get(field), f"{field} missing in {r['message_id']}"
        assert r["_time"]
        assert r["quality"] in ("valid", "degraded", "invalid")
        assert r["calibration_revision"]
        assert r["calibration_revision"] != "none"
        assert r["validation"] == "not_validated"
