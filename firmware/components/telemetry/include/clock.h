// Node clock (research R-005): SNTP UTC is authoritative, there is no RTC.
//
// - unsynchronized: no SNTP sync since boot; timestamps are diagnostic only.
// - sntp: synced, link up, and the last sync is fresh (<= 2 polls + 60 s).
// - holdover: synced earlier in this boot, but the link is down or the last sync
//   is stale; UTC keeps running on the monotonic timer and the age is reported.
//
// Pure logic: callers pass the monotonic time (esp_timer_get_time() on target),
// so energy and uptime never depend on wall-clock steps.
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

typedef enum {
    CLOCK_SOURCE_UNSYNCHRONIZED = 0,
    CLOCK_SOURCE_SNTP,
    CLOCK_SOURCE_HOLDOVER,
} clock_source_t;

typedef struct {
    bool synced;
    bool link_up;
    int64_t sync_utc_ms;
    int64_t sync_mono_us;
    int64_t fresh_limit_us;
} clock_state_t;

typedef struct {
    clock_source_t source;
    int64_t utc_ms;          // window timestamps; since boot when unsynchronized
    int64_t last_sync_age_s; // -1 when never synced in this boot
    int64_t uptime_ms;
} clock_reading_t;

#define CLOCK_RFC3339_LEN 25 // "YYYY-MM-DDTHH:MM:SS.mmmZ" plus NUL

void clock_init(clock_state_t *c, uint32_t sntp_interval_s);
void clock_on_sntp_sync(clock_state_t *c, int64_t utc_ms, int64_t mono_us);
void clock_on_link(clock_state_t *c, bool up);
clock_reading_t clock_read(const clock_state_t *c, int64_t mono_us);
const char *clock_source_name(clock_source_t source);
// Formats RFC 3339 UTC with milliseconds; returns 0 on bad input or small buffer.
size_t clock_format_utc(int64_t utc_ms, char *buf, size_t len);
