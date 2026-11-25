"""T066: golden-query tests for the history queries (T071) against the live stack.

Hand-built counter readings for a fresh node are written straight into
`energy_raw`, then `dashboards/queries/{hourly,daily,weekly,peak_hour}.flux` run
over them and must return the answers worked out below. The data exercises:

- energy from counter DIFFERENCES, never by summing cumulative totals;
- a difference belongs to the period containing (window end - 1 ms);
- invalid and degraded windows excluded (a degraded reading would add a huge step);
- a counter reset through a new `counter_id` (its first reading adds nothing) and a
  negative step inside one counter (dropped, never subtracted);
- America/Lima day boundaries (UTC-5) and Monday-start weeks: the day D is a
  Sunday, so D and D+1 fall in different Lima days AND different weeks, and a
  UTC-day query would move the 23:00-24:00 Lima energy to the next day.

Contract with the query files (Codex handoff, T071): template variables are only
`v.timeRangeStart`, `v.timeRangeStop`, and `"${node}"`; one yield per file named
`hourly_energy_Wh`, `daily_energy_Wh`, `weekly_energy_Wh`, `peak_hour`; `_time`
is the period start; periods without differences are omitted.
"""

from __future__ import annotations

import os
import secrets
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from tests import stack

pytestmark = pytest.mark.integration
QUERIES = Path(__file__).resolve().parents[2] / "dashboards" / "queries"
LIMA = timedelta(hours=-5)  # America/Lima, no DST


def last_sunday_lima(now: datetime) -> datetime:
    """Midnight (Lima) of the latest Sunday that ended at least a day ago, in UTC."""
    local = (now + LIMA).replace(hour=0, minute=0, second=0, microsecond=0)
    day = local - timedelta(days=2)
    while day.weekday() != 6:  # Sunday
        day -= timedelta(days=1)
    return (day - LIMA).replace(tzinfo=UTC)


D = last_sunday_lima(datetime.now(UTC).replace(tzinfo=None))


def at(day: int, hh: int, mm: int = 0) -> datetime:
    return D + timedelta(days=day, hours=hh, minutes=mm)


# (time, quality, counter_id, cumulative Wh or None for an invalid window)
READINGS = [
    (at(0, 9, 0), "valid", "c1", 100.0),  # first in range: contributes nothing
    (at(0, 9, 30), "valid", "c1", 105.0),  # +5 -> 09:00
    (at(0, 10, 0), "valid", "c1", 110.0),  # +5 -> 09:00 (ends exactly on the hour)
    (at(0, 10, 30), "valid", "c1", 118.0),  # +8 -> 10:00
    (at(0, 10, 40), "invalid", "c1", None),  # excluded
    (at(0, 10, 45), "degraded", "c1", 500.0),  # excluded (would add +382)
    (at(0, 11, 0), "valid", "c2", 0.0),  # counter reset: new series, nothing
    (at(0, 11, 30), "valid", "c2", 3.0),  # +3 -> 11:00
    (at(0, 12, 0), "valid", "c2", 6.0),  # +3 -> 11:00
    (at(0, 12, 30), "valid", "c2", 5.0),  # -1 dropped
    (at(0, 12, 45), "valid", "c2", 9.0),  # +4 -> 12:00
    (at(0, 23, 30), "valid", "c2", 10.0),  # +1 -> 23:00
    (at(1, 0, 0), "valid", "c2", 12.0),  # +2 -> 23:00 of D (Lima midnight - 1 ms)
    (at(1, 0, 30), "valid", "c2", 17.0),  # +5 -> 00:00 of D+1 (Monday)
]
HOURLY = {at(0, 9): 10.0, at(0, 10): 8.0, at(0, 11): 6.0, at(0, 12): 4.0, at(0, 23): 3.0,
          at(1, 0): 5.0}  # fmt: skip
