// Panel 7 — alert evidence, state transitions, and latest webhook delivery state.
import "join"
import "internal/debug"

transitions = from(bucket: "operations")
    |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
    |> filter(fn: (r) => r._measurement == "alert_transition" and r.node_id == "${node}")
    |> filter(fn: (r) => contains(value: r._field, set: ["alert_id", "from_status", "actor", "reason", "observed_value", "threshold_value", "notification_state"]))
    |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
    // health and quality alerts carry no values: give every row the same columns
    |> map(fn: (r) => ({r with
        observed_value: if exists r.observed_value then r.observed_value else debug.null(type: "float"),
        threshold_value: if exists r.threshold_value then r.threshold_value else debug.null(type: "float"),
    }))
    |> rename(columns: {to_status: "status"})
    |> keep(columns: ["_time", "node_id", "kind", "severity", "status", "alert_id", "from_status", "actor", "reason", "observed_value", "threshold_value", "notification_state"])
    |> group(columns: ["alert_id"])

notifications = from(bucket: "operations")
    |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
    |> filter(fn: (r) => r._measurement == "alert_notification" and r.node_id == "${node}")
    |> filter(fn: (r) => contains(value: r._field, set: ["alert_id", "attempt_count", "last_error_code"]))
    |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
    // `last_error_code` is written only on failures: add it where it is missing
    |> map(fn: (r) => ({r with last_error_code: if exists r.last_error_code then r.last_error_code else ""}))
    |> rename(columns: {state: "latest_notification_state", attempt_count: "latest_attempt_count", last_error_code: "latest_error_code"})
    |> keep(columns: ["_time", "alert_id", "latest_notification_state", "latest_attempt_count", "latest_error_code"])
    |> group(columns: ["alert_id"])
    |> sort(columns: ["_time"])
    |> tail(n: 1)  // latest delivery state per alert (`last()` needs a _value column)

join.left(
    left: transitions,
    right: notifications,
    on: (l, r) => l.alert_id == r.alert_id,
    as: (l, r) => ({l with notification_state: if exists r.latest_notification_state then r.latest_notification_state else l.notification_state, latest_attempt_count: r.latest_attempt_count, latest_error_code: r.latest_error_code}),
)
    |> group()
    |> sort(columns: ["_time"], desc: true)
    |> yield(name: "alert_history")
