"""T100: Hypothesis properties of the ingest path.

- Ledger idempotency: under any delivery order, any number of redeliveries, and
  storage failures, every contract-valid message is stored at most once, exactly
  once if any delivery succeeded, and each application ACK agrees with the ledger.
- Energy never decreases within a `counter_id` in what is stored, whatever the
  arrival order (outage replay, swaps, duplicates).
- Contract round trips: a valid measurement survives model parse and dump, and
  the dump still validates against the normative schema.
"""

import copy
import json
import re
import shutil
import tempfile
from datetime import UTC, datetime, timedelta
from functools import cache
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from energy_ingestion.cli.simulate import SCENARIOS, Message, SimulatedNode
from energy_ingestion.contracts.models import Measurement
from energy_ingestion.contracts.validate import contracts_dir, validate_payload
from energy_ingestion.mqtt.pipeline import IngestPipeline
from energy_ingestion.persistence.db import make_engine, make_session_factory
from tests.conftest import alembic_config
from tests.fakes import FakeClock, FakePublisher, FakeWriter

pytestmark = pytest.mark.unit
START = datetime(2026, 10, 14, 17, 0, 0, tzinfo=UTC)
PROPS = settings(max_examples=30, deadline=None, suppress_health_check=[HealthCheck.too_slow])
_FIELD = re.compile(r'(?:^|[ ,])(\w+)=("(?:[^"\\]|\\.)*"|[^, ]+)')


@cache
def _template_db() -> Path:
    """A migrated database built once; each example works on a copy."""
    path = Path(tempfile.mkdtemp(prefix="energy-props-")) / "template.sqlite"
    command.upgrade(alembic_config(f"sqlite:///{path}"), "head")
    return path


def _pipeline(tmp: Path) -> tuple[IngestPipeline, FakeWriter, FakePublisher]:
    db = tmp / "energy.sqlite"
    shutil.copy(_template_db(), db)
    sessions = make_session_factory(make_engine(f"sqlite:///{db}"))
    writer, pub = FakeWriter(), FakePublisher()
    return IngestPipeline(sessions, writer, pub, clock=FakeClock()), writer, pub


def _fields(line: str) -> dict[str, str]:
    _, _, rest = line.partition(" ")
    body, _, ts = rest.rpartition(" ")
    out = {k: v.strip('"') for k, v in _FIELD.findall(body)}
    out["_time"] = ts
    return out


def _measurements(scenario: str, seed: int, minutes: int) -> list[Message]:
    node = SimulatedNode(scenario, START, seed=seed)
    return [m for m in node.messages(timedelta(minutes=minutes)) if m.kind == "measurement"]


# ---- ledger idempotency ----------------------------------------------------------


@PROPS
@given(
    scenario=st.sampled_from(SCENARIOS),
    seed=st.integers(0, 2**16),
    data=st.data(),
)
def test_each_message_is_stored_at_most_once(scenario: str, seed: int, data: Any) -> None:
    msgs = _measurements(scenario, seed, minutes=2)
    deliveries = data.draw(
        st.lists(
            st.tuples(st.integers(0, len(msgs) - 1), st.booleans()),
            min_size=1,
            max_size=3 * len(msgs),
        )
    )
    with tempfile.TemporaryDirectory() as tmp:
        pipe, writer, pub = _pipeline(Path(tmp))
        succeeded: set[str] = set()
        for index, storage_down in deliveries:
            msg = msgs[index]
            writer.fail = storage_down
            mid = json.loads(msg.payload)["message_id"]
            try:
                pipe.handle(msg.topic, msg.payload)
            except ConnectionError:
                assert msg.contract_valid  # only the storage path can fail
                continue
            if msg.contract_valid:
                succeeded.add(mid)

        writer.fail = False
        stored = [
            _fields(x)["message_id"] for x in writer.lines("energy_raw", "electrical_measurement")
        ]
        assert sorted(stored) == sorted(succeeded)  # exactly once per successful message

        statuses: dict[str, list[str]] = {}
        for _, payload, _, _ in pub.sent:
            ack = json.loads(payload)
            statuses.setdefault(ack["message_id"], []).append(ack["status"])
        for mid, seen in statuses.items():
            if mid in succeeded:
                assert seen[0] == "accepted"
                assert set(seen[1:]) <= {"duplicate"}
            else:
                assert set(seen) == {"rejected"}


# ---- energy never decreases within a counter_id ----------------------------------


@PROPS
@given(
    scenario=st.sampled_from(SCENARIOS),
    seed=st.integers(0, 2**16),
    order=st.randoms(use_true_random=False),
)
def test_stored_energy_never_decreases_within_a_counter(
    scenario: str, seed: int, order: Any
) -> None:
    msgs = _measurements(scenario, seed, minutes=3)
    order.shuffle(msgs)
    with tempfile.TemporaryDirectory() as tmp:
        pipe, writer, _ = _pipeline(Path(tmp))
        for msg in msgs:
            pipe.handle(msg.topic, msg.payload)
        series: dict[str, list[tuple[int, float]]] = {}
        for line in writer.lines("energy_raw", "electrical_measurement"):
            f = _fields(line)
            if "active_energy_import_total_Wh" in f:  # absent for invalid windows
                series.setdefault(f["counter_id"], []).append(
                    (int(f["_time"]), float(f["active_energy_import_total_Wh"]))
                )
        for points in series.values():
            energies = [e for _, e in sorted(points)]
            assert energies == sorted(energies)


# ---- contract round trips --------------------------------------------------------

VALID = json.loads((contracts_dir() / "examples" / "valid-measurement.json").read_text())
finite = {"allow_nan": False, "allow_infinity": False}


@PROPS
@given(
    voltage=st.floats(0, 300, **finite),
    current=st.floats(0, 20, **finite),
    power=st.floats(-3000, 3000, **finite),
    energy=st.floats(0, 1e9, **finite),
    sequence=st.integers(0, 2**53 - 1),
    ratio=st.floats(0.99, 1, **finite),
    sync_age=st.one_of(st.none(), st.integers(0, 10**6)),
)
def test_measurement_round_trip(
    voltage: float,
    current: float,
    power: float,
    energy: float,
    sequence: int,
    ratio: float,
    sync_age: int | None,
) -> None:
    doc = copy.deepcopy(VALID)
    m = doc["measurements"]
    m["voltage_rms"]["value"] = voltage
    m["current_rms"]["value"] = current
    m["active_power"]["value"] = power
    m["active_energy_import_total"]["value"] = energy
    doc["sequence"] = sequence
    doc["quality"]["valid_sample_ratio"] = ratio
    doc["clock"]["last_sync_age_s"] = sync_age
    raw = json.dumps(doc).encode()
    parsed = Measurement.model_validate(validate_payload("measurement", raw))
    dumped = json.dumps(parsed.model_dump(mode="json", by_alias=True)).encode()
    again = Measurement.model_validate(validate_payload("measurement", dumped))
    assert again == parsed
    assert again.measurements.active_power.value == power


@PROPS
@given(scenario=st.sampled_from(SCENARIOS), seed=st.integers(0, 2**16))
def test_simulator_output_round_trips(scenario: str, seed: int) -> None:
    for msg in SimulatedNode(scenario, START, seed=seed).messages(timedelta(minutes=1)):
        if not msg.contract_valid:
            continue
        doc = validate_payload(msg.kind, msg.payload)
        if msg.kind == "measurement":
            dumped = Measurement.model_validate(doc).model_dump(mode="json", by_alias=True)
            validate_payload("measurement", json.dumps(dumped).encode())
