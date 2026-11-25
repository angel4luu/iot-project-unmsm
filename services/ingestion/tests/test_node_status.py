"""T099: server-derived node status timers (stale after 15 s, offline after 30 s or last will)."""

from datetime import UTC, datetime, timedelta

import pytest

from energy_ingestion.health.node_status import NodeStatusTracker

pytestmark = pytest.mark.unit
T0 = datetime(2026, 10, 14, 17, 0, 0, tzinfo=UTC)


def at(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


def status(state: str) -> dict[str, object]:
    return {
        "node_id": "node-001",
        "state": state,
        "acquisition_state": "running",
        "clock_source": "sntp",
        "firmware_version": "0.1.0",
        "calibration_revision": None,
        "pending_records": 3,
        "oldest_pending_age_s": 12,
    }


def live_tracker() -> NodeStatusTracker:
    t = NodeStatusTracker()
    t.on_status(status("online"), at(0))
    t.on_measurement("node-001", at(0), at(0))
    return t


def test_new_node_without_measurements_is_stale() -> None:
    t = NodeStatusTracker()
    t.on_status(status("online"), at(0))
    assert t.nodes["node-001"].state == "stale"


def test_measurement_makes_it_online() -> None:
    assert live_tracker().nodes["node-001"].state == "online"


@pytest.mark.parametrize(
    ("silent_s", "state"),
    [(15.0, "online"), (15.1, "stale"), (30.0, "stale"), (30.1, "offline")],
)
def test_timers_use_the_last_measurement(silent_s: float, state: str) -> None:
    t = live_tracker()
    t.tick(at(silent_s))
    assert t.nodes["node-001"].state == state


def test_transitions_are_reported_once() -> None:
    t = live_tracker()
    (first,) = t.tick(at(16))
    assert (first.old, first.new) == ("online", "stale")
    assert t.tick(at(17)) == []
    (second,) = t.tick(at(31))
    assert (second.old, second.new) == ("stale", "offline")


def test_last_will_is_offline_immediately() -> None:
    t = live_tracker()
    (tr,) = t.on_status(status("offline"), at(1))
    assert tr.new == "offline"


def test_measurement_after_last_will_brings_it_back() -> None:
    t = live_tracker()
    t.on_status(status("offline"), at(1))
    t.on_measurement("node-001", at(5), at(6))
    assert t.nodes["node-001"].state == "online"


def test_reported_degraded_is_kept_while_measurements_arrive() -> None:
    t = live_tracker()
    t.on_status(status("degraded"), at(2))
    assert t.nodes["node-001"].state == "degraded"
    t.tick(at(20))
    assert t.nodes["node-001"].state == "stale"  # silence wins over the report


def test_replayed_old_window_does_not_move_newest_window_back() -> None:
    t = live_tracker()
    t.on_measurement("node-001", at(-600), at(3))  # replay after an outage
    assert t.nodes["node-001"].newest_window_end == at(0)


def test_heartbeat_points_carry_state_and_ages() -> None:
    t = live_tracker()
    (point,) = t.points(at(7))
    line = point.to_line_protocol()
    assert line.startswith("node_status,node_id=node-001 ")
    assert 'state="online"' in line
    assert 'calibration_revision="none"' in line
    assert "pending_records=3i" in line
    assert "last_measurement_age_s=7" in line


def test_no_age_before_the_first_measurement() -> None:
    t = NodeStatusTracker()
    t.on_status(status("online"), at(0))
    (point,) = t.points(at(1))
    assert "last_measurement_age_s" not in point.to_line_protocol()
