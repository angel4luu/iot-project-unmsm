#include "calibration.h"

#include <math.h>
#include <stdio.h>
#include <string.h>

const cal_frontend_t CAL_FRONTEND_NOMINAL = {
    .r1_ohm = 100000.0,
    .r2_ohm = 4700.0,
    .r3_ohm = 4700.0,
    .r4_ohm = 10000.0,
    .sensitivity_mv_per_a = 100.0,
    .acs_zero_mv = 2500.0,
    .bias_mv = 1650.0,
    .current_delay_conversions = 1.0,
    .zero_noise_current_a = 0.05,
};

#define HEAD_KEY "cal_head"

uint32_t cal_crc32(const void *data, size_t len) {
    const uint8_t *p = data;
    uint32_t crc = 0xFFFFFFFFu;
    for (size_t i = 0; i < len; i++) {
        crc ^= p[i];
        for (int k = 0; k < 8; k++) {
            crc = (crc >> 1) ^ (0xEDB88320u & (0u - (crc & 1u)));
        }
    }
    return ~crc;
}

static uint32_t crc_of(const calibration_t *c) {
    return cal_crc32(c, offsetof(calibration_t, crc));
}

void calibration_nominal(calibration_t *c, const cal_frontend_t *fe) {
    memset(c, 0, sizeof(*c)); // also zeroes padding, so the CRC is deterministic
    const double divider_i = fe->r4_ohm / (fe->r3_ohm + fe->r4_ohm);
    c->layout = CAL_LAYOUT_VERSION;
    c->kind = CAL_KIND_NOMINAL;
    c->voltage_gain = (fe->r1_ohm + fe->r2_ohm) / fe->r2_ohm;
    c->current_gain = 1000.0 / (fe->sensitivity_mv_per_a * divider_i);
    c->phase_correction_pairs = fe->current_delay_conversions / 2.0;
    c->current_sign = 1;
    c->current_zero_mv = fe->acs_zero_mv * divider_i;
    c->voltage_bias_mv = fe->bias_mv;
    c->zero_noise_current_a = fe->zero_noise_current_a;
    c->frozen = false;
    c->crc = crc_of(c);
}

bool calibration_accepted(const calibration_t *c) {
    return c != NULL && c->frozen && c->revision[0] != '\0';
}

// ---- offset capture --------------------------------------------------------------

void cal_offset_begin(cal_offset_capture_t *cap) {
    memset(cap, 0, sizeof(*cap));
}

void cal_offset_add(cal_offset_capture_t *cap, uint16_t i_mv) {
    cap->n++;
    cap->sum += i_mv;
    cap->sumsq += (double)i_mv * i_mv;
}

cal_offset_result_t cal_offset_finish(const cal_offset_capture_t *cap, uint32_t pairs_per_s,
                                      calibration_t *c) {
    const double needed = 0.99 * (double)pairs_per_s * CAL_OFFSET_CAPTURE_S;
    if ((double)cap->n < needed) {
        return CAL_OFFSET_TOO_SHORT;
    }
    const double n = (double)cap->n;
    const double mean = cap->sum / n;
    if (fabs(mean - c->current_zero_mv) > CAL_OFFSET_MAX_SHIFT_MV) {
        return CAL_OFFSET_DISCONNECTED;
    }
    double var = cap->sumsq / n - mean * mean;
    var = var > 0.0 ? var : 0.0;
    const double sigma_a = sqrt(var) / 1000.0 * c->current_gain;
    c->current_zero_mv = mean;
    if (3.0 * sigma_a > c->zero_noise_current_a) {
        c->zero_noise_current_a = 3.0 * sigma_a;
    }
    c->crc = crc_of(c);
    return CAL_OFFSET_OK;
}

bool cal_correct_sign(calibration_t *c, double measured_power_w, double min_power_w) {
    if (c->frozen || !(measured_power_w < -fabs(min_power_w))) {
        return false;
    }
    c->current_sign = -c->current_sign;
    c->crc = crc_of(c);
    return true;
}

// ---- append-only storage -----------------------------------------------------------

static void key_for(uint32_t n, char *key, size_t len) {
    snprintf(key, len, "cal_r%u", (unsigned)n);
}

uint32_t calibration_revision_count(const nvs_port_t *nvs) {
    uint32_t head = 0;
    size_t len = sizeof(head);
    if (nvs->get_blob(nvs->ctx, HEAD_KEY, &head, &len) != NVS_PORT_OK || len != sizeof(head)) {
        return 0;
    }
    return head;
}

static bool node_ok(const char *node_id) {
    if (node_id == NULL || node_id[0] == '\0') {
        return false;
    }
    return strlen(node_id) <= CAL_NODE_ID_MAX;
}

cal_store_result_t calibration_freeze(const nvs_port_t *nvs, const char *node_id,
                                      calibration_t *c) {
    if (c->frozen) {
        return CAL_STORE_FROZEN;
    }
    if (!node_ok(node_id)) {
        return CAL_STORE_BAD_NODE;
    }
    const uint32_t next = calibration_revision_count(nvs) + 1u;
    if (next > CAL_MAX_REVISIONS) {
        return CAL_STORE_FULL;
    }
    char key[16];
    key_for(next, key, sizeof(key));
    calibration_t probe;
    size_t len = sizeof(probe);
    if (nvs->get_blob(nvs->ctx, key, &probe, &len) != NVS_PORT_NOT_FOUND) {
        return CAL_STORE_EXISTS;
    }
    calibration_t frozen = *c;
    frozen.revision_number = next;
    memset(frozen.revision, 0, sizeof(frozen.revision));
    snprintf(frozen.revision, sizeof(frozen.revision), "%s-%s-r%u", node_id,
             frozen.kind == CAL_KIND_NOMINAL ? "nominal" : "reference", (unsigned)next);
    frozen.frozen = true;
    frozen.crc = crc_of(&frozen);
    // Revision first, head second: a power loss in between leaves the head on the
    // previous revision and the orphan key is reported as CAL_STORE_EXISTS later.
    if (nvs->set_blob(nvs->ctx, key, &frozen, sizeof(frozen)) != NVS_PORT_OK ||
        nvs->set_blob(nvs->ctx, HEAD_KEY, &next, sizeof(next)) != NVS_PORT_OK ||
        nvs->commit(nvs->ctx) != NVS_PORT_OK) {
        return CAL_STORE_NVS_ERROR;
    }
    *c = frozen;
    return CAL_STORE_OK;
}

bool calibration_load(const nvs_port_t *nvs, uint32_t revision_number, calibration_t *out) {
    char key[16];
    key_for(revision_number, key, sizeof(key));
    calibration_t c;
    size_t len = sizeof(c);
    if (nvs->get_blob(nvs->ctx, key, &c, &len) != NVS_PORT_OK || len != sizeof(c)) {
        return false;
    }
    if (c.layout != CAL_LAYOUT_VERSION || c.crc != crc_of(&c) || !c.frozen ||
        c.revision_number != revision_number ||
        memchr(c.revision, '\0', sizeof(c.revision)) == NULL) {
        return false;
    }
    *out = c;
    return true;
}

bool calibration_load_latest(const nvs_port_t *nvs, calibration_t *out) {
    const uint32_t head = calibration_revision_count(nvs);
    return head > 0 && calibration_load(nvs, head, out);
}
