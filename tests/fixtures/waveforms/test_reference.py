"""T096: the reference calculation agrees with the physical truth of each fixture.

Truth (CSV header, written by generate.py) and reference (computed from raw mV
by reference.py) are produced independently; the firmware is later compared
with expected.json (T035) within the same tolerances.
"""

import math

import pytest

from tests.fixtures.waveforms import generate, reference

pytestmark = pytest.mark.unit
CLEAN = ("sine_inphase", "lag60", "dc_offset", "no_current")


def within(value: float, target: float, tol: dict[str, float]) -> bool:
    return abs(value - target) <= max(tol["abs"], tol["rel"] * abs(target))


def truth(name: str) -> dict[str, float]:
    h = reference.load(name).header
    p = h["v_rms"] * h["i_rms"] * math.cos(math.radians(h["lag_deg"]))
    return {
        "v_rms_v": h["v_rms"],
        "i_rms_a": h["i_rms"],
        "active_power_w": p,
        "energy_wh": p * h["duration_s"] / 3600,
    }


def test_fixtures_and_expected_are_current() -> None:
    assert generate.main(["--check"]) == 0
    assert reference.main(["--check"]) == 0


def test_generator_and_reference_share_only_frontend_constants() -> None:
    gv, gi = reference.gains()
    assert gv == pytest.approx(generate.voltage_gain_mv_per_v())
    assert gi == pytest.approx(generate.current_gain_mv_per_a())
    # plan.md: 12 V RMS -> about +-0.76 V peak; 1.7 A RMS -> about +-0.16 V peak
    assert 12 * math.sqrt(2) * gv / 1000 == pytest.approx(0.76, abs=0.01)
    assert 1.7 * math.sqrt(2) * gi / 1000 == pytest.approx(0.16, abs=0.01)


# no_current is checked against the noise limit instead, except for voltage.
TRUTH_CASES = [
    (name, q)
    for name in CLEAN
    for q in sorted(reference.TOLERANCE)
    if name != "no_current" or q == "v_rms_v"
]


@pytest.mark.parametrize(("name", "quantity"), TRUTH_CASES)
def test_reference_matches_truth(name: str, quantity: str) -> None:
    got = reference.compute(reference.load(name))[quantity]
    assert within(got, truth(name)[quantity], reference.TOLERANCE[quantity])


def test_power_is_mean_of_v_times_i_not_vrms_times_irms() -> None:
    got = reference.compute(reference.load("lag60"))
    assert got["active_power_w"] == pytest.approx(0.5 * got["v_rms_v"] * got["i_rms_a"], rel=0.01)


def test_phase_correction_is_needed() -> None:
    w = reference.load("lag60")
    uncorrected = reference.compute(w, phase_correction=False)["active_power_w"]
    tol = reference.TOLERANCE["active_power_w"]
    assert not within(uncorrected, truth("lag60")["active_power_w"], tol)


def test_offsets_are_removed() -> None:
    a = reference.compute(reference.load("dc_offset"))
    b = reference.compute(reference.load("sine_inphase"))
    for q, tol in reference.TOLERANCE.items():
        assert within(a[q], b[q], tol)


def test_no_current_is_below_the_noise_limit() -> None:
    got = reference.compute(reference.load("no_current"))
    assert got["i_rms_a"] < reference.FRONTEND["zero_noise_current_a"]
    assert abs(got["active_power_w"]) < 0.05


@pytest.mark.parametrize(
    ("name", "flag"), [("clipping", "adc_clipped"), ("sample_gap", "sample_gap")]
)
def test_faults_are_flagged_and_invalid(name: str, flag: str) -> None:
    entry = reference.expected()["fixtures"][name]
    assert entry["flags"] == [flag]
    assert entry["valid"] is False
    assert entry["active_power_w"] is None


@pytest.mark.parametrize("name", CLEAN)
def test_clean_fixtures_have_no_flags(name: str) -> None:
    assert reference.flags_of(reference.load(name)) == []


def test_every_fixture_is_one_second_of_pairs() -> None:
    for name in reference.FIXTURES:
        w = reference.load(name)
        assert w.header["pairs"] == len(w.pair)
        assert w.pair[-1] == 3999
