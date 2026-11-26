"""T080: simulated alert acceptance of user story 3 (SC-004, scenarios 1-3).

Runs the simulator's `alerts` scenario in real time through the live stack:
`US3_EPISODES` episodes (default 60: 20 sustained, 20 brief surges shorter than
`confirm_ms`, 20 below the limit), with the node's threshold config stored and
published by `energyctl threshold publish` first. The simulated node evaluates every
1 s block with the mirror of the firmware state machine and sends its events. Checks:

- every sustained episode opens exactly one `active_power_threshold` alert, which
  the node's later `threshold_cleared` resolves; surges and below-limit episodes
  open none; the cross-check raises no `pipeline_health` alert;
- local warning <= 2 s after confirmation, in simulated node timing (the block that
  confirms turns the warning on; the 500 ms display refresh is added);
- remote alert <= 10 s: from the node event's time to the webhook POST received by a
  local fake receiver (alert opened, outbox row delivered);
- with the ingestion service stopped, the local warning still fires, and the alert
  opens once the service is back (the broker kept the QoS 1 event);
- ntfy format (T109): one sustained episode reaches a local fake ntfy server as an
  ntfy JSON publish (server root, topic in the body, Spanish title, no bearer token)
  within 10 s of the node event.

Delivery: the lab stack runs with `NOTIFICATION_WEBHOOK_URL` empty, so the service's
own worker is disabled and no real endpoint is involved. The test starts the fake receiver and a
`NotificationWorker` loop (the same class the service runs) inside the ingestion
container, against the service's SQLite file, on 127.0.0.1. The token (or ntfy topic) is
a dummy test value written to the container's /tmp, never a real secret. Each test
stops its worker with a stop file, so a later test's alerts are not claimed by it.

Evidence JSON goes to the ignored `experiments/data/acceptance/`. Simulated values
are not measurements and are not validated.
"""

from __future__ import annotations

import json
import os
import secrets
import statistics
import subprocess
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from tests import stack

from energy_ingestion.cli.simulate import SimulatedNode

pytestmark = pytest.mark.integration
EPISODES = int(os.environ.get("US3_EPISODES", "60"))
CONFIRM_MS = 2000  # shortest practical episodes; the default 10 s is covered by unit tests
CLEAR_MS = 1000
LIMIT_W = 22.0
UI_REFRESH_S = 0.5  # firmware ui_task period
LOCAL_BOUND_S = 2.0
REMOTE_BOUND_S = 10.0
EVIDENCE = stack.REPO / "experiments" / "data" / "acceptance"
NODE, CIRCUIT = "sim-001", "sim-load-001"
HOOK_PORT = 18089
HOOK_LOG = "/tmp/us3-webhook.jsonl"
TOKEN_FILE = "/tmp/us3-dummy-token"
NTFY_PORT = 18090
NTFY_LOG = "/tmp/us3-ntfy.jsonl"
NTFY_TOPIC_FILE = "/tmp/us3-ntfy-topic"
REGISTER = (
    *("energyctl", "node", "register", "--node-id", NODE, "--display-name", "Simulator"),
    *("--hardware-revision", "simulator", "--circuit-id", CIRCUIT),
)

RECEIVER = r"""
import http.server, json, sys, threading, time
port, out, life = int(sys.argv[1]), sys.argv[2], float(sys.argv[3])
class H(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        rec = {"received_at": time.time(), "key": self.headers.get("Idempotency-Key"),
               "path": self.path, "bearer": "Authorization" in self.headers,
               "body": json.loads(body)}
        with open(out, "a") as f:
            f.write(json.dumps(rec) + "\n")
        self.send_response(200)
        self.end_headers()
    def log_message(self, *args):
        pass
srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), H)
threading.Timer(life, srv.shutdown).start()
srv.serve_forever()
"""

WORKER = r"""
import os, sys, time
from energy_ingestion.notifications.outbox import NotificationWorker, WebhookSender
from energy_ingestion.persistence.db import make_engine, make_session_factory
from energy_ingestion.persistence.influx import InfluxWriter
url, token, life, fmt, stop = sys.argv[1], sys.argv[2], float(sys.argv[3]), *sys.argv[4:6]
sender = WebhookSender.from_env({"NOTIFICATION_WEBHOOK_URL": url, "NOTIFICATION_TOKEN_FILE": token,
                                 "NOTIFICATION_FORMAT": fmt})
worker = NotificationWorker(make_session_factory(make_engine()), sender, InfluxWriter.from_env())
end = time.time() + life
while time.time() < end and not os.path.exists(stop):
    worker.run_once()
    time.sleep(0.5)
"""

