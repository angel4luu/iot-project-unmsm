// Panel 3 — valid active-power windows; insert a null point after gaps longer than 10 s.
import "internal/debug"

power = from(bucket: "energy_raw")
    |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
    |> filter(fn: (r) => r._measurement == "electrical_measurement" and r.node_id == "${node}" and r.quality == "valid" and r._field == "active_power_W")
    |> aggregateWindow(every: 5s, fn: mean, createEmpty: false)
    |> sort(columns: ["_time"])
    |> elapsed(unit: 1s, columnName: "elapsed_s")

powerValues = power
    |> drop(columns: ["elapsed_s"])

gapBreaks = power
    |> filter(fn: (r) => r.elapsed_s > 10)
    |> map(fn: (r) => ({r with _time: time(v: int(v: r._time) - 5000000000), _value: debug.null(type: "float")}))
    |> drop(columns: ["elapsed_s"])

union(tables: [powerValues, gapBreaks])
    |> sort(columns: ["_time"])
    |> yield(name: "valid_active_power_W")

// Panel 4 — valid RMS voltage/current; calibrated ranges are shaded by Grafana field thresholds.
from(bucket: "energy_raw")
    |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
    |> filter(fn: (r) => r._measurement == "electrical_measurement" and r.node_id == "${node}" and r.quality == "valid")
    |> filter(fn: (r) => contains(value: r._field, set: ["voltage_rms_V", "current_rms_A"]))
    |> aggregateWindow(every: 5s, fn: mean, createEmpty: false)
    |> yield(name: "valid_voltage_current")
