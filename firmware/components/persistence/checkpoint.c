#include "checkpoint.h"

#include <string.h>

#include "calibration.h" // cal_crc32

#define LAYOUT 1u

typedef struct {
    uint32_t layout;
    uint32_t seq;
    char counter_id[METERING_UUID_LEN + 1];
    uint8_t clean;
    double total_wh;
    uint32_t crc;
} record_t;

static const char *const KEYS[2] = {"ekp_a", "ekp_b"};

static uint32_t crc_of(const record_t *r) {
    return cal_crc32(r, offsetof(record_t, crc));
}

static bool uuid_ok(const char *s) {
    if (strnlen(s, METERING_UUID_LEN + 1) != METERING_UUID_LEN) {
        return false;
    }
    for (int k = 0; k < METERING_UUID_LEN; k++) {
        const char c = s[k];
        const bool dash = (k == 8 || k == 13 || k == 18 || k == 23);
        if (dash ? c != '-' : !((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f'))) {
            return false;
        }
    }
    return true;
}

static bool load(const nvs_port_t *nvs, const char *key, record_t *r) {
    size_t len = sizeof(*r);
    if (nvs->get_blob(nvs->ctx, key, r, &len) != NVS_PORT_OK || len != sizeof(*r)) {
        return false;
    }
    return r->layout == LAYOUT && r->crc == crc_of(r) && uuid_ok(r->counter_id) &&
           r->total_wh >= 0.0 && r->total_wh == r->total_wh; // rejects NaN
}

static bool write_record(const nvs_port_t *nvs, checkpoint_state_t *st, const energy_counter_t *e,
                         bool clean) {
    record_t r;
    memset(&r, 0, sizeof(r));
    r.layout = LAYOUT;
    r.seq = st->next_seq;
    memcpy(r.counter_id, e->counter_id, sizeof(r.counter_id));
    r.counter_id[METERING_UUID_LEN] = '\0';
    r.clean = clean ? 1u : 0u;
    r.total_wh = e->total_wh;
    r.crc = crc_of(&r);
    if (nvs->set_blob(nvs->ctx, KEYS[r.seq & 1u], &r, sizeof(r)) != NVS_PORT_OK ||
        nvs->commit(nvs->ctx) != NVS_PORT_OK) {
        return false;
    }
    st->next_seq++;
    return true;
}

checkpoint_restore_t checkpoint_restore(const nvs_port_t *nvs, checkpoint_state_t *st,
                                        energy_counter_t *out, checkpoint_uuid_fn uuid,
                                        void *uuid_ctx, int64_t now_us) {
    record_t a, b;
    const bool ok_a = load(nvs, KEYS[0], &a);
    const bool ok_b = load(nvs, KEYS[1], &b);
    const record_t *best = NULL;
    if (ok_a && ok_b) {
        best = (b.seq > a.seq) ? &b : &a;
    } else if (ok_a) {
        best = &a;
    } else if (ok_b) {
        best = &b;
    }
    checkpoint_restore_t result;
    memset(out, 0, sizeof(*out));
    if (best == NULL) {
        uuid(out->counter_id, uuid_ctx);
        out->counter_id[METERING_UUID_LEN] = '\0';
        out->total_wh = 0.0;
        st->next_seq = 0;
        result = CHECKPOINT_NEW_COUNTER;
    } else {
        memcpy(out->counter_id, best->counter_id, sizeof(out->counter_id));
        out->total_wh = best->total_wh;
        st->next_seq = best->seq + 1u;
        result = best->clean ? CHECKPOINT_RESUMED_CLEAN : CHECKPOINT_RESUMED_UNCLEAN;
    }
    // Mark the run as started: a crash from here on is detected at the next boot.
    (void)write_record(nvs, st, out, false);
    st->last_save_us = now_us;
    return result;
}

bool checkpoint_save(const nvs_port_t *nvs, checkpoint_state_t *st, const energy_counter_t *e,
                     bool clean, bool force, int64_t now_us) {
    if (!force && now_us - st->last_save_us < CHECKPOINT_INTERVAL_US) {
        return true;
    }
    if (!write_record(nvs, st, e, clean)) {
        return false;
    }
    st->last_save_us = now_us;
    return true;
}
