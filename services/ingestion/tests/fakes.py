"""Fakes shared by ingestion unit tests (no broker, no InfluxDB)."""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from influxdb_client import Point


@dataclass
class FakeWriter:
    points: list[tuple[str, Point]] = field(default_factory=list)
    fail: bool = False

    def write(self, bucket: str, point: Point) -> None:
        if self.fail:
            raise ConnectionError("influx down")
        self.points.append((bucket, point))

    def lines(self, bucket: str, measurement: str) -> list[str]:
        return [
            p.to_line_protocol()
            for b, p in self.points
            if b == bucket and p.to_line_protocol().startswith(measurement + ",")
        ]


@dataclass
class FakePublisher:
    sent: list[tuple[str, bytes, int, bool]] = field(default_factory=list)

    def __call__(self, topic: str, payload: bytes, qos: int, retain: bool) -> None:
        self.sent.append((topic, payload, qos, retain))


@dataclass
class FakeClock:
    now: datetime = datetime(2026, 10, 14, 17, 0, 5, 200000, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)