DAILY = {at(0, 0): 31.0, at(1, 0): 5.0}
WEEKLY = {at(-6, 0): 31.0, at(1, 0): 5.0}  # Monday D-6 .. Sunday D; Monday D+1
# Flux clips a period's start to the query range: the first week may start at D.
WEEKLY_CLIPPED = {at(0, 0): 31.0, at(1, 0): 5.0}
PEAK = (at(0, 9), 10.0)


def _line(node: str, t: datetime, quality: str, counter: str, wh: float | None) -> str:
    tags = f"node_id={node},circuit_id=golden-load,quality={quality},calibration_revision=golden-r1"
    fields = f'counter_id="{counter}",sequence={int(t.timestamp())}i'
    if wh is not None:
        fields += f",active_energy_import_total_Wh={wh}"
    return f"electrical_measurement,{tags} {fields} {int(t.timestamp() * 1000)}"


def write_points(lines: list[str]) -> None:
    token = (stack.SECRETS / "influx-admin-token").read_text(encoding="utf-8").strip()
    r = subprocess.run(
        [
            "docker",
            "exec",
            "-i",
            "-e",
            "INFLUX_TOKEN",
            stack.INFLUXDB,
            "influx",
            "write",
            "--org",
            stack.ORG,
            "--bucket",
            "energy_raw",
            "--precision",
            "ms",
        ],
        input="\n".join(lines) + "\n",
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "INFLUX_TOKEN": token},
    )
    assert r.returncode == 0, r.stderr[:300]


@pytest.fixture(scope="module")
def node() -> str:
    stack.require_stack()
    name = f"golden-{secrets.token_hex(4)}"  # fresh series on every run
    write_points([_line(name, *r) for r in READINGS])
    return name


def run_query(name: str, node: str) -> list[dict[str, str]]:
    text = (QUERIES / f"{name}.flux").read_text(encoding="utf-8")
    text = (
        text.replace("v.timeRangeStart", at(0, 0).strftime("%Y-%m-%dT%H:%M:%SZ"))
        .replace("v.timeRangeStop", at(2, 0).strftime("%Y-%m-%dT%H:%M:%SZ"))
        .replace("${node}", node)
    )
    return stack.flux(text)


def as_map(rows: list[dict[str, str]], yield_name: str) -> dict[datetime, float]:
    out: dict[datetime, float] = {}
    for r in rows:
        assert r["result"] == yield_name, r
        t = datetime.fromisoformat(r["_time"].replace("Z", "+00:00"))
        assert t not in out, f"two rows for {t}: tables not merged"
        out[t] = float(r["_value"])
    return out


@pytest.mark.parametrize(
    ("name", "expected"),
    [("hourly", HOURLY), ("daily", DAILY), ("weekly", WEEKLY)],
)
def test_energy_per_period(node: str, name: str, expected: dict[datetime, float]) -> None:
    got = as_map(run_query(name, node), f"{name}_energy_Wh")
    if name == "weekly" and got.keys() == WEEKLY_CLIPPED.keys():
        expected = WEEKLY_CLIPPED
    assert got.keys() == expected.keys(), sorted(got)
    for t, wh in expected.items():
        assert got[t] == pytest.approx(wh, abs=1e-9), t


def test_peak_hour(node: str) -> None:
    rows = run_query("peak_hour", node)
    (t, wh), *rest = as_map(rows, "peak_hour").items()
    assert rest == []
    assert (t, wh) == (PEAK[0], pytest.approx(PEAK[1]))


def test_peak_hour_tie_goes_to_the_earliest_hour(node: str) -> None:
    """A second node with two equal hours: 13:00 and 15:00 both get 7 Wh."""
    tie = f"{node}-tie"
    write_points(
        [
            _line(tie, at(0, 13, 0), "valid", "t1", 0.0),
            _line(tie, at(0, 13, 30), "valid", "t1", 7.0),
            _line(tie, at(0, 15, 0), "valid", "t1", 7.0),
            _line(tie, at(0, 15, 30), "valid", "t1", 14.0),
        ]
    )
    rows = run_query("peak_hour", tie)
    assert as_map(rows, "peak_hour") == {at(0, 13): pytest.approx(7.0)}
