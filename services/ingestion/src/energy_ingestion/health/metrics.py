"""Pipeline counters and latency (T055), flushed to `operations` every 10 s."""

from __future__ import annotations

import statistics
import threading
from collections import Counter
from datetime import datetime

from influxdb_client import Point, WritePrecision

RESULTS = ("received", "accepted", "rejected", "duplicate", "conflict")
FLUSH_S = 10.0


class PipelineMetrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.totals: Counter[str] = Counter(dict.fromkeys(RESULTS, 0))
        self._latencies: list[float] = []

    def count(self, result: str) -> None:
        if result not in RESULTS:
            raise ValueError(result)
        with self._lock:
            self.totals[result] += 1

    def latency(self, ms: float) -> None:
        with self._lock:
            self._latencies.append(ms)

    def snapshot(self) -> dict[str, float | int]:
        with self._lock:
            snap: dict[str, float | int] = {f"{k}_total": self.totals[k] for k in RESULTS}
            if self._latencies:
                snap["ingest_latency_ms_p50"] = statistics.median(self._latencies)
                snap["ingest_latency_ms_max"] = max(self._latencies)
            return snap

    def flush_point(self, now: datetime) -> Point:
        """Point for the last interval; latency samples are reset afterwards."""
        snap = self.snapshot()
        with self._lock:
            self._latencies.clear()
        p = Point("pipeline").tag("component", "ingestion").time(now, WritePrecision.MS)
        for key, value in snap.items():
            p.field(key, value)
        return p
