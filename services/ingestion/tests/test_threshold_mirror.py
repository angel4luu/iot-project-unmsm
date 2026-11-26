"""The simulator's threshold mirror follows the firmware's table (T076 cases)."""

from pathlib import Path

import pytest

from energy_ingestion.thresholds.local import LocalThreshold, State

pytestmark = pytest.mark.unit
CASES = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "threshold" / "cases.txt"
LETTER = {
    "threshold_entered": "E",
    "threshold_cleared": "R",
    "measurement_quality_changed": "Q",
}


def cases() -> list[tuple[str, list[str]]]:
    out = []
    for line in CASES.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            name, *fields = (f.strip() for f in line.split("|"))
            out.append((name, fields))
    return out


def test_table_is_present() -> None:
    assert len(cases()) >= 10


@pytest.mark.parametrize(("name", "fields"), cases(), ids=[c[0] for c in cases()])
def test_mirror_follows_the_shared_table(name: str, fields: list[str]) -> None:
    cfg, blocks, states, events = (f.split() for f in fields)
    thr = LocalThreshold(float(cfg[0]), float(cfg[1]), int(cfg[2]), int(cfg[3]))
    assert len(blocks) == len(states) == len(events), name
    for k, (b, st, ev) in enumerate(zip(blocks, states, events, strict=True)):
        got = thr.step(None if b == "x" else float(b))
        assert thr.state == State(st), (name, k)
        assert "".join(LETTER[e.event_type] for e in got) == ("" if ev == "-" else ev), (name, k)
        assert thr.warning_active == (thr.state in (State.FIRING, State.CLEARING)), (name, k)


def test_events_carry_the_evidence() -> None:
    thr = LocalThreshold(15.0, 14.25, 1000, 1000, severity="critical")
    (entered,) = thr.step(18.0)
    assert (entered.severity, entered.measured_value, entered.threshold_value) == (
        "critical",
        18.0,
        15.0,
    )
    assert entered.local_warning_active
    (cleared,) = thr.step(3.0)
    assert (cleared.severity, cleared.threshold_value, cleared.local_warning_active) == (
        "info",
        14.25,
        False,
    )
    (lost,) = thr.step(None)
    assert (lost.quality, lost.measured_value, lost.threshold_value) == ("invalid", None, None)
    assert lost.reason_code == "sensor_disconnected"
