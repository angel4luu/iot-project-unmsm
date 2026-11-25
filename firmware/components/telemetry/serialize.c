#include "serialize.h"

#include <inttypes.h>
#include <math.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>

typedef struct {
    char *buf;
    size_t len, pos;
    bool ok;
} jw_t;

static void jw_raw(jw_t *w, const char *s) {
    const size_t n = strlen(s);
    if (!w->ok || w->pos + n + 1 > w->len) {
        w->ok = false;
        return;
    }
    memcpy(w->buf + w->pos, s, n + 1);
    w->pos += n;
}

static void jw_fmt(jw_t *w, const char *fmt, ...) {
    if (!w->ok) {
        return;
    }
    va_list ap;
    va_start(ap, fmt);
    const int n = vsnprintf(w->buf + w->pos, w->len - w->pos, fmt, ap);
    va_end(ap);
    if (n < 0 || w->pos + (size_t)n + 1 > w->len) {
        w->ok = false;
        return;
    }
    w->pos += (size_t)n;
}

// Strings here are identifiers, versions, and codes; anything that would need
// escaping is refused instead of escaped, so no payload carries surprises.
static void jw_str(jw_t *w, const char *s) {
    if (s == NULL) {
        w->ok = false;
        return;
    }
    for (const char *p = s; *p; p++) {
        const unsigned char c = (unsigned char)*p;
        if (c < 0x20 || c == '"' || c == '\\' || c >= 0x7F) {
            w->ok = false;
            return;
        }
    }
    jw_fmt(w, "\"%s\"", s);
}

static void jw_str_or_null(jw_t *w, const char *s) {
    if (s == NULL || s[0] == '\0') {
        jw_raw(w, "null");
    } else {
        jw_str(w, s);
    }
}

static void jw_key(jw_t *w, const char *key) {
    jw_fmt(w, "\"%s\":", key);
}

static void jw_time(jw_t *w, int64_t utc_ms) {
    char t[CLOCK_RFC3339_LEN];
    if (clock_format_utc(utc_ms, t, sizeof t) == 0) {
        w->ok = false;
        return;
    }
    jw_fmt(w, "\"%s\"", t);
}

// Number within [lo, hi] with `decimals`, else null.
static void jw_num(jw_t *w, double x, int decimals, double lo, double hi) {
    if (!isfinite(x) || x < lo || x > hi) {
        jw_raw(w, "null");
        return;
    }
    if (x == 0.0) {
        x = 0.0; // no "-0.000"
    }
    jw_fmt(w, "%.*f", decimals, x);
}

static const char *QUALITY_NAMES[] = {"valid", "degraded", "invalid"};

