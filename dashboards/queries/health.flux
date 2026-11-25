// Panel 8a — pipeline counters converted to per-second rates plus ingest latency.
from(bucket: "operations")
    |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
    |> filter(fn: (r) => r._measurement == "pipeline" and r.component == "ingestion")
    |> filter(fn: (r) => contains(value: r._field, set: ["received_total", "accepted_total", "rejected_total", "duplicate_total", "conflict_total"]))
    |> derivative(unit: 1s, nonNegative: true)
    |> yield(name: "pipeline_counter_rates")

// Panel 8a — ingest latency distribution summaries.
from(bucket: "operations")
    |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
    |> filter(fn: (r) => r._measurement == "pipeline" and r.component == "ingestion")
    |> filter(fn: (r) => r._field == "ingest_latency_ms_p50" or r._field == "ingest_latency_ms_max")
    |> yield(name: "ingest_latency_ms")

// Panel 8b — most recent node queue state.
from(bucket: "operations")
    |> range(start: -15m)
    |> filter(fn: (r) => r._measurement == "node_status" and r.node_id == "${node}")
    |> filter(fn: (r) => contains(value: r._field, set: ["pending_records", "oldest_pending_age_s", "state"]))
    |> group(columns: ["_field"])
    |> last()
    |> yield(name: "node_queue_status")

// Panel 8c — latest rejected/conflict events.
from(bucket: "operations")
    |> range(start: -24h)
    |> filter(fn: (r) => r._measurement == "ingest_event" and r.node_id == "${node}")
    |> keep(columns: ["_time", "node_id", "result", "_field", "_value"])
    |> sort(columns: ["_time"], desc: true)
    |> limit(n: 100)
    |> yield(name: "recent_ingest_events")

// Panel 8d — age of the newest energy_raw point, in seconds.
from(bucket: "energy_raw")
    |> range(start: -30d)
    |> filter(fn: (r) => r._measurement == "electrical_measurement" and r.node_id == "${node}" and r._field == "active_power_W")
    |> group(columns: ["node_id"])
    |> last()
    |> map(fn: (r) => ({r with _value: float(v: int(v: now()) - int(v: r._time)) / 1000000000.0, _field: "last_point_age_s"}))
    |> yield(name: "energy_raw_last_point_age")
