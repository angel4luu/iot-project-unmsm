"""T040: a crash between the InfluxDB write and ledger `stored` repeats the write on recovery.

Runs inside the ingestion container against the real InfluxDB, with a scratch
SQLite ledger in /tmp so the service's own registry is untouched. Step 1 hard-
kills the process (`os._exit`) right after the Influx write, before `stored`.
Step 2, a new process on the same ledger, receives the redelivery: the ledger
row is still `received`, so the pipeline repeats the idempotent write (same
series and timestamp), marks it stored, and ACKs `accepted`. InfluxDB then
holds exactly one point for the message.
"""

import json
import secrets
import subprocess
from datetime import UTC, datetime, timedelta

import pytest
from tests import stack

from energy_ingestion.cli.simulate import SimulatedNode

pytestmark = pytest.mark.integration

PROBE = r"""
import json, os, sys
from alembic import command
from alembic.config import Config
from energy_ingestion.mqtt.pipeline import IngestPipeline
from energy_ingestion.persistence import ledger
from energy_ingestion.persistence.db import make_engine, make_session_factory
from energy_ingestion.persistence.influx import InfluxWriter

mode, db, topic = sys.argv[1], sys.argv[2], sys.argv[3]
payload = sys.stdin.buffer.read()
url = f"sqlite:///{db}"
cfg = Config("/app/services/ingestion/alembic.ini")
cfg.set_main_option("sqlalchemy.url", url)
command.upgrade(cfg, "head")
sent = []
pipe = IngestPipeline(make_session_factory(make_engine(url)), InfluxWriter.from_env(),
                      lambda t, p, q, r: sent.append(json.loads(p)))
if mode == "crash":
    def die(*_a, **_k):
        os._exit(3)  # the process dies after the Influx write, before `stored`
    ledger.mark_stored = die
outcome = pipe.handle(topic, payload)
print(json.dumps({"result": outcome.result, "acks": sent}))
"""


def probe(mode: str, db: str, topic: str, payload: bytes) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["docker", "exec", "-i", stack.INGESTION, "python", "-c", PROBE, mode, db, topic],
        input=payload,
        capture_output=True,
        check=False,
    )


def points_for(node: str, message_id: str) -> int:
    rows = stack.flux(
        'from(bucket: "energy_raw") |> range(start: -1h)'
        f' |> filter(fn: (r) => r._measurement == "electrical_measurement"'
        f' and r.node_id == "{node}" and r._field == "message_id" and r._value == "{message_id}")'
    )
    return len(rows)


def test_crash_after_influx_write_is_resumed_exactly_once() -> None:
    stack.require_stack()
    node_id = f"crash-{secrets.token_hex(3)}"
    sim = SimulatedNode(
        "normal",
        datetime.now(UTC) - timedelta(seconds=10),
        node_id=node_id,
        seed=secrets.randbits(32),
    )
    msg = next(m for m in sim.messages(timedelta(seconds=5)) if m.kind == "measurement")
    message_id = json.loads(msg.payload)["message_id"]
    db = f"/tmp/crash-{secrets.token_hex(4)}.sqlite"

    crashed = probe("crash", db, msg.topic, msg.payload)
    assert crashed.returncode == 3, crashed.stderr.decode()[-500:]
    assert crashed.stdout == b""  # no ACK was published before the crash
    assert points_for(node_id, message_id) == 1  # the write happened

    resumed = probe("resume", db, msg.topic, msg.payload)
    assert resumed.returncode == 0, resumed.stderr.decode()[-500:]
    out = json.loads(resumed.stdout)
    assert out["result"] == "accepted"
    assert [a["status"] for a in out["acks"]] == ["accepted"]
    assert points_for(node_id, message_id) == 1  # repeated write, same point

    retry = json.loads(probe("resume", db, msg.topic, msg.payload).stdout)
    assert retry["result"] == "duplicate"
    assert points_for(node_id, message_id) == 1
    subprocess.run(
        ["docker", "exec", stack.INGESTION, "rm", "-f", db, f"{db}-wal", f"{db}-shm"], check=False
    )
