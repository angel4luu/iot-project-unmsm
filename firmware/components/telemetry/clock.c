#include "clock.h"

#include <stdio.h>

void clock_init(clock_state_t *c, uint32_t sntp_interval_s) {
    *c = (clock_state_t){
        .synced = false,
        .link_up = false,
        .fresh_limit_us = ((int64_t)sntp_interval_s * 2 + 60) * 1000000LL,
    };
}

void clock_on_sntp_sync(clock_state_t *c, int64_t utc_ms, int64_t mono_us) {
    c->synced = true;
    c->link_up = true; // a sync proves the link works
    c->sync_utc_ms = utc_ms;
    c->sync_mono_us = mono_us;
}

void clock_on_link(clock_state_t *c, bool up) {
    c->link_up = up;
}

clock_reading_t clock_read(const clock_state_t *c, int64_t mono_us) {
    clock_reading_t r = {.uptime_ms = mono_us / 1000, .last_sync_age_s = -1};
    if (!c->synced) {
        r.source = CLOCK_SOURCE_UNSYNCHRONIZED;
        r.utc_ms = mono_us / 1000;
        return r;
    }
    int64_t since_us = mono_us - c->sync_mono_us;
    if (since_us < 0) {
        since_us = 0; // monotonic time never goes back; guard against misuse
    }
    r.utc_ms = c->sync_utc_ms + since_us / 1000;
    r.last_sync_age_s = since_us / 1000000;
    r.source =
        (c->link_up && since_us <= c->fresh_limit_us) ? CLOCK_SOURCE_SNTP : CLOCK_SOURCE_HOLDOVER;
    return r;
}

const char *clock_source_name(clock_source_t source) {
    switch (source) {
    case CLOCK_SOURCE_SNTP:
        return "sntp";
    case CLOCK_SOURCE_HOLDOVER:
        return "holdover";
    case CLOCK_SOURCE_UNSYNCHRONIZED:
    default:
        return "unsynchronized";
    }
}

// Days since 1970-01-01 to civil date (H. Hinnant's algorithm, proleptic Gregorian).
static void civil_from_days(int64_t z, int *year, unsigned *month, unsigned *day) {
    z += 719468;
    const int64_t era = (z >= 0 ? z : z - 146096) / 146097;
    const unsigned doe = (unsigned)(z - era * 146097);
    const unsigned yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    const unsigned doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    const unsigned mp = (5 * doy + 2) / 153;
    *day = doy - (153 * mp + 2) / 5 + 1;
    *month = mp < 10 ? mp + 3 : mp - 9;
    *year = (int)(yoe + era * 400 + (*month <= 2));
}

size_t clock_format_utc(int64_t utc_ms, char *buf, size_t len) {
    // 253402300799999 ms is 9999-12-31T23:59:59.999Z, the last 4-digit-year instant.
    if (buf == NULL || len < CLOCK_RFC3339_LEN || utc_ms < 0 || utc_ms > 253402300799999LL) {
        return 0;
    }
    const int64_t days = utc_ms / 86400000LL;
    const int64_t ms_of_day = utc_ms % 86400000LL;
    int year;
    unsigned month, day;
    civil_from_days(days, &year, &month, &day);
    const int n = snprintf(buf, len, "%04d-%02u-%02uT%02u:%02u:%02u.%03uZ", year, month, day,
                           (unsigned)(ms_of_day / 3600000), (unsigned)(ms_of_day / 60000 % 60),
                           (unsigned)(ms_of_day / 1000 % 60), (unsigned)(ms_of_day % 1000));
    return (n > 0 && (size_t)n < len) ? (size_t)n : 0;
}