QUERY = r"""
import json, sys
from sqlalchemy import select
from energy_ingestion.persistence.db import Alert, AlertTransition
from energy_ingestion.persistence.db import make_engine, make_session_factory
args = json.load(sys.stdin)
with make_session_factory(make_engine())() as s:
    rows = s.scalars(select(Alert).where(Alert.node_id == args["node"]))
    out = []
    for a in rows:
        if a.opened_at.timestamp() < args["since"]:
            continue
        ts = s.scalars(select(AlertTransition).where(AlertTransition.alert_id == a.alert_id))
        out.append({"alert_id": a.alert_id, "event_id": a.event_id, "kind": a.kind,
                    "status": a.status, "opened_at": a.opened_at.timestamp(),
                    "reasons": [t.reason for t in ts]})
print(json.dumps(out))
"""


def container(*args: str, stdin: str | None = None, detach: bool = False) -> str:
    cmd = ["docker", "exec", *(["-d"] if detach else []), *(["-i"] if stdin else [])]
    r = subprocess.run(
        [*cmd, stack.INGESTION, *args],
        input=stdin,
        capture_output=True,
        text=True,
        check=False,
    )
    if r.returncode != 0:
        raise RuntimeError(f"{args[:2]} failed: {r.stderr.strip()[:300]}")
    return r.stdout


