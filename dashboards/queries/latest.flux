// Panel 1 — node identity, current status, calibration, clock, and last valid update.
import "array"

statusData = from(bucket: "operations")
    |> range(start: -30d)
    |> filter(fn: (r) => r._measurement == "node_status" and r.node_id == "${node}")
    |> filter(fn: (r) => contains(value: r._field, set: ["acquisition_state", "clock_source", "firmware_version", "calibration_revision", "last_measurement_age_s"]))
    |> group(columns: ["_field"])
    |> last()
    |> yield(name: "latest_node_metadata")

stateData = from(bucket: "operations")
    |> range(start: -30d)
    |> filter(fn: (r) => r._measurement == "node_status" and r.node_id == "${node}" and r._field == "state")
    |> keep(columns: ["_time", "node_id", "_field", "_value"])

union(tables: [stateData, array.from(rows: [{_time: time(v: 0), node_id: "${node}", _field: "state", _value: "NO DATA"}])])
    |> group(columns: ["node_id"])
    |> sort(columns: ["_time"])
    |> last()
    |> yield(name: "latest_node_status")

validUpdate = from(bucket: "energy_raw")
    |> range(start: -30d)
    |> filter(fn: (r) => r._measurement == "electrical_measurement" and r.node_id == "${node}" and r.quality == "valid" and r._field == "active_power_W")
    |> map(fn: (r) => ({_time: r._time, node_id: r.node_id, circuit_id: r.circuit_id, calibration_revision: r.calibration_revision, _field: "last_valid_update", _value: string(v: r._time), last_valid_age_s: string(v: float(v: int(v: now()) - int(v: r._time)) / 1000000000.0)}))

union(tables: [validUpdate, array.from(rows: [{_time: time(v: 0), node_id: "${node}", circuit_id: "unknown", calibration_revision: "unknown", _field: "last_valid_update", _value: "NO DATA", last_valid_age_s: "NO DATA"}])])
    |> group(columns: ["node_id"])
    |> sort(columns: ["_time"])
    |> last()
    |> map(fn: (r) => ({r with _time: if r._value == "NO DATA" then now() else r._time}))
    |> yield(name: "last_valid_update")

// Panel 2 — current cards. Values are strings so status text can replace a number safely.
import "join"
import "array"

statusData = from(bucket: "operations")
    |> range(start: -15m)
    |> filter(fn: (r) => r._measurement == "node_status" and r.node_id == "${node}" and r._field == "state")
    |> rename(columns: {_value: "node_state"})
    |> keep(columns: ["_time", "node_id", "node_state"])

latestStatus = union(tables: [statusData, array.from(rows: [{_time: time(v: 0), node_id: "${node}", node_state: "NO DATA"}])])
    |> group(columns: ["node_id"])
    |> sort(columns: ["_time"])
    |> last(column: "node_state")

windowData = from(bucket: "energy_raw")
    |> range(start: -15m)
    |> filter(fn: (r) => r._measurement == "electrical_measurement" and r.node_id == "${node}" and r._field == "quality_flags")
    |> rename(columns: {_value: "window_flags", _time: "window_time"})
    |> keep(columns: ["node_id", "quality", "calibration_revision", "window_flags", "window_time"])

latestWindow = union(tables: [windowData, array.from(rows: [{node_id: "${node}", quality: "unknown", calibration_revision: "unknown", window_flags: "", window_time: time(v: 0)}])])
    |> group(columns: ["node_id"])
    |> sort(columns: ["window_time"])
    |> last(column: "window_flags")

statusWithWindow = join.left(
    left: latestStatus,
    right: latestWindow,
    on: (l, r) => l.node_id == r.node_id,
    as: (l, r) => ({l with latest_quality: r.quality, calibration_revision: r.calibration_revision, window_flags: r.window_flags, window_time: r.window_time}),
)

card = (field, label, unit, energy) => {
    readingData = from(bucket: "energy_raw")
        |> range(start: -30d)
        |> filter(fn: (r) => r._measurement == "electrical_measurement" and r.node_id == "${node}" and r.quality == "valid" and r._field == field)
        |> map(fn: (r) => ({_time: r._time, node_id: r.node_id, circuit_id: r.circuit_id, calibration_revision: r.calibration_revision, _value: float(v: r._value), has_reading: true}))

    reading = union(tables: [readingData, array.from(rows: [{_time: time(v: 0), node_id: "${node}", circuit_id: "unknown", calibration_revision: "unknown", _value: 0.0, has_reading: false}])])
        |> group(columns: ["node_id"])
        |> sort(columns: ["_time"])
        |> last()
        |> rename(columns: {_value: "reading", _time: "reading_time", calibration_revision: "reading_calibration_revision"})

    return join.left(
        left: statusWithWindow,
        right: reading,
        on: (l, r) => l.node_id == r.node_id,
        as: (l, r) => ({l with circuit_id: r.circuit_id, reading_calibration_revision: r.reading_calibration_revision, reading: r.reading, reading_time: r.reading_time, has_reading: r.has_reading}),
    )
        |> map(fn: (r) => {
            age_s = if r.has_reading then float(v: int(v: now()) - int(v: r.reading_time)) / 1000000000.0 else 999999.0
            hasBadWindow = exists r.latest_quality and (r.latest_quality == "degraded" or r.latest_quality == "invalid")
            reason = if exists r.window_flags and r.window_flags != "" then r.window_flags else if exists r.latest_quality then r.latest_quality else "quality unavailable"
            live = r.node_state == "online" and r.has_reading and age_s <= 15.0 and exists r.latest_quality and r.latest_quality == "valid"
            display = if r.node_state == "NO DATA" then "NO DATA" else if r.node_state == "offline" then "OFFLINE" else if hasBadWindow then reason else if r.node_state == "stale" or (r.has_reading and age_s > 15.0) or r.node_state == "degraded" then "STALE" else if live then (if energy then string(v: r.reading) + " Wh / " + string(v: r.reading / 1000.0) + " kWh" else string(v: r.reading)) else "NO DATA"
            quality = if r.node_state == "NO DATA" then "no data" else if r.node_state == "offline" then "offline" else if hasBadWindow then reason else if live then "valid" else if r.node_state == "stale" or (r.has_reading and age_s > 15.0) or r.node_state == "degraded" then "stale" else "no data"
            return {_time: if r.has_reading then r.reading_time else now(), node_id: r.node_id, circuit_id: r.circuit_id, metric: label, value: display, unit: unit, reading_time: if r.has_reading then string(v: r.reading_time) else "—", quality: quality, calibration_revision: r.reading_calibration_revision}
        })
}

union(tables: [
    card(field: "voltage_rms_V", label: "V RMS", unit: "V", energy: false),
    card(field: "current_rms_A", label: "I RMS", unit: "A", energy: false),
    card(field: "active_power_W", label: "Active power", unit: "W", energy: false),
    card(field: "active_energy_import_total_Wh", label: "Import energy", unit: "Wh / kWh", energy: true),
])
    |> yield(name: "current_cards")
