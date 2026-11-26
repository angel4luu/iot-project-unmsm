"""T041: dashboard provisioning smoke test against the live stack.

Datasource healthy, dashboard provisioned read-only, and panel 2 (current cards)
shows `NO DATA` for a node that never sent, a number only while the node is
online with a fresh valid window, and `STALE` once it goes quiet: never a zero
or a fabricated last value. Queries go through Grafana itself (`/api/ds/query`).
"""

import json
import secrets
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from tests import stack

from energy_ingestion.cli.simulate import SimulatedNode

pytestmark = pytest.mark.integration
DASH_UID = "energy-overview"
DS_UID = "influxdb-energy"


@pytest.fixture(scope="module")
def dashboard() -> dict[str, Any]:
    stack.require_stack()
    out: dict[str, Any] = stack.grafana(f"/api/dashboards/uid/{DASH_UID}")
    return out


def panel_query(dash: dict[str, Any], panel_id: int) -> str:
    def walk(panels: list[dict[str, Any]]) -> Any:
        for p in panels:
            if p.get("id") == panel_id:
                return p["targets"][0]["query"]
            found = walk(p.get("panels", []))
            if found:
                return found
        return None

    query = walk(dash["panels"])
    assert query, f"panel {panel_id} not found"
    return str(query)


def cards(dash: dict[str, Any], node: str) -> dict[str, str]:
    """Panel 2 rendered by Grafana: metric -> displayed value."""
    body = {
        "from": "now-15m",
        "to": "now",
        "queries": [
            {
                "refId": "A",
                "datasource": {"type": "influxdb", "uid": DS_UID},
                "query": panel_query(dash, 2).replace("${node}", node),
            }
        ],
    }
    result = stack.grafana("/api/ds/query", body)["results"]["A"]
    assert "error" not in result, result.get("error")
    shown: dict[str, str] = {}
    for frame in result["frames"]:
        names = [f["name"] for f in frame["schema"]["fields"]]
        columns = dict(zip(names, frame["data"]["values"], strict=True))
        for metric, value in zip(columns["metric"], columns["value"], strict=True):
            shown[metric] = value
    return shown


def test_datasource_is_healthy() -> None:
    stack.require_stack()
    health = stack.grafana(f"/api/datasources/uid/{DS_UID}/health")
    assert health["status"] == "OK", health


def test_dashboard_is_provisioned_read_only(dashboard: dict[str, Any]) -> None:
    dash, meta = dashboard["dashboard"], dashboard["meta"]
    assert dash["title"] == "Energy overview"
    assert dash["editable"] is False
    assert meta.get("provisioned") is True
    ids = {p["id"] for p in dash["panels"]}
    assert ids >= {1, 2, 3, 4, 5, 6, 7, 8}  # 5: history (US2), 7: alerts (US3)


def test_rows_do_not_hide_panels(dashboard: dict[str, Any]) -> None:
    """Grafana shows a row's nested `panels` only when it is collapsed; an expanded
    row's panels must follow it at the top level, or they are not displayed."""
    for p in dashboard["dashboard"]["panels"]:
        if p["type"] == "row":
            assert p.get("collapsed") is False, p["title"]
            assert p.get("panels", []) == [], f"panels nested in expanded row {p['title']!r}"


def test_history_panels_use_the_query_files(dashboard: dict[str, Any]) -> None:
    """Panel 5 and its stats run exactly the reviewed .flux files (T071, T072)."""
    queries = Path(__file__).resolve().parents[2] / "dashboards" / "queries"
    for panel_id, name in ((5, "hourly"), (51, "daily"), (52, "weekly"), (53, "peak_hour")):
        expected = (queries / f"{name}.flux").read_text(encoding="utf-8").strip()
        assert panel_query(dashboard["dashboard"], panel_id).strip() == expected, name


def test_node_that_never_sent_shows_no_data(dashboard: dict[str, Any]) -> None:
    shown = cards(dashboard["dashboard"], f"never-{secrets.token_hex(3)}")
    assert set(shown.values()) == {"NO DATA"}, shown


def test_live_then_stale_never_zero(dashboard: dict[str, Any]) -> None:
    dash = dashboard["dashboard"]
    node = SimulatedNode("normal", datetime.now(UTC), seed=secrets.randbits(32))
    msgs = list(node.messages(timedelta(seconds=10)))  # status + two windows
    with stack.sim_link() as link:
        for msg in msgs:
            delay = (msg.at - datetime.now(UTC)).total_seconds()
            if delay > 0:
                time.sleep(delay)
            link.publish(msg.topic, msg.payload, retain=msg.retain)
            if msg.kind == "measurement":
                ack = link.wait_ack(json.loads(msg.payload)["message_id"])
                assert ack is not None
                assert ack["status"] == "accepted"
    live = stack.wait_until(
        lambda: (s := cards(dash, node.node_id)) and _numeric(s.get("Active power")) and s, 8
    )
    assert live, "panel 2 never showed the live value"
    assert float(live["Active power"]) > 0
    assert float(live["V RMS"]) > 0
    assert "Wh" in live["Import energy"]

    # Quiet for more than 15 s: the server marks the node stale and the cards stop
    # showing numbers (no last value kept on screen).
    stale = stack.wait_until(
        lambda: (s := cards(dash, node.node_id)) and not any(_numeric(v) for v in s.values()) and s,
        30,
        every_s=2,
    )
    assert stale, "panel 2 kept showing a number after the node went quiet"
    assert set(stale.values()) <= {"STALE", "OFFLINE"}, stale


def _numeric(value: str | None) -> bool:
    try:
        float(value or "")
    except ValueError:
        return False
    return True