def ensure_node_and_config(node: SimulatedNode) -> int:
    """Register the simulator node (once) and publish a newer threshold config."""
    try:
        container(*REGISTER)
    except RuntimeError as exc:
        if "already exists" not in str(exc):
            raise
    shown = subprocess.run(
        ["docker", "exec", stack.INGESTION, "energyctl", "threshold", "show", NODE],
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        current = int(json.loads(shown.stdout).get("config_version", 0))
    except ValueError, AttributeError:
        current = 0  # nothing stored yet
    node.config_version = current + 1
    doc = node.threshold_config(datetime.now(UTC))
    path = f"/tmp/us3-threshold-v{node.config_version}.json"
    container("sh", "-c", f"cat > {path}", stdin=json.dumps(doc))  # YAML is a superset of JSON
    container("energyctl", "threshold", "publish", path, "--by", "acceptance-us3")
    return node.config_version


def alerts_since(since: datetime) -> list[dict[str, Any]]:
    out = container(
        "python", "-c", QUERY, stdin=json.dumps({"node": NODE, "since": since.timestamp()})
    )
    result: list[dict[str, Any]] = json.loads(out)
    return result


def start_delivery(fmt: str, port: int, log: str, token_file: str, life: float) -> str:
    """Start a fake receiver and a worker in the container; return the worker's stop file."""
    configured = container("sh", "-c", 'test -n "$NOTIFICATION_WEBHOOK_URL" && echo set || true')
    if configured.strip() == "set":
        # The service's own worker would claim these alerts and send them for real.
        pytest.skip("service has NOTIFICATION_WEBHOOK_URL set; clear it for acceptance runs")
    stop = f"/tmp/us3-stop-{secrets.token_hex(4)}"
    container("python", "-c", RECEIVER, str(port), log, str(life), detach=True)
    url = f"http://127.0.0.1:{port}" + ("" if fmt == "ntfy" else "/hook")
    container("python", "-c", WORKER, url, token_file, str(life), fmt, stop, detach=True)
    return stop


def webhook_log(log: str = HOOK_LOG) -> list[dict[str, Any]]:
    out = container("sh", "-c", f"cat {log} 2>/dev/null || true")
    return [json.loads(line) for line in out.splitlines() if line.strip()]


def publish_realtime(node: SimulatedNode, duration: timedelta) -> list[dict[str, Any]]:
    """Publish the run in real time; return the node events sent, in order."""
    sent: list[dict[str, Any]] = []
    with stack.sim_link(NODE) as link:
        for msg in node.messages(duration):
            delay = (msg.at - datetime.now(UTC)).total_seconds()
            if delay > 0:
                time.sleep(delay)
            link.publish(msg.topic, msg.payload, retain=msg.retain)
            if msg.kind == "node-event":
                sent.append(json.loads(msg.payload))
    return sent


def local_latencies(node: SimulatedNode) -> list[float]:
    """Confirmation instant to local warning on, per firing, in simulated node time."""
    out = []
    confirm = timedelta(milliseconds=node.confirm_ms)
    previous = "N"
    pending_since: datetime | None = None
    for at, state, warn in node.local_log:
        block_start = at - timedelta(seconds=1)
        if state == "P" and previous != "P":
            pending_since = block_start
        if state == "F" and previous == "P" and pending_since is not None:
            confirmed_at = pending_since + confirm
            assert warn, "warning off in firing"
            out.append((at - confirmed_at).total_seconds() + UI_REFRESH_S)
        previous = state
    return out


def episodes_of(node: SimulatedNode, events: list[dict[str, Any]]) -> dict[str, str]:
    """Episode kind of each threshold_entered event (by the block that confirmed it)."""
    kinds = {}
    for e in events:
        if e["event_type"] == "threshold_entered":
            at = datetime.fromisoformat(e["observed_at"])
            sec = int((at - node.start).total_seconds()) - 1
            kinds[e["event_id"]] = node.episode(sec)[1]
    return kinds


def new_node(start: datetime) -> SimulatedNode:
    return SimulatedNode(
        "alerts",
        start,
        NODE,
        CIRCUIT,
        LIMIT_W,
        secrets.randbits(32),
        confirm_ms=CONFIRM_MS,
        clear_ms=CLEAR_MS,
    )


def episode_count(k: int) -> int:
    """Episodes of kind index k (0 sustained, 1 surge, 2 below) among EPISODES."""
    return len(range(k, EPISODES, 3))


def settled_alerts(since: datetime, resolved: int) -> list[dict[str, Any]]:
    """Alerts since `since`, waiting until `resolved` threshold alerts are resolved."""

    def ready() -> list[dict[str, Any]] | None:
        rows = alerts_since(since)
        done = [r for r in rows if r["kind"] == "active_power_threshold"]
        return rows if sum(r["status"] == "resolved" for r in done) >= resolved else None

    return stack.wait_until(ready, timeout_s=20) or alerts_since(since)


def delivered(alert_ids: set[str], log: str = HOOK_LOG) -> list[dict[str, Any]]:
    def ready() -> list[dict[str, Any]] | None:
        rows = webhook_log(log)
        return rows if alert_ids <= {h["key"] for h in rows} else None

    return stack.wait_until(ready, timeout_s=15) or webhook_log(log)


def test_us3_alert_acceptance() -> None:
    stack.require_stack()
    run_id = f"us3-{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{secrets.token_hex(2)}"
    start = datetime.now(UTC).replace(microsecond=0) + timedelta(seconds=5)
    node = new_node(start)
    version = ensure_node_and_config(node)
    duration = timedelta(seconds=EPISODES * node.episode_s)
    life = duration.total_seconds() + 60
    container("sh", "-c", f"rm -f {HOOK_LOG}; printf acceptance-dummy > {TOKEN_FILE}")
    stop = start_delivery("generic", HOOK_PORT, HOOK_LOG, TOKEN_FILE, life)
    try:
        events = publish_realtime(node, duration)
        by_event = {e["event_id"]: e for e in events}
        entered_kind = episodes_of(node, events)
        expected = episode_count(0)
        ours = settled_alerts(start - timedelta(seconds=1), expected)
        threshold_alerts = [a for a in ours if a["kind"] == "active_power_threshold"]
        health = [a for a in ours if a["kind"] == "pipeline_health"]
        hooks = delivered({a["alert_id"] for a in ours})
    finally:
        container("touch", stop)
    first_hook = {}
    for h in hooks:
        first_hook.setdefault(h["key"], h)

    remote_s = []
    for a in threshold_alerts:
        ev = by_event.get(a["event_id"])
        hook = first_hook.get(a["alert_id"])
        if ev is not None and hook is not None:
            observed = datetime.fromisoformat(ev["observed_at"]).timestamp()
            remote_s.append(hook["received_at"] - observed)
    local_s = local_latencies(node)
    alerted_kinds = [entered_kind.get(a["event_id"], "unknown") for a in threshold_alerts]

    summary = {
        "run_id": run_id,
        "simulated": True,
        "validation": "not_validated",
        "config": {
            "config_version": version,
            "limit_W": LIMIT_W,
            "clear_below_W": node.clear_below_w,
            "confirm_ms": CONFIRM_MS,
            "clear_ms": CLEAR_MS,
        },
        "episodes": {
            "total": EPISODES,
            "sustained": expected,
            "surge": episode_count(1),
            "below": episode_count(2),
        },
        "events_sent": {
            k: sum(e["event_type"] == k for e in events) for k in entered_types(events)
        },
        "threshold_alerts": len(threshold_alerts),
        "alerted_episode_kinds": {k: alerted_kinds.count(k) for k in set(alerted_kinds)},
        "resolved": sum(a["status"] == "resolved" for a in threshold_alerts),
        "pipeline_health_alerts": len(health),
        "webhook_deliveries": len(first_hook),
        "local_warning_s": {
            "basis": "simulated node timing (confirming block + 0.5 s display refresh)",
            "max": round(max(local_s), 3) if local_s else None,
            "count": len(local_s),
        },
        "remote_alert_s": {
            "basis": "node event time to fake webhook receipt",
            "p50": round(statistics.median(remote_s), 3) if remote_s else None,
            "max": round(max(remote_s), 3) if remote_s else None,
            "count": len(remote_s),
        },
    }
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / f"{run_id}.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))

    assert len(threshold_alerts) == expected, summary
    assert set(alerted_kinds) == {"sustained"}, summary  # surges and below-limit never alert
    assert summary["resolved"] == expected, summary
    assert health == [], [a["reasons"] for a in health]
    assert len(local_s) == expected
    assert max(local_s) <= LOCAL_BOUND_S
    assert len(remote_s) == expected, summary
    assert max(remote_s) <= REMOTE_BOUND_S, summary


def entered_types(events: list[dict[str, Any]]) -> list[str]:
    return sorted({str(e["event_type"]) for e in events})


def docker(*args: str) -> None:
    subprocess.run(["docker", *args], capture_output=True, text=True, check=True)


def test_us3_local_warning_with_ingestion_stopped() -> None:
    """Scenario 3: the node warns locally with the server down; the alert follows later."""
    stack.require_stack()
    start = datetime.now(UTC).replace(microsecond=0) + timedelta(seconds=2)
    node = new_node(start)
    ensure_node_and_config(node)
    docker("stop", stack.INGESTION)
    try:
        # A sustained episode, then a surge, so the clear falls inside a full window.
        events = publish_realtime(node, timedelta(seconds=2 * node.episode_s))
        assert any(warn for _, state, warn in node.local_log if state == "F")
        assert max(local_latencies(node)) <= LOCAL_BOUND_S
    finally:
        docker("start", stack.INGESTION)
    entered = [e for e in events if e["event_type"] == "threshold_entered"]
    assert len(entered) == 1
    assert stack.wait_until(lambda: stack.health(stack.INGESTION) == "healthy", timeout_s=120)
    opened = stack.wait_until(
        lambda: [
            a
            for a in alerts_since(start - timedelta(seconds=1))
            if a["event_id"] == entered[0]["event_id"]
        ],
        timeout_s=60,
    )
    assert opened, "the broker should have kept the event for the ingestion session"
    assert opened[0]["status"] == "resolved"  # the clear event was kept too


def test_us3_ntfy_format_end_to_end() -> None:
    """T109: one sustained episode through the real alert path to a fake ntfy server."""
    stack.require_stack()
    start = datetime.now(UTC).replace(microsecond=0) + timedelta(seconds=5)
    node = new_node(start)
    ensure_node_and_config(node)
    duration = timedelta(seconds=node.episode_s)  # episode 0 is sustained
    life = duration.total_seconds() + 60
    topic = f"us3-dummy-{secrets.token_hex(8)}"  # test value, never a real topic
    container("sh", "-c", f"rm -f {NTFY_LOG}; printf %s {topic} > {NTFY_TOPIC_FILE}")
    stop = start_delivery("ntfy", NTFY_PORT, NTFY_LOG, NTFY_TOPIC_FILE, life)
    try:
        events = publish_realtime(node, duration)
        ours = settled_alerts(start - timedelta(seconds=1), 1)
        threshold_alerts = [a for a in ours if a["kind"] == "active_power_threshold"]
        hooks = delivered({a["alert_id"] for a in threshold_alerts}, NTFY_LOG)
    finally:
        container("touch", stop)

    assert len(threshold_alerts) == 1, ours
    (alert,) = threshold_alerts
    (hook,) = [h for h in hooks if h["key"] == alert["alert_id"]]
    body = hook["body"]
    assert (hook["path"], hook["bearer"]) == ("/", False)
    assert body["topic"] == topic
    assert body["title"] == "Alerta: potencia sobre el límite"
    assert body["priority"] == 4
    assert body["tags"] == ["warning", "zap"]
    lines = body["message"].splitlines()
    assert lines[0] == f"Nodo {NODE}, circuito {CIRCUIT}."
    assert "Valores no validados." in lines
    assert lines[-1] == f"ID: {alert['alert_id']}"
    (entered,) = [e for e in events if e["event_id"] == alert["event_id"]]
    observed = datetime.fromisoformat(entered["observed_at"]).timestamp()
    assert hook["received_at"] - observed <= REMOTE_BOUND_S