static bool uuid_ok(const char *s) {
    if (strnlen(s, REC_UUID_LEN + 1) != REC_UUID_LEN) {
        return false;
    }
    for (int k = 0; k < REC_UUID_LEN; k++) {
        const char c = s[k];
        const bool dash = k == 8 || k == 13 || k == 18 || k == 23;
        if (dash ? c != '-' : !((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f'))) {
            return false;
        }
    }
    return s[14] == '4' && strchr("89ab", s[19]) != NULL;
}

static void quantity(jw_t *w, const char *key, bool has, double x, int dec, double lo, double hi,
                     const char *unit) {
    jw_key(w, key);
    jw_raw(w, "{\"value\":");
    if (has) {
        jw_num(w, x, dec, lo, hi);
    } else {
        jw_raw(w, "null");
    }
    jw_fmt(w, ",\"unit\":\"%s\"", unit);
}

size_t serialize_measurement(const node_identity_t *id, const measurement_record_t *m, char *buf,
                             size_t len) {
    if (buf == NULL || len == 0 || !uuid_ok(m->message_id) || !uuid_ok(m->boot_id) ||
        !uuid_ok(m->counter_id) || m->quality > QUALITY_INVALID) {
        return 0;
    }
    if (m->flags >> QF_COUNT) {
        return 0; // unknown flag bits
    }
    jw_t w = {.buf = buf, .len = len, .ok = true};
    const bool has = m->quality != QUALITY_INVALID; // invalid: null, never last values
    jw_raw(&w, "{\"schema_version\":\"1.0.0\",\"message_id\":");
    jw_str(&w, m->message_id);
    jw_raw(&w, ",\"node_id\":");
    jw_str(&w, id->node_id);
    jw_raw(&w, ",\"circuit_id\":");
    jw_str(&w, id->circuit_id);
    jw_raw(&w, ",\"boot_id\":");
    jw_str(&w, m->boot_id);
    jw_fmt(&w, ",\"sequence\":%" PRIu64, m->sequence);
    jw_raw(&w, ",\"window\":{\"start\":");
    jw_time(&w, m->window_start_ms);
    jw_raw(&w, ",\"end\":");
    jw_time(&w, m->window_end_ms);
    jw_fmt(&w, ",\"duration_ms\":%" PRIu32 ",\"sample_count\":%" PRIu32 "}", m->duration_ms,
           m->sample_count);
    jw_fmt(&w, ",\"clock\":{\"source\":\"%s\",\"last_sync_age_s\":",
           clock_source_name(m->clock_source));
    if (m->last_sync_age_s < 0) {
        jw_raw(&w, "null}");
    } else {
        jw_fmt(&w, "%" PRId64 "}", m->last_sync_age_s);
    }
    jw_raw(&w, ",\"measurements\":{");
    quantity(&w, "voltage_rms", has, m->v_rms_v, 3, 0.0, 300.0, "V");
    jw_raw(&w, "},");
    quantity(&w, "current_rms", has, m->i_rms_a, 4, 0.0, 20.0, "A");
    jw_raw(&w, "},");
    quantity(&w, "active_power", has, m->active_power_w, 3, -3000.0, 3000.0, "W");
    jw_raw(&w, "},");
    quantity(&w, "active_energy_import_total", has, m->energy_wh, 6, 0.0, 1e12, "Wh");
    jw_raw(&w, ",\"counter_id\":");
    jw_str(&w, m->counter_id);
    jw_raw(&w, "}}");
    jw_fmt(&w, ",\"quality\":{\"state\":\"%s\",\"flags\":[", QUALITY_NAMES[m->quality]);
    bool first = true;
    for (uint32_t k = 0; k < QF_COUNT; k++) {
        if (m->flags & (1u << k)) {
            jw_raw(&w, first ? "" : ",");
            jw_str(&w, quality_flag_name(1u << k));
            first = false;
        }
    }
    jw_raw(&w, "],\"valid_sample_ratio\":");
    jw_num(&w, m->valid_sample_ratio, 4, 0.0, 1.0);
    jw_raw(&w, ",\"calibration_revision\":");
    jw_str_or_null(&w, m->calibration_revision);
    jw_fmt(&w, "},\"uptime_ms\":%" PRIu64 "}", m->uptime_ms);
    return w.ok ? w.pos : 0;
}

static const char *NODE_STATES[] = {"online", "degraded", "offline"};
static const char *ACQ_STATES[] = {"sampling", "degraded", "stopped"};

size_t serialize_status(const node_identity_t *id, const status_record_t *s, char *buf,
                        size_t len) {
    if (buf == NULL || len == 0 || id->boot_id == NULL || !uuid_ok(id->boot_id) ||
        s->state > NODE_OFFLINE || s->acquisition_state > ACQ_STOPPED ||
        s->pending_records > 65535) {
        return 0;
    }
    jw_t w = {.buf = buf, .len = len, .ok = true};
    jw_raw(&w, "{\"schema_version\":\"1.0.0\",\"node_id\":");
    jw_str(&w, id->node_id);
    jw_raw(&w, ",\"boot_id\":");
    jw_str(&w, id->boot_id);
    jw_raw(&w, ",\"observed_at\":");
    jw_time(&w, s->observed_at_ms);
    jw_fmt(&w, ",\"state\":\"%s\",\"firmware_version\":", NODE_STATES[s->state]);
    jw_str(&w, id->firmware_version);
    jw_raw(&w, ",\"hardware_revision\":");
    jw_str(&w, id->hardware_revision);
    jw_raw(&w, ",\"calibration_revision\":");
    jw_str_or_null(&w, s->calibration_revision);
    jw_fmt(&w, ",\"clock_source\":\"%s\",\"acquisition_state\":\"%s\"",
           clock_source_name(s->clock_source), ACQ_STATES[s->acquisition_state]);
    jw_fmt(&w, ",\"pending_records\":%" PRIu32 ",\"oldest_pending_age_s\":%" PRId64,
           s->pending_records, s->oldest_pending_age_s < 0 ? 0 : s->oldest_pending_age_s);
    jw_raw(&w, ",\"last_valid_window_end\":");
    if (s->last_valid_window_end_ms < 0) {
        jw_raw(&w, "null");
    } else {
        jw_time(&w, s->last_valid_window_end_ms);
    }
    jw_raw(&w, ",\"last_error_code\":");
    jw_str_or_null(&w, s->last_error_code);
    jw_raw(&w, "}");
    return w.ok ? w.pos : 0;
}

static const char *EVENT_TYPES[] = {"threshold_entered", "threshold_cleared",
                                    "measurement_quality_changed"};
static const char *SEVERITIES[] = {"info", "warning", "critical"};

size_t serialize_event(const node_identity_t *id, const event_record_t *e, char *buf, size_t len) {
    if (buf == NULL || len == 0 || id->boot_id == NULL || !uuid_ok(id->boot_id) ||
        !uuid_ok(e->event_id) || e->type > EVENT_MEASUREMENT_QUALITY_CHANGED ||
        e->severity > SEVERITY_CRITICAL || e->quality > QUALITY_INVALID || e->config_version < 1) {
        return 0;
    }
    jw_t w = {.buf = buf, .len = len, .ok = true};
    jw_raw(&w, "{\"schema_version\":\"1.0.0\",\"event_id\":");
    jw_str(&w, e->event_id);
    jw_raw(&w, ",\"node_id\":");
    jw_str(&w, id->node_id);
    jw_raw(&w, ",\"circuit_id\":");
    jw_str(&w, id->circuit_id);
    jw_raw(&w, ",\"boot_id\":");
    jw_str(&w, id->boot_id);
    jw_fmt(&w, ",\"sequence\":%" PRIu64 ",\"observed_at\":", e->sequence);
    jw_time(&w, e->observed_at_ms);
    jw_fmt(&w, ",\"event_type\":\"%s\",\"severity\":\"%s\",\"config_version\":%" PRIu32,
           EVENT_TYPES[e->type], SEVERITIES[e->severity], e->config_version);
    jw_raw(&w, ",\"measured_value\":");
    if (e->has_measured) {
        jw_num(&w, e->measured_value, 3, -1e9, 1e9);
    } else {
        jw_raw(&w, "null");
    }
    jw_raw(&w, ",\"threshold_value\":");
    if (e->has_threshold) {
        jw_num(&w, e->threshold_value, 3, 0.0, 1e9);
    } else {
        jw_raw(&w, "null");
    }
    jw_fmt(&w, ",\"unit\":\"%s\",\"quality\":\"%s\",\"local_warning_active\":%s",
           e->unit_watts ? "W" : "none", QUALITY_NAMES[e->quality],
           e->local_warning_active ? "true" : "false");
    jw_raw(&w, ",\"reason_code\":");
    jw_str_or_null(&w, e->reason_code);
    jw_raw(&w, "}");
    return w.ok ? w.pos : 0;
}
