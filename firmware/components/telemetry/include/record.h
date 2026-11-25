// Compact records kept in the RAM queue and serialized only at publish time
// (plan › Telemetry, Delivery, and Clock Design).
#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "clock.h"
#include "quality.h"

#define REC_UUID_LEN 36
#define REC_REVISION_MAX 64

typedef struct {
    char message_id[REC_UUID_LEN + 1];
    char boot_id[REC_UUID_LEN + 1];
    uint64_t sequence;
    int64_t window_start_ms; // UTC ms (since boot when the clock is unsynchronized)
    int64_t window_end_ms;   // observation timestamp
    uint32_t duration_ms;    // monotonic duration
    uint32_t sample_count;
    clock_source_t clock_source;
    int64_t last_sync_age_s; // -1: never synced in this boot (null on the wire)
    uint64_t uptime_ms;
    quality_state_t quality;
    uint32_t flags;
    double valid_sample_ratio;
    // Quantities; written as null when the window is invalid.
    double v_rms_v, i_rms_a, active_power_w, energy_wh;
    char counter_id[REC_UUID_LEN + 1];
    char calibration_revision[REC_REVISION_MAX + 1]; // "" = null (no accepted calibration)
} measurement_record_t;

typedef struct {
    const char *node_id;
    const char *circuit_id;
    const char *boot_id;
    const char *firmware_version;
    const char *hardware_revision;
} node_identity_t;

typedef enum {
    NODE_ONLINE = 0,
    NODE_DEGRADED,
    NODE_OFFLINE,
} node_state_t;

typedef enum {
    ACQ_SAMPLING = 0,
    ACQ_DEGRADED,
    ACQ_STOPPED,
} acquisition_state_t;

typedef struct {
    int64_t observed_at_ms;
    node_state_t state;
    const char *calibration_revision; // NULL = null
    clock_source_t clock_source;
    acquisition_state_t acquisition_state;
    uint32_t pending_records;
    int64_t oldest_pending_age_s;
    int64_t last_valid_window_end_ms; // -1 = null
    const char *last_error_code;      // NULL = null
} status_record_t;

typedef enum {
    EVENT_THRESHOLD_ENTERED = 0,
    EVENT_THRESHOLD_CLEARED,
    EVENT_MEASUREMENT_QUALITY_CHANGED,
} event_type_t;

typedef enum {
    SEVERITY_INFO = 0,
    SEVERITY_WARNING,
    SEVERITY_CRITICAL,
} event_severity_t;

typedef struct {
    char event_id[REC_UUID_LEN + 1];
    uint64_t sequence;
    int64_t observed_at_ms;
    event_type_t type;
    event_severity_t severity;
    uint32_t config_version;
    bool has_measured, has_threshold;
    double measured_value, threshold_value;
    bool unit_watts; // "W", otherwise "none"
    quality_state_t quality;
    bool local_warning_active;
    const char *reason_code; // NULL = null
} event_record_t;
