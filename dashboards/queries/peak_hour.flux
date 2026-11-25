import "timezone"
import "date"

option location = timezone.location(name: "America/Lima")

hourly = from(bucket: "energy_raw")
    |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
    |> filter(fn: (r) => r._measurement == "electrical_measurement" and r.node_id == "${node}" and r.quality == "valid")
    |> filter(fn: (r) => r._field == "active_energy_import_total_Wh" or r._field == "counter_id")
    |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
    |> keep(columns: ["_time", "counter_id", "active_energy_import_total_Wh"])
    |> group(columns: ["counter_id"])
    |> sort(columns: ["_time"])
    |> difference(columns: ["active_energy_import_total_Wh"])
    |> filter(fn: (r) => exists r.active_energy_import_total_Wh and r.active_energy_import_total_Wh >= 0.0)
    |> map(fn: (r) => ({_time: time(v: int(v: r._time) - 1000000), _value: float(v: r.active_energy_import_total_Wh)}))
    |> group()
    |> aggregateWindow(every: 1h, fn: sum, createEmpty: false, timeSrc: "_start")
    |> group()
    |> sort(columns: ["_time"])

hourly
    // earliest hour wins a tie: sort on (value, -time), both descending
    |> map(fn: (r) => ({r with neg_time: -int(v: r._time)}))
    |> sort(columns: ["_value", "neg_time"], desc: true)
    |> limit(n: 1)
    |> drop(columns: ["neg_time"])
    |> map(fn: (r) => ({r with result: "peak_hour"}))
    |> map(fn: (r) => {
        year = string(v: date.year(t: r._time))
        month = date.month(t: r._time)
        day = date.monthDay(t: r._time)
        hour = date.hour(t: r._time)
        minute = date.minute(t: r._time)
        monthText = if month < 10 then "0" + string(v: month) else string(v: month)
        dayText = if day < 10 then "0" + string(v: day) else string(v: day)
        hourText = if hour < 10 then "0" + string(v: hour) else string(v: hour)
        minuteText = if minute < 10 then "0" + string(v: minute) else string(v: minute)
        localStart = year + "-" + monthText + "-" + dayText + " " + hourText + ":" + minuteText
        return {r with peak_hour_lima: localStart}
    })
    |> yield(name: "peak_hour")
