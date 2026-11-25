"""T094: calibration registry through `energyctl`, and the "not validated" label end to end.

Runs against the live stack (`make infra-up`). It registers `sim-001` and a new,
uniquely named nominal calibration revision in the stack's registry; revisions
are immutable, so each run adds one (harmless on the development stack).
"""

import json
import secrets
import subprocess
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from tests import stack

from energy_ingestion.cli.simulate import SimulatedNode

pytestmark = pytest.mark.integration
NODE = "sim-001"


@pytest.fixture(scope="module", autouse=True)
def _stack() -> None:
    stack.require_stack()
    r = stack.energyctl(
        "node", "register", "--node-id", NODE, "--display-name", "Simulator",
        "--hardware-revision", "simulator", "--circuit-id", "sim-load-001",
    )  # fmt: skip
    assert r.returncode == 0 or "already exists" in r.stderr, r.stderr


def register(revision: str) -> dict[str, Any]:
    doc = {
        "calibration_revision": revision,
        "node_id": NODE,
        "hardware_revision": "simulator",
        "firmware_commit": "0" * 40,
        "calibration_kind": "nominal",
        "current_sensor_variant": "20A",
        "voltage_gain": 22.276596,
        "current_gain": 14.7,
        "phase_correction_samples": 0.5,
        "zero_noise_current_a": 0.05,
        "procedure_version": "nominal-calibration-v1",
        "dataset_manifest_sha256": "0" * 64,
    }
    r = subprocess.run(
        [
            "docker",
            "exec",
            "-i",
            stack.INGESTION,
            "energyctl",
            "calibration",
            "register",
            "/dev/stdin",
        ],
        input=json.dumps(doc),  # JSON is YAML
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    out: dict[str, Any] = json.loads(r.stdout)
    return out


def send_window(link: stack.SimLink, revision: str) -> str:
    node = SimulatedNode(
        "normal", datetime.now(UTC) - timedelta(seconds=10), node_id=NODE, seed=secrets.randbits(32)
    )
    msg = next(m for m in node.messages(timedelta(seconds=5)) if m.kind == "measurement")
    doc = json.loads(msg.payload)
    doc["quality"]["calibration_revision"] = revision
    link.publish(msg.topic, json.dumps(doc).encode())
    ack = link.wait_ack(doc["message_id"])
    assert ack is not None, "no application ACK"
    assert ack["status"] == "accepted", ack
    return str(doc["message_id"])


def stored(message_id: str) -> dict[str, str]:
    rows = stack.flux(
        'from(bucket: "energy_raw") |> range(start: -1h)'
        ' |> filter(fn: (r) => r._measurement == "electrical_measurement")'
        f' |> filter(fn: (r) => r.node_id == "{NODE}")'
        ' |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")'
        f' |> filter(fn: (r) => r.message_id == "{message_id}")'
    )
    assert len(rows) == 1, f"expected exactly one stored window, got {len(rows)}"
    return rows[0]


def test_registered_nominal_calibration_is_not_validated_before_and_after_acceptance() -> None:
    revision = f"cal-{NODE}-it-{secrets.token_hex(4)}"
    assert register(revision)["kind"] == "nominal"
    with stack.sim_link() as link:
        before = stored(send_window(link, revision))
        r = stack.energyctl("calibration", "accept", revision, "--by", "operator A")
        assert r.returncode == 0, r.stderr
        assert json.loads(r.stdout)["validation"] == "not_validated"
        after = stored(send_window(link, revision))
    for row in (before, after):
        assert row["calibration_revision"] == revision
        assert row["validation"] == "not_validated"


def test_unknown_calibration_revision_is_not_validated() -> None:
    with stack.sim_link() as link:
        row = stored(send_window(link, f"cal-unregistered-{secrets.token_hex(4)}"))
    assert row["validation"] == "not_validated"


def test_registry_lists_the_revision_and_refuses_reuse() -> None:
    revision = f"cal-{NODE}-it-{secrets.token_hex(4)}"
    register(revision)
    listed = [
        json.loads(x)
        for x in stack.energyctl("calibration", "list", "--node", NODE).stdout.splitlines()
    ]
    assert revision in {row["calibration_revision"] for row in listed}
    again = subprocess.run(
        [
            "docker",
            "exec",
            "-i",
            stack.INGESTION,
            "energyctl",
            "calibration",
            "register",
            "/dev/stdin",
        ],
        input=json.dumps({"calibration_revision": revision}),
        capture_output=True,
        text=True,
        check=False,
    )
    assert again.returncode == 2


def test_dashboard_banner_is_unconditional() -> None:
    dash = stack.grafana("/api/dashboards/uid/energy-overview")["dashboard"]
    banner = next(p for p in dash["panels"] if p["id"] == 1)
    assert "NOT VALIDATED" in banner["title"]
    assert "nominal calibration" in banner["title"]
