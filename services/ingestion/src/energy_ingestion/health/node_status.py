"""Server-side node status (T054; plan, Health observability).

The node reports `online`/`degraded`/`offline` in its retained status (its last
will is an `offline` status). The server derives the state it shows:

    offline   the node reported offline (last will or clean stop), or no
              measurement arrived for more than 30 s
    stale     no measurement arrived for more than 15 s
    degraded  the node reports degraded and measurements arrive
    online    otherwise

Timers use the server receive time; a window replayed after an outage counts as
a sign of life, but `last_measurement_age_s` (from the window end) tells the
dashboard it is not live. Pure logic: callers pass `now`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime

from influxdb_client import Point, WritePrecision

STALE_AFTER_S = 15.0
OFFLINE_AFTER_S = 30.0
HEARTBEAT_S = 5.0
STATUS_MEASUREMENT = "node_status"


@dataclass
class NodeView:
    node_id: str
    first_seen: datetime
    reported_state: str = "online"
    acquisition_state: str | None = None
    clock_source: str | None = None
    firmware_version: str | None = None
    calibration_revision: str | None = None
    pending_records: int | None = None
    oldest_pending_age_s: int | None = None
    last_measurement_rx: datetime | None = None
    newest_window_end: datetime | None = None
    state: str = field(default="stale")


@dataclass(frozen=True)
class Transition:
    node_id: str
    old: str
    new: str
    at: datetime


def derive_state(view: NodeView, now: datetime) -> str:
    if view.reported_state == "offline":
        return "offline"
    reference = view.last_measurement_rx or view.first_seen
    silent = (now - reference).total_seconds()
    if silent > OFFLINE_AFTER_S:
        return "offline"
    if silent > STALE_AFTER_S or view.last_measurement_rx is None:
        return "stale"
    return "degraded" if view.reported_state == "degraded" else "online"


class NodeStatusTracker:
    def __init__(self) -> None:
        self.nodes: dict[str, NodeView] = {}

    def _view(self, node_id: str, now: datetime) -> NodeView:
        if node_id not in self.nodes:
            self.nodes[node_id] = NodeView(node_id=node_id, first_seen=now)
        return self.nodes[node_id]

    def _update(self, view: NodeView, now: datetime) -> list[Transition]:
        new = derive_state(view, now)
        if new == view.state:
            return []
        old, view.state = view.state, new
        return [Transition(view.node_id, old, new, now)]

    def on_status(self, doc: Mapping[str, object], now: datetime) -> list[Transition]:
        """A schema-valid node-status payload (retained, periodic, or last will)."""
        view = self._view(str(doc["node_id"]), now)
        view.reported_state = str(doc["state"])
        view.acquisition_state = _str(doc.get("acquisition_state"))
        view.clock_source = _str(doc.get("clock_source"))
        view.firmware_version = _str(doc.get("firmware_version"))
        view.calibration_revision = _str(doc.get("calibration_revision"))
        view.pending_records = _int(doc.get("pending_records"))
        view.oldest_pending_age_s = _int(doc.get("oldest_pending_age_s"))
        return self._update(view, now)

    def on_measurement(self, node_id: str, window_end: datetime, now: datetime) -> list[Transition]:
        view = self._view(node_id, now)
        view.last_measurement_rx = now
        if view.newest_window_end is None or window_end > view.newest_window_end:
            view.newest_window_end = window_end
        if view.reported_state == "offline":  # measurements prove the node is back
            view.reported_state = "online"
        return self._update(view, now)

    def tick(self, now: datetime) -> list[Transition]:
        return [t for view in self.nodes.values() for t in self._update(view, now)]

    def points(self, now: datetime) -> list[Point]:
        """Heartbeat points for the `operations` bucket (handoff data layout)."""
        out = []
        for v in self.nodes.values():
            p = Point(STATUS_MEASUREMENT).tag("node_id", v.node_id).time(now, WritePrecision.MS)
            p.field("state", v.state)
            for name in ("acquisition_state", "clock_source", "firmware_version"):
                value = getattr(v, name)
                if value is not None:
                    p.field(name, value)
            p.field("calibration_revision", v.calibration_revision or "none")
            for name in ("pending_records", "oldest_pending_age_s"):
                value = getattr(v, name)
                if value is not None:
                    p.field(name, value)
            if v.newest_window_end is not None:
                age = (now - v.newest_window_end).total_seconds()
                p.field("last_measurement_age_s", float(age))
            out.append(p)
        return out


def _str(value: object) -> str | None:
    return None if value is None else str(value)


def _int(value: object) -> int | None:
    return value if isinstance(value, int) else None
