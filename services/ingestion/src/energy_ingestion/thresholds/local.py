"""Python mirror of the node's local threshold state machine (firmware threshold.c).

The simulator uses it to send the node events a real node would send. It follows
the same rules, checked against the same table as the firmware host test
(`tests/fixtures/threshold/cases.txt`):

    normal   --power > limit-------------------------> pending
    pending  --above for confirm_ms------------------> firing     (threshold_entered)
    pending  --power <= limit, or a non-valid block--> normal
    firing   --power < clear_below_W-----------------> clearing
    clearing --below for clear_ms--------------------> resolved -> normal (threshold_cleared)
    clearing --power >= clear_below_W----------------> firing

A non-valid block (None) never confirms or clears; a change of block quality is a
separate `measurement_quality_changed` event. Overload exception (FR-012): a block
degraded only by a current above the calibrated range (`over_range_high`), with
power above the limit, counts as above the limit; it never clears. The local warning (red LED and
buzzer) is on only in firing and clearing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class State(StrEnum):
    NORMAL = "N"
    PENDING = "P"
    FIRING = "F"
    CLEARING = "C"


@dataclass(frozen=True)
class LocalEvent:
    event_type: str  # threshold_entered | threshold_cleared | measurement_quality_changed
    severity: str
    quality: str
    measured_value: float | None
    threshold_value: float | None
    local_warning_active: bool
    reason_code: str | None


@dataclass
class LocalThreshold:
    limit_w: float
    clear_below_w: float
    confirm_ms: int = 10_000
    clear_ms: int = 5_000
    severity: str = "warning"
    local_warning_enabled: bool = True
    state: State = field(default=State.NORMAL, init=False)
    elapsed_ms: int = field(default=0, init=False)
    last_quality: str = field(default="valid", init=False)

    @property
    def warning_active(self) -> bool:
        return self.local_warning_enabled and self.state in (State.FIRING, State.CLEARING)

    def step(
        self,
        power_w: float | None,
        duration_ms: int = 1000,
        quality: str = "valid",
        reason: str = "sensor_disconnected",
        over_range_high: bool = False,
    ) -> list[LocalEvent]:
        """One 1 s block; `power_w` None (or quality not valid) is a non-valid block."""
        events: list[LocalEvent] = []
        valid = quality == "valid" and power_w is not None
        q = "valid" if valid else ("invalid" if quality == "valid" else quality)
        if q != self.last_quality:
            restored = q == "valid"
            events.append(
                LocalEvent(
                    "measurement_quality_changed",
                    "info" if restored else "warning",
                    q,
                    None,
                    None,
                    self.warning_active,
                    "quality_restored" if restored else reason,
                )
            )
            self.last_quality = q
        overload = (
            not valid
            and over_range_high
            and quality == "degraded"
            and power_w is not None
            and power_w > self.limit_w
        )
        if not valid and not overload:
            if self.state is State.PENDING:
                self.state, self.elapsed_ms = State.NORMAL, 0
            return events
        assert power_w is not None
        p = power_w
        if self.state is State.NORMAL and p > self.limit_w:
            self.state, self.elapsed_ms = State.PENDING, 0
        if self.state is State.PENDING:
            if not p > self.limit_w:
                self.state, self.elapsed_ms = State.NORMAL, 0
            else:
                self.elapsed_ms += duration_ms
                if self.elapsed_ms >= self.confirm_ms:
                    self.state, self.elapsed_ms = State.FIRING, 0
                    events.append(self._event("threshold_entered", p, q))
            return events
        if self.state is State.FIRING and p < self.clear_below_w:
            self.state, self.elapsed_ms = State.CLEARING, 0
        if self.state is State.CLEARING:
            if not p < self.clear_below_w:
                self.state, self.elapsed_ms = State.FIRING, 0
            else:
                self.elapsed_ms += duration_ms
                if self.elapsed_ms >= self.clear_ms:
                    self.state, self.elapsed_ms = State.NORMAL, 0
                    events.append(self._event("threshold_cleared", p, q))
        return events

    def _event(self, event_type: str, p: float, quality: str) -> LocalEvent:
        entered = event_type == "threshold_entered"
        return LocalEvent(
            event_type,
            self.severity if entered else "info",
            quality,  # `degraded` when an over-range block confirmed it
            round(p, 3),
            self.limit_w if entered else self.clear_below_w,
            self.warning_active,
            None,
        )
