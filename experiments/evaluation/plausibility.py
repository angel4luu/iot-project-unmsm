"""Plausibility evaluation for experiment E1 (T061; SC-001, research R-004).

There is no reference meter, so this is a plausibility check, not an accuracy
figure (plan > Calibration and plausibility procedure, step 7):

- bulb on: V_RMS within 10-16 V, every active power P > 0, and
  d_P = (P_m - P_n) / P_n x 100 within ±20 %, where P_m is the mean active power
  of the admissible bulb-on windows and P_n the nameplate rating;
- bulb off: every current within the calibration's absolute noise limit;
- at least 5 min on (60 windows) and 1 min off (12 windows) of admissible windows.

A window is admissible when its quality is `valid`, or `degraded` with
`calibration_missing` as the only flag. Everything else is excluded and counted
by flag.

Input: the exported 5 s summaries as CSV (`window_end`, `load_state` on/off as
labelled by the operator, `quality_state`, `quality_flags` separated by `;`,
`voltage_rms`, `current_rms`, `active_power`) and a nameplate CSV (`load_id`,
`nameplate_power_W`). Output in `--out`: `e1-<run>.csv`, `e1-<run>.md`, and
`e1-<run>.manifest.json` with SHA-256 hashes of inputs, script, and outputs.
Exit status 0 when every check passes, 1 otherwise.

Standard library only:
    python experiments/evaluation/plausibility.py --summaries S.csv \
        --nameplate N.csv --load-id bulb-12v-20w --noise-limit-a 0.05 \
        --run-id 2026-11-30-a --out experiments/data/e1
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

V_MIN_V = 10.0
V_MAX_V = 16.0
D_P_LIMIT_PCT = 20.0
WINDOW_S = 5
MIN_ON_WINDOWS = 5 * 60 // WINDOW_S
MIN_OFF_WINDOWS = 60 // WINDOW_S
ADMISSIBLE_FLAGS = frozenset({"calibration_missing"})

CHECKS = (
    ("enough_windows", f">= {MIN_ON_WINDOWS} on and >= {MIN_OFF_WINDOWS} off admissible windows"),
    ("voltage_in_range", f"every on-window V_RMS in {V_MIN_V:g}-{V_MAX_V:g} V"),
    ("power_positive", "every on-window P > 0"),
    ("power_within_20pct", f"|d_P| <= {D_P_LIMIT_PCT:g} %"),
    ("off_current_at_noise_limit", "every off-window I_RMS <= noise limit"),
)


@dataclass(frozen=True)
class Window:
    window_end: str
    load_state: str
    quality_state: str
    quality_flags: tuple[str, ...]
    voltage_rms: float | None
    current_rms: float | None
    active_power: float | None


@dataclass
class E1Result:
    n_on: int = 0
    n_off: int = 0
    n_on_admissible: int = 0
    n_off_admissible: int = 0
    excluded: dict[str, int] = field(default_factory=dict)
    v_min_v: float | None = None
    v_max_v: float | None = None
    p_min_w: float | None = None
    p_mean_w: float | None = None
    d_p_pct: float | None = None
    i_off_max_a: float | None = None
    checks: dict[str, bool] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return bool(self.checks) and all(self.checks.values())


def _num(text: str) -> float | None:
    text = text.strip()
    return float(text) if text else None


def load_summaries(path: Path) -> list[Window]:
    with path.open(newline="") as f:
        return [
            Window(
                window_end=row["window_end"],
                load_state=row["load_state"].strip().lower(),
                quality_state=row["quality_state"].strip(),
                quality_flags=tuple(x for x in row["quality_flags"].split(";") if x),
                voltage_rms=_num(row["voltage_rms"]),
                current_rms=_num(row["current_rms"]),
                active_power=_num(row["active_power"]),
            )
            for row in csv.DictReader(f)
        ]


def load_nameplate(path: Path, load_id: str) -> float:
    with path.open(newline="") as f:
        for row in csv.DictReader(f):
            if row["load_id"] == load_id:
                return float(row["nameplate_power_W"])
    raise KeyError(f"load {load_id!r} not in {path}")


def admissible(w: Window) -> bool:
    if w.quality_state == "valid":
        return not w.quality_flags
    return w.quality_state == "degraded" and set(w.quality_flags) <= ADMISSIBLE_FLAGS


def _exclusion_reason(w: Window) -> str:
    other = [f for f in w.quality_flags if f not in ADMISSIBLE_FLAGS]
    return other[0] if other else w.quality_state


def evaluate(windows: list[Window], *, nameplate_w: float, noise_limit_a: float) -> E1Result:
    r = E1Result()
    on = [w for w in windows if w.load_state == "on"]
    off = [w for w in windows if w.load_state == "off"]
    r.n_on, r.n_off = len(on), len(off)
    excluded: Counter[str] = Counter()
    for w in on + off:
        if not admissible(w):
            excluded[_exclusion_reason(w)] += 1
    r.excluded = dict(excluded)

    on_ok = [w for w in on if admissible(w)]
    off_ok = [w for w in off if admissible(w)]
    r.n_on_admissible, r.n_off_admissible = len(on_ok), len(off_ok)

    volts = [w.voltage_rms for w in on_ok if w.voltage_rms is not None]
    powers = [w.active_power for w in on_ok if w.active_power is not None]
    currents = [w.current_rms for w in off_ok if w.current_rms is not None]
    if volts:
        r.v_min_v, r.v_max_v = min(volts), max(volts)
    if powers:
        r.p_min_w = min(powers)
        r.p_mean_w = sum(powers) / len(powers)
        r.d_p_pct = (r.p_mean_w - nameplate_w) / nameplate_w * 100.0
    if currents:
        r.i_off_max_a = max(currents)

    tol = 1e-9  # the ±20 % and noise boundaries are inside
    r.checks = {
        "enough_windows": len(on_ok) >= MIN_ON_WINDOWS and len(off_ok) >= MIN_OFF_WINDOWS,
        "voltage_in_range": bool(volts) and min(volts) >= V_MIN_V and max(volts) <= V_MAX_V,
        "power_positive": bool(powers) and min(powers) > 0,
        "power_within_20pct": r.d_p_pct is not None and abs(r.d_p_pct) <= D_P_LIMIT_PCT + tol,
        "off_current_at_noise_limit": bool(currents) and max(currents) <= noise_limit_a + tol,
    }
    return r


def _fmt(x: float | None, digits: int = 3) -> str:
    return "" if x is None else f"{x:.{digits}f}"


def _observed(r: E1Result) -> dict[str, str]:
    return {
        "enough_windows": f"on {r.n_on_admissible}/{r.n_on}, off {r.n_off_admissible}/{r.n_off}",
        "voltage_in_range": f"{_fmt(r.v_min_v)}-{_fmt(r.v_max_v)} V",
        "power_positive": f"min {_fmt(r.p_min_w)} W",
        "power_within_20pct": f"P_m {_fmt(r.p_mean_w)} W, d_P {_fmt(r.d_p_pct, 2)} %",
        "off_current_at_noise_limit": f"max {_fmt(r.i_off_max_a, 4)} A",
    }


def write_table(
    r: E1Result, run_id: str, out: Path, nameplate_w: float, noise: float
) -> tuple[Path, Path]:
    out.mkdir(parents=True, exist_ok=True)
    observed = _observed(r)
    csv_path = out / f"e1-{run_id}.csv"
    with csv_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["run_id", "check", "criterion", "observed", "result"])
        for name, criterion in CHECKS:
            w.writerow(
                [run_id, name, criterion, observed[name], "PASS" if r.checks[name] else "FAIL"]
            )
        w.writerow([run_id, "overall", "all checks", "", "PASS" if r.passed else "FAIL"])

    md_path = out / f"e1-{run_id}.md"
    lines = [
        f"# E1 plausibility, run {run_id}",
        "",
        "Plausibility check only: no reference instrument was used, so no accuracy is claimed.",
        f"Nameplate {nameplate_w:g} W; noise limit {noise:g} A; values are not validated.",
        "",
        "| Check | Criterion | Observed | Result |",
        "|---|---|---|---|",
        *(
            f"| {name} | {criterion} | {observed[name]} | {'PASS' if r.checks[name] else 'FAIL'} |"
            for name, criterion in CHECKS
        ),
        f"| overall | all checks | | {'PASS' if r.passed else 'FAIL'} |",
        "",
        "Excluded windows by flag: "
        + (", ".join(f"{k} {v}" for k, v in sorted(r.excluded.items())) or "none"),
        "",
    ]
    md_path.write_text("\n".join(lines))
    return csv_path, md_path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_manifest(
    run_id: str, out: Path, files: dict[str, Path], params: dict[str, object]
) -> Path:
    manifest = {
        "experiment": "E1",
        "run_id": run_id,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "python": platform.python_version(),
        "parameters": params,
        "files": [
            {"role": role, "path": str(p.resolve()), "sha256": _sha256(p)}
            for role, p in files.items()
        ],
    }
    path = out / f"e1-{run_id}.manifest.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n")
    return path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--summaries", type=Path, required=True)
    ap.add_argument("--nameplate", type=Path, required=True)
    ap.add_argument("--load-id", required=True)
    ap.add_argument("--noise-limit-a", type=float, required=True,
                    help="zero_noise_current_A of the frozen calibration revision")  # fmt: skip
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)

    nameplate = load_nameplate(a.nameplate, a.load_id)
    result = evaluate(
        load_summaries(a.summaries), nameplate_w=nameplate, noise_limit_a=a.noise_limit_a
    )
    csv_path, md_path = write_table(result, a.run_id, a.out, nameplate, a.noise_limit_a)
    write_manifest(
        a.run_id,
        a.out,
        {
            "summaries": a.summaries,
            "nameplate": a.nameplate,
            "script": Path(__file__),
            "table_csv": csv_path,
            "table_md": md_path,
        },
        {"load_id": a.load_id, "nameplate_power_w": nameplate, "noise_limit_a": a.noise_limit_a},
    )
    print(md_path.read_text())
    return 0 if result.passed else 1


if __name__ == "__main__":
    sys.exit(main())
