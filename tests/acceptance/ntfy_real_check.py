"""T110: real ntfy end-to-end check, with the operator and the phone present.

Unlike the acceptance tests, delivery here goes through the running service's own
worker to the real ntfy server configured in `.env` (guides/operations/ntfy.md). The
script publishes one sustained simulated episode as node `sim-001`, waits until the
service marks the alert's notification `delivered`, asks the operator whether the
phone showed it, and writes `experiments/manifests/ntfy-YYYYMMDD.json`.

The webhook URL and topic are never read, printed, or recorded. Simulated values;
not validated. Run from the repository root: `make ntfy-check`.
"""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from tests import stack
from tests.acceptance.test_us3_alerts import (
    REMOTE_BOUND_S,
    container,
    ensure_node_and_config,
    new_node,
    publish_realtime,
    settled_alerts,
)

MANIFESTS = stack.REPO / "experiments" / "manifests"

OUTBOX = r"""
import json, sys
from energy_ingestion.contracts.models import wire_time
from energy_ingestion.persistence.db import Alert, NotificationOutbox
from energy_ingestion.persistence.db import make_engine, make_session_factory
from sqlalchemy import select
with make_session_factory(make_engine())() as s:
    a = s.get(Alert, sys.argv[1])
    rows = s.scalars(select(NotificationOutbox).where(NotificationOutbox.alert_id == a.alert_id))
    print(json.dumps({"opened_at": wire_time(a.opened_at), "notifications": [
        {"state": r.state, "attempt_count": r.attempt_count, "last_error_code": r.last_error_code,
         "delivered_at": wire_time(r.delivered_at) if r.delivered_at else None} for r in rows]}))
"""


def service_format() -> str:
    """The running service's notification format, or '' when delivery is disabled."""
    url = container("sh", "-c", 'test -n "$NOTIFICATION_WEBHOOK_URL" && echo set || true')
    if url.strip() != "set":
        return ""
    return container("printenv", "NOTIFICATION_FORMAT").strip() or "generic"


def ask(question: str) -> str:
    while True:
        answer = input(f"{question} [s/n]: ").strip().lower()
        if answer in ("s", "n"):
            return "yes" if answer == "s" else "no"


def main() -> int:
    stack.require_stack()
    fmt = service_format()
    if fmt != "ntfy":
        print("The service is not configured for ntfy (see guides/operations/ntfy.md).")
        return 2
    start = datetime.now(UTC).replace(microsecond=0) + timedelta(seconds=5)
    node = new_node(start)
    version = ensure_node_and_config(node)
    print(f"Publishing one sustained episode ({node.episode_s} s); watch the phone.")
    events = publish_realtime(node, timedelta(seconds=node.episode_s))
    alerts = [
        a
        for a in settled_alerts(start - timedelta(seconds=1), 1)
        if a["kind"] == "active_power_threshold"
    ]
    if len(alerts) != 1:
        print(f"Expected one threshold alert, got {len(alerts)}.")
        return 1
    (alert,) = alerts
    (entered,) = [e for e in events if e["event_id"] == alert["event_id"]]

    def delivered() -> dict[str, Any] | None:
        doc: dict[str, Any] = json.loads(container("python", "-c", OUTBOX, alert["alert_id"]))
        states = {n["state"] for n in doc["notifications"]}
        return doc if states & {"delivered", "failed_terminal"} else None

    outbox = stack.wait_until(delivered, timeout_s=60) or json.loads(
        container("python", "-c", OUTBOX, alert["alert_id"])
    )
    (row,) = outbox["notifications"]
    observed = datetime.fromisoformat(entered["observed_at"])
    latency = (
        (datetime.fromisoformat(row["delivered_at"]) - observed).total_seconds()
        if row["delivered_at"]
        else None
    )
    print(f"Server: notification {row['state']}, event to delivery {latency} s.")
    phone = ask("¿Llegó la notificación «Alerta: potencia sobre el límite» al teléfono?")
    spanish = ask("¿El título y el mensaje se ven en español y dicen «Valores no validados»?")
    within = ask("¿Llegó en menos de 10 s desde que la vio el servidor (aprox.)?")
    passed = (
        row["state"] == "delivered"
        and latency is not None
        and latency <= REMOTE_BOUND_S
        and phone == spanish == within == "yes"
    )
    script = Path(__file__).resolve()
    commit = subprocess.run(
        ["git", "-C", str(stack.REPO), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    manifest = {
        "check": "T110 ntfy end to end",
        "simulated": True,
        "validation": "not_validated",
        "node_id": node.node_id,
        "config_version": version,
        "alert_id": alert["alert_id"],
        "event_observed_at": entered["observed_at"],
        "alert_opened_at": outbox["opened_at"],
        "notification": row,
        "event_to_delivery_s": round(latency, 3) if latency is not None else None,
        "bound_s": REMOTE_BOUND_S,
        "operator": {"phone_received": phone, "spanish_text": spanish, "within_10s": within},
        "passed": passed,
        "endpoint": "ntfy (URL and topic are runtime secrets, not recorded)",
        "files": [{"role": "script", "path": str(script.relative_to(stack.REPO)),
                   "sha256": hashlib.sha256(script.read_bytes()).hexdigest()}],
        "code_commit": commit,
        "environment": {"python": platform.python_version(), "platform": platform.platform()},
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }  # fmt: skip
    MANIFESTS.mkdir(parents=True, exist_ok=True)
    out = MANIFESTS / f"ntfy-{datetime.now(UTC):%Y%m%d}.json"
    if out.exists():
        out = out.with_name(f"ntfy-{datetime.now(UTC):%Y%m%dT%H%M%S}.json")
    out.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"{'PASS' if passed else 'FAIL'}: {out.relative_to(stack.REPO)}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
