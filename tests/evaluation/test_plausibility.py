"""Plausibility evaluation (T102, written before T061): known answers for table E1.

SC-001 / plan > Calibration and plausibility procedure, step 7: V_RMS in 10-16 V,
P positive and within ±20 % of the nameplate, bulb-off current within the noise
limit, >=5 min on and >=1 min off; windows flagged only `calibration_missing`
are admissible, any other flag (or an invalid window) is not.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "plausibility"


def _load():
    path = ROOT / "experiments" / "evaluation" / "plausibility.py"
    spec = importlib.util.spec_from_file_location("plausibility", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["plausibility"] = module
    spec.loader.exec_module(module)
    return module


pl = _load()


def window(load="on", v=12.0, i=1.7, p=20.0, state="valid", flags=()):
    return pl.Window(
        window_end=f"2026-11-25T10:00:{len(flags):02d}.000Z",
        load_state=load,
        quality_state=state,
        quality_flags=tuple(flags),
        voltage_rms=v,
        current_rms=i,
        active_power=p,
    )


def session(on=None, off=None, n_on=60, n_off=12):
    on = on or window()
    off = off or window(load="off", i=0.02, p=0.0)
    return [on] * n_on + [off] * n_off


def evaluate(windows, nameplate=20.0, noise=0.05):
    return pl.evaluate(windows, nameplate_w=nameplate, noise_limit_a=noise)


# ---- admissibility ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("state", "flags", "ok"),
    [
        ("valid", (), True),
        ("degraded", ("calibration_missing",), True),
        ("degraded", ("calibration_missing", "clock_unsynchronized"), False),
        ("degraded", ("out_of_range",), False),
        ("degraded", ("energy_continuity_uncertain",), False),
        ("invalid", ("sample_gap",), False),
        ("invalid", (), False),
    ],
)
def test_admissibility(state, flags, ok):
    assert pl.admissible(window(state=state, flags=flags)) is ok


def test_inadmissible_windows_are_excluded_and_counted():
    bad = window(p=-50.0, v=30.0, state="invalid", flags=("sample_gap",))
    r = evaluate([*session(), bad, bad, window(state="degraded", flags=("out_of_range",))])
    assert r.passed
    assert r.n_on == 63
    assert r.n_on_admissible == 60
    assert r.excluded == {"sample_gap": 2, "out_of_range": 1}


# ---- the four criteria -----------------------------------------------------------


@pytest.mark.parametrize(
    ("p", "d_p", "ok"),
    [
        (20.0, 0.0, True),
        (24.0, 20.0, True),  # boundary is inside
        (16.0, -20.0, True),
        (24.1, 20.5, False),
        (15.9, -20.5, False),
    ],
)
def test_power_within_20_percent_of_nameplate(p, d_p, ok):
    r = evaluate(session(on=window(p=p)))
    assert r.d_p_pct == pytest.approx(d_p)
    assert r.checks["power_within_20pct"] is ok
    assert r.passed is ok


def test_negative_power_fails_even_if_mean_is_close():
    on = [window(p=20.0)] * 59 + [window(p=-0.5)]
    r = evaluate(on + [window(load="off", i=0.02, p=0.0)] * 12)
    assert r.checks["power_positive"] is False
    assert not r.passed


@pytest.mark.parametrize(("v", "ok"), [(10.0, True), (16.0, True), (9.9, False), (16.1, False)])
def test_voltage_range(v, ok):
    r = evaluate(session(on=window(v=v)))
    assert r.checks["voltage_in_range"] is ok


@pytest.mark.parametrize(("i", "ok"), [(0.0, True), (0.05, True), (0.051, False)])
def test_bulb_off_current_at_noise_limit(i, ok):
    r = evaluate(session(off=window(load="off", i=i, p=0.0)))
    assert r.i_off_max_a == pytest.approx(i)
    assert r.checks["off_current_at_noise_limit"] is ok


@pytest.mark.parametrize(
    ("n_on", "n_off", "ok"), [(60, 12, True), (59, 12, False), (60, 11, False)]
)
def test_minimum_capture_durations(n_on, n_off, ok):
    r = evaluate(session(n_on=n_on, n_off=n_off))
    assert r.checks["enough_windows"] is ok


def test_coverage_counts_admissible_windows_only():
    gaps = [window(state="invalid", flags=("sample_gap",))] * 5
    r = evaluate(session(n_on=58) + gaps)
    assert r.checks["enough_windows"] is False


def test_no_admissible_windows_fails_without_crashing():
    r = evaluate([window(state="invalid", flags=("sample_gap",))])
    assert not r.passed
    assert r.d_p_pct is None


# ---- fixture and outputs ---------------------------------------------------------


def test_fixture_known_answers():
    windows = pl.load_summaries(FIXTURES / "example.csv")
    nameplate = pl.load_nameplate(FIXTURES / "example-nameplate.csv", "bulb-12v-20w")
    r = pl.evaluate(windows, nameplate_w=nameplate, noise_limit_a=0.05)
    assert (r.n_on, r.n_on_admissible, r.n_off, r.n_off_admissible) == (64, 61, 12, 12)
    assert r.excluded == {"sample_gap": 1, "clock_unsynchronized": 1, "adc_clipped": 1}
    assert r.p_mean_w == pytest.approx(20.5, abs=1e-9)
    assert r.d_p_pct == pytest.approx(2.5, abs=1e-9)
    assert (r.v_min_v, r.v_max_v) == (12.0, 12.2)
    assert r.i_off_max_a == pytest.approx(0.03)
    assert r.passed


def test_cli_writes_table_and_manifest(tmp_path):
    rc = pl.main(
        [
            "--summaries", str(FIXTURES / "example.csv"),
            "--nameplate", str(FIXTURES / "example-nameplate.csv"),
            "--load-id", "bulb-12v-20w",
            "--noise-limit-a", "0.05",
            "--run-id", "fixture",
            "--out", str(tmp_path),
        ]
    )  # fmt: skip
    assert rc == 0
    table = (tmp_path / "e1-fixture.csv").read_text()
    assert "power_within_20pct" in table
    assert "PASS" in table
    assert "no reference" in (tmp_path / "e1-fixture.md").read_text()
    manifest = json.loads((tmp_path / "e1-fixture.manifest.json").read_text())
    for entry in manifest["files"]:
        data = Path(entry["path"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == entry["sha256"]
    roles = {e["role"] for e in manifest["files"]}
    assert roles == {"summaries", "nameplate", "script", "table_csv", "table_md"}
    assert manifest["parameters"]["noise_limit_a"] == 0.05


def test_cli_exit_status_reports_failure(tmp_path):
    rc = pl.main(
        [
            "--summaries", str(FIXTURES / "example.csv"),
            "--nameplate", str(FIXTURES / "example-nameplate.csv"),
            "--load-id", "bulb-12v-20w",
            "--noise-limit-a", "0.01",  # off current 0.03 A is above it
            "--run-id", "strict",
            "--out", str(tmp_path),
        ]
    )  # fmt: skip
    assert rc == 1
    assert "FAIL" in (tmp_path / "e1-strict.csv").read_text()


def test_unknown_load_id_is_an_error():
    with pytest.raises(KeyError):
        pl.load_nameplate(FIXTURES / "example-nameplate.csv", "missing")
