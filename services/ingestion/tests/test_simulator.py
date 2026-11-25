"""T024: the simulator emits schema-valid telemetry and each scenario's behaviour."""

import io
import json
from contextlib import redirect_stdout
from datetime import UTC, datetime, timedelta
from itertools import groupby

import pytest

from energy_ingestion.cli.simulate import (
    SCENARIOS,
    STATUS_EVERY_S,
    WINDOW_S,
    Message,
    SimulatedNode,
    main,
    parse_duration,
)
from energy_ingestion.contracts.topics import check_identity
from energy_ingestion.contracts.validate import ContractError, validate_payload

pytestmark = pytest.mark.unit
START = datetime(2026, 11, 25, 12, 0, tzinfo=UTC)
TEN_MIN = timedelta(minutes=10)


def run(scenario: str, duration: timedelta = TEN_MIN) -> list[Message]:
    return list(SimulatedNode(scenario, START).messages(duration))


def windows(msgs: list[Message]) -> list[dict[str, object]]:
    return [json.loads(m.payload) for m in msgs if m.kind == "measurement"]


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_every_payload_matches_its_contract_flag(scenario: str) -> None:
    for msg in run(scenario):
        if msg.contract_valid:
            doc = validate_payload(msg.kind, msg.payload)
            assert check_identity("sim-001", msg.topic, doc) == "sim-001"
        else:
            with pytest.raises(ContractError):
                validate_payload(msg.kind, msg.payload)


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_every_window_uses_the_nominal_calibration(scenario: str) -> None:
    for w in windows(run(scenario)):
        assert w["quality"]["calibration_revision"] == "sim-001-nominal-r1"  # type: ignore[index]


def test_normal_is_the_plan_b_bulb() -> None:
    ws = windows(run("normal"))
    assert len(ws) == TEN_MIN.total_seconds() // WINDOW_S
    for w in ws:
        m = w["measurements"]
        assert 12.4 < m["voltage_rms"]["value"] < 12.8  # type: ignore[index]
        assert 1.5 < m["current_rms"]["value"] < 1.75  # type: ignore[index]
        assert 19.5 < m["active_power"]["value"] < 21.5  # type: ignore[index]
        assert w["quality"]["state"] == "valid"  # type: ignore[index]
    energy = [w["measurements"]["active_energy_import_total"]["value"] for w in ws]  # type: ignore[index]
    assert energy == sorted(energy)
    assert energy[-1] == pytest.approx(20.4 * 600 / 3600, rel=0.02)


def test_status_is_retained_every_30_s_and_last_will_is_offline() -> None:
    node = SimulatedNode("normal", START)
    msgs = list(node.messages(TEN_MIN))
    status = [m for m in msgs if m.kind == "node-status"]
    assert all(m.retain for m in status)
    assert len(status) == TEN_MIN.total_seconds() // STATUS_EVERY_S
    will = validate_payload("node-status", node.last_will())
    assert will["state"] == "offline"
    assert not any(m.retain for m in msgs if m.kind == "measurement")


def _above(msgs: list[Message], limit: float = 22.0) -> list[int]:
    flags = [w["measurements"]["active_power"]["value"] > limit for w in windows(msgs)]  # type: ignore[index]
    return [len(list(g)) for k, g in groupby(flags) if k]


def test_surge_never_lasts_a_confirmation_period() -> None:
    runs = _above(run("surge"))
    assert runs
    assert max(runs) * WINDOW_S < 10  # shorter than the default confirm_ms


def test_sustained_exceeds_for_30_s() -> None:
    runs = _above(run("sustained"))
    assert runs
    assert min(runs) * WINDOW_S >= 30


def test_normal_never_exceeds() -> None:
    assert _above(run("normal")) == []


def test_invalid_mixes_null_windows_and_contract_defects() -> None:
    msgs = run("invalid")
    assert any(not m.contract_valid for m in msgs)
    nulls = [w for w in windows(msgs) if w["quality"]["state"] == "invalid"]  # type: ignore[index]
    assert nulls
    assert all(w["measurements"]["active_power"]["value"] is None for w in nulls)  # type: ignore[index]


def test_outage_queues_then_drains_in_order() -> None:
    msgs = run("outage")
    seqs = [w["sequence"] for w in windows(msgs)]
    assert seqs == sorted(seqs)
    assert len(seqs) == TEN_MIN.total_seconds() // WINDOW_S
    send_times = [m.at for m in msgs if m.kind == "measurement"]
    burst = max(len(list(g)) for _, g in groupby(send_times))
    assert burst >= 30  # a third of 120 windows sent at reconnect


def test_duplicate_repeats_identical_bytes() -> None:
    meas = [m.payload for m in run("duplicate") if m.kind == "measurement"]
    assert len(meas) == 2 * len(set(meas))


def test_out_of_order_swaps_but_loses_nothing() -> None:
    seqs = [w["sequence"] for w in windows(run("out_of_order"))]
    assert seqs != sorted(seqs)
    assert sorted(seqs) == list(range(len(seqs)))


def test_clock_holdover_degrades_only_when_unsynchronized() -> None:
    ws = windows(run("clock_holdover"))
    sources = [w["clock"]["source"] for w in ws]  # type: ignore[index]
    assert [k for k, _ in groupby(sources)] == ["sntp", "holdover", "unsynchronized"]
    for w in ws:
        state = w["quality"]["state"]  # type: ignore[index]
        assert (state == "degraded") == (w["clock"]["source"] == "unsynchronized")  # type: ignore[index]


def test_runs_are_reproducible_with_a_seed() -> None:
    assert run("normal") == run("normal")


def test_unknown_scenario_is_refused() -> None:
    with pytest.raises(ValueError, match="unknown scenario"):
        SimulatedNode("nope", START)


@pytest.mark.parametrize(("text", "seconds"), [("30s", 30), ("10m", 600), ("1h", 3600)])
def test_parse_duration(text: str, seconds: int) -> None:
    assert parse_duration(text).total_seconds() == seconds


def test_cli_dry_run_prints_json_lines() -> None:
    buf = io.StringIO()
    with redirect_stdout(buf):
        assert main(["--scenario", "normal", "--duration", "30s", "--dry-run"]) == 0
    lines = [json.loads(x) for x in buf.getvalue().splitlines()]
    assert len([x for x in lines if x["topic"].endswith("/measurements")]) == 6
