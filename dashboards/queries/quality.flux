// Panel 6a — degraded and invalid windows counted by minute.
from(bucket: "energy_raw")
    |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
    |> filter(fn: (r) => r._measurement == "electrical_measurement" and r.node_id == "${node}" and (r.quality == "degraded" or r.quality == "invalid") and r._field == "quality_flags")
    |> aggregateWindow(every: 1m, fn: count, createEmpty: false)
    |> yield(name: "non_valid_windows_per_minute")

// Panel 6b — recent quality flags; empty flag strings are omitted.
from(bucket: "energy_raw")
    |> range(start: -24h)
    |> filter(fn: (r) => r._measurement == "electrical_measurement" and r.node_id == "${node}" and (r.quality == "degraded" or r.quality == "invalid") and r._field == "quality_flags")
    |> filter(fn: (r) => r._value != "")
    |> keep(columns: ["_time", "node_id", "circuit_id", "quality", "_value"])
    |> sort(columns: ["_time"], desc: true)
    |> limit(n: 100)
    |> yield(name: "recent_quality_flags")

// Panel 6c — clock source over time; calibration revision is retained as a tag on each window.
from(bucket: "energy_raw")
    |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
    |> filter(fn: (r) => r._measurement == "electrical_measurement" and r.node_id == "${node}" and r._field == "clock_source")
    |> yield(name: "clock_source_and_calibration_revision")
