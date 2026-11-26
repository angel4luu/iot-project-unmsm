#include <math.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

#include "calibration.h" // cal_crc32, shared by the persistence records
#include "json_scan.h"
#include "threshold_config.h"

#define CFG_KEY "thr_cfg"
#define ID_MAX 32

// Stored record: field by field, so the CRC never covers padding.
typedef struct {
    uint32_t layout;
    uint32_t config_version;
    double limit_w, clear_below_w;
    uint32_t confirm_ms, clear_ms;
    uint32_t severity;
    uint32_t local_warning_enabled;
    uint32_t crc;
} stored_t;

bool threshold_config_valid(const thr_config_t *c) {
    return c->config_version >= 1 && isfinite(c->limit_w) && c->limit_w > 0.0 &&
           c->limit_w <= THR_LIMIT_MAX_W && isfinite(c->clear_below_w) && c->clear_below_w >= 0.0 &&
           c->clear_below_w < c->limit_w && c->confirm_ms >= THR_MS_MIN &&
           c->confirm_ms <= THR_MS_MAX && c->clear_ms >= THR_MS_MIN && c->clear_ms <= THR_MS_MAX &&
           (c->severity == SEVERITY_WARNING || c->severity == SEVERITY_CRITICAL);
}

bool threshold_config_equal(const thr_config_t *a, const thr_config_t *b) {
    return a->config_version == b->config_version && a->limit_w == b->limit_w &&
           a->clear_below_w == b->clear_below_w && a->confirm_ms == b->confirm_ms &&
           a->clear_ms == b->clear_ms && a->severity == b->severity &&
           a->local_warning_enabled == b->local_warning_enabled;
}

thr_cfg_parse_t threshold_config_parse(const char *json, size_t len, const char *node_id,
                                       const char *circuit_id, thr_config_t *out) {
    char schema[8], node[ID_MAX + 1], circuit[ID_MAX + 1], severity[16], effective[40];
    uint64_t version = 0, confirm = THR_CONFIRM_MS_DEFAULT, clear_ms = 0;
    thr_config_t c;
    memset(&c, 0, sizeof c);
    if (json == NULL || len < 2 || json[0] != '{' ||
        !json_string_of(json, len, "schema_version", schema, sizeof schema, NULL) ||
        !json_uint_of(json, len, "config_version", UINT32_MAX, &version) || version < 1 ||
        !json_string_of(json, len, "node_id", node, sizeof node, NULL) ||
        !json_string_of(json, len, "circuit_id", circuit, sizeof circuit, NULL) ||
        !json_string_of(json, len, "effective_at", effective, sizeof effective, NULL) ||
        !json_number_of(json, len, "active_power_limit_W", &c.limit_w) ||
        !json_number_of(json, len, "clear_below_W", &c.clear_below_w) ||
        !json_uint_of(json, len, "clear_ms", UINT32_MAX, &clear_ms) ||
        !json_string_of(json, len, "severity", severity, sizeof severity, NULL) ||
        !json_bool_of(json, len, "local_warning_enabled", &c.local_warning_enabled)) {
        return THR_CFG_BAD_JSON;
    }
    if (json_value_of(json, len, "confirm_ms") != NULL &&
        !json_uint_of(json, len, "confirm_ms", UINT32_MAX, &confirm)) {
        return THR_CFG_BAD_JSON;
    }
    if (strcmp(severity, "warning") == 0) {
        c.severity = SEVERITY_WARNING;
    } else if (strcmp(severity, "critical") == 0) {
        c.severity = SEVERITY_CRITICAL;
    } else {
        return THR_CFG_BAD_JSON;
    }
    if (strcmp(schema, "1.0.0") != 0) {
        return THR_CFG_BAD_SCHEMA;
    }
    if (strcmp(node, node_id) != 0 || strcmp(circuit, circuit_id) != 0) {
        return THR_CFG_WRONG_TARGET;
    }
    c.config_version = (uint32_t)version;
    c.confirm_ms = (uint32_t)confirm;
    c.clear_ms = (uint32_t)clear_ms;
    if (!threshold_config_valid(&c)) {
        return THR_CFG_OUT_OF_BOUNDS;
    }
    *out = c;
    return THR_CFG_OK;
}

static stored_t to_stored(const thr_config_t *c) {
    stored_t s;
    memset(&s, 0, sizeof s);
    s.layout = THR_CONFIG_LAYOUT_VERSION;
    s.config_version = c->config_version;
    s.limit_w = c->limit_w;
    s.clear_below_w = c->clear_below_w;
    s.confirm_ms = c->confirm_ms;
    s.clear_ms = c->clear_ms;
    s.severity = (uint32_t)c->severity;
    s.local_warning_enabled = c->local_warning_enabled ? 1u : 0u;
    s.crc = cal_crc32(&s, offsetof(stored_t, crc));
    return s;
}

bool threshold_config_load(const nvs_port_t *nvs, thr_config_t *out) {
    stored_t s;
    size_t len = sizeof s;
    if (nvs->get_blob(nvs->ctx, CFG_KEY, &s, &len) != NVS_PORT_OK || len != sizeof s ||
        s.layout != THR_CONFIG_LAYOUT_VERSION || s.crc != cal_crc32(&s, offsetof(stored_t, crc)) ||
        s.severity > SEVERITY_CRITICAL || s.local_warning_enabled > 1u) {
        return false;
    }
    thr_config_t c = {
        .config_version = s.config_version,
        .limit_w = s.limit_w,
        .clear_below_w = s.clear_below_w,
        .confirm_ms = s.confirm_ms,
        .clear_ms = s.clear_ms,
        .severity = (event_severity_t)s.severity,
        .local_warning_enabled = s.local_warning_enabled == 1u,
    };
    if (!threshold_config_valid(&c)) {
        return false;
    }
    *out = c;
    return true;
}

thr_cfg_accept_t threshold_config_accept(const nvs_port_t *nvs, const thr_config_t *c) {
    if (!threshold_config_valid(c)) {
        return THR_CFG_INVALID;
    }
    thr_config_t stored;
    if (threshold_config_load(nvs, &stored)) {
        if (threshold_config_equal(&stored, c)) {
            return THR_CFG_UNCHANGED;
        }
        if (c->config_version <= stored.config_version) {
            return THR_CFG_ROLLBACK; // older, or the same version with other content
        }
    }
    const stored_t s = to_stored(c);
    if (nvs->set_blob(nvs->ctx, CFG_KEY, &s, sizeof s) != NVS_PORT_OK ||
        nvs->commit(nvs->ctx) != NVS_PORT_OK) {
        return THR_CFG_NVS_ERROR;
    }
    return THR_CFG_ACCEPTED;
}

const char *threshold_config_result_name(thr_cfg_accept_t r) {
    switch (r) {
    case THR_CFG_ACCEPTED:
        return "accepted";
    case THR_CFG_UNCHANGED:
        return "unchanged";
    case THR_CFG_ROLLBACK:
        return "rollback_rejected";
    case THR_CFG_INVALID:
        return "invalid";
    case THR_CFG_NVS_ERROR:
        return "nvs_error";
    }
    return "invalid";
}
