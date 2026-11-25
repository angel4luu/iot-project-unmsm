"""Generate the synthetic waveform fixtures (T033).

Each fixture is one second of the plan B loop as the ESP32-S3 would see it after
Espressif's ADC calibration: alternating voltage/current conversions at 8,000/s
(4,000 pairs/s), current sampled one conversion (125 us) after voltage, values in
integer millivolts at the ADC pins, deterministic noise. The physical truth used
to make each file is written into its header so reference.py can be checked
against it.

    python tests/fixtures/waveforms/generate.py          # write the CSVs
    python tests/fixtures/waveforms/generate.py --check  # verify they are current

Standard library only, so the files can be regenerated anywhere.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
FRONTEND = json.loads((HERE / "frontend.json").read_text(encoding="utf-8"))
DURATION_S = 1.0
FREQUENCY_HZ = 60.0  # Peru mains frequency, passed through by the AC adapter
NOISE_MV = 1.0


@dataclass(frozen=True)
class Spec:
    name: str
    description: str
    v_rms: float  # physical truth at the adapter output, V
    i_rms: float  # physical truth in the loop, A
    lag_deg: float = 0.0  # current lag behind voltage
    v_offset_mv: float = 0.0  # bias drift on the voltage pin
    i_offset_mv: float = 0.0  # ACS712 zero drift on the current pin
    gaps: tuple[tuple[int, int], ...] = ()  # missing pair index ranges [start, stop)
    seed: int = 1
    expected_flags: tuple[str, ...] = field(default=())


SPECS = (
    Spec("sine_inphase", "Bulb on: 12 V RMS, 1.7 A RMS, in phase (resistive)", 12.0, 1.7),
    Spec("lag60", "Current lags voltage by 60 degrees", 12.0, 1.7, lag_deg=60.0, seed=2),
    Spec(
        "dc_offset",
        "Bulb on with +40 mV bias drift on V and -25 mV ACS712 zero drift on I",
        12.0,
        1.7,
        v_offset_mv=40.0,
        i_offset_mv=-25.0,
        seed=3,
    ),
    Spec(
        "clipping",
        "Voltage overdrive (40 V RMS) drives GPIO4 past both ADC rails",
        40.0,
        1.7,
        seed=4,
        expected_flags=("adc_clipped",),
    ),
    Spec(
        "sample_gap",
        "Bulb on with 200 pairs (50 ms) missing after a DMA overrun",
        12.0,
        1.7,
        gaps=((1800, 2000),),
        seed=5,
        expected_flags=("sample_gap",),
    ),
    Spec(
        "no_current", "Bulb off: 12 V RMS, no loop current (sensor noise only)", 12.0, 0.0, seed=6
    ),
)


def voltage_gain_mv_per_v() -> float:
    v = FRONTEND["voltage"]
    return 1000.0 * v["r2_ohm"] / (v["r1_ohm"] + v["r2_ohm"])


def current_gain_mv_per_a() -> float:
    c = FRONTEND["current"]
    return c["sensitivity_mv_per_a"] * c["r4_ohm"] / (c["r3_ohm"] + c["r4_ohm"])


def current_zero_mv() -> float:
    c = FRONTEND["current"]
    return c["zero_mv"] * c["r4_ohm"] / (c["r3_ohm"] + c["r4_ohm"])


def _adc(mv: float) -> int:
    return round(min(max(mv, FRONTEND["adc_min_mv"]), FRONTEND["adc_max_mv"]))


def render(spec: Spec) -> str:
    rng = random.Random(spec.seed)  # deterministic test noise
    pairs = int(DURATION_S * FRONTEND["pairs_per_s"])
    t_pair = 1.0 / FRONTEND["pairs_per_s"]
    t_conv = 1.0 / FRONTEND["conversions_per_s"]
    w = 2 * math.pi * FREQUENCY_HZ
    lag = math.radians(spec.lag_deg)
    gv, gi, zi = voltage_gain_mv_per_v(), current_gain_mv_per_a(), current_zero_mv()
    bias = FRONTEND["voltage"]["bias_mv"]
    missing = {k for a, b in spec.gaps for k in range(a, b)}
    header = {
        **asdict(spec),
        "duration_s": DURATION_S,
        "frequency_hz": FREQUENCY_HZ,
        "noise_mv": NOISE_MV,
        "pairs": pairs - len(missing),
    }
    lines = [f"# {json.dumps(header, sort_keys=True)}", "pair,v_mv,i_mv"]
    for k in range(pairs):
        tv = k * t_pair
        ti = tv + FRONTEND["current_delay_conversions"] * t_conv
        v = spec.v_rms * math.sqrt(2) * math.sin(w * tv)
        i = spec.i_rms * math.sqrt(2) * math.sin(w * ti - lag)
        v_mv = bias + spec.v_offset_mv + gv * v + rng.gauss(0, NOISE_MV)
        i_mv = zi + spec.i_offset_mv + gi * i + rng.gauss(0, NOISE_MV)
        if k not in missing:
            lines.append(f"{k},{_adc(v_mv)},{_adc(i_mv)}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--check", action="store_true", help="fail if a CSV is out of date")
    args = parser.parse_args(argv)
    stale = []
    for spec in SPECS:
        path = HERE / f"{spec.name}.csv"
        text = render(spec)
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != text:
                stale.append(path.name)
        else:
            path.write_text(text, encoding="utf-8")
    if stale:
        print("out of date: " + ", ".join(stale), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
