#include "threshold.h"

#include <math.h>
#include <string.h>

void threshold_init(threshold_t *t) {
    memset(t, 0, sizeof(*t));
    t->state = THR_NORMAL;
    t->last_quality = QUALITY_VALID;
    t->last_valid_w = NAN;
}

void threshold_set_config(threshold_t *t, const thr_config_t *cfg) {
    t->cfg = *cfg;
    t->configured = true;
    if (t->state == THR_PENDING) {
        t->state = THR_NORMAL; // confirmation restarts under the new limit
        t->elapsed_ms = 0;
    }
}

bool threshold_warning_active(const threshold_t *t) {
    return t->configured && t->cfg.local_warning_enabled &&
           (t->state == THR_FIRING || t->state == THR_CLEARING);
}

const char *threshold_state_name(thr_state_t s) {
    switch (s) {
    case THR_NORMAL:
        return "normal";
    case THR_PENDING:
        return "pending";
    case THR_FIRING:
        return "firing";
    case THR_CLEARING:
        return "clearing";
    }
    return "normal";
}

static event_record_t *add_event(const threshold_t *t, thr_events_t *out, event_type_t type) {
    event_record_t *e = &out->ev[out->count++];
    memset(e, 0, sizeof(*e));
    e->type = type;
    e->config_version = t->cfg.config_version;
    return e;
}

static void quality_event(const threshold_t *t, const thr_block_t *b, thr_events_t *out) {
    event_record_t *e = add_event(t, out, EVENT_MEASUREMENT_QUALITY_CHANGED);
    const bool restored = b->quality == QUALITY_VALID;
    e->severity = restored ? SEVERITY_INFO : SEVERITY_WARNING;
    e->quality = b->quality;
    e->has_measured = false; // a non-valid block has no value; never 0 W
    e->has_threshold = false;
    e->unit_watts = false;
    e->reason_code = restored ? "quality_restored" : (b->reason != NULL ? b->reason : "invalid");
}

static void threshold_event(threshold_t *t, const thr_block_t *b, thr_events_t *out,
                            event_type_t type) {
    event_record_t *e = add_event(t, out, type);
    const bool entered = type == EVENT_THRESHOLD_ENTERED;
    e->severity = entered ? t->cfg.severity : SEVERITY_INFO;
    e->quality = b->quality; // `degraded` when an over-range block confirmed it
    e->has_measured = true;
    e->measured_value = b->power_w;
    e->has_threshold = true;
    e->threshold_value = entered ? t->cfg.limit_w : t->cfg.clear_below_w;
    e->unit_watts = true;
    e->local_warning_active = threshold_warning_active(t);
    e->reason_code = NULL;
}

void threshold_step(threshold_t *t, const thr_block_t *b, thr_events_t *out) {
    out->count = 0;
    if (!t->configured) {
        return;
    }
    const bool valid = b->quality == QUALITY_VALID && isfinite(b->power_w);
    const quality_state_t q =
        valid ? QUALITY_VALID : (b->quality == QUALITY_VALID ? QUALITY_INVALID : b->quality);
    if (q != t->last_quality) {
        thr_block_t qb = *b;
        qb.quality = q;
        quality_event(t, &qb, out);
        t->last_quality = q;
    }
    // FR-012 overload exception: above the limit, so it can only confirm or sustain.
    const bool overload = !valid && b->over_range_high && b->quality == QUALITY_DEGRADED &&
                          isfinite(b->power_w) && b->power_w > t->cfg.limit_w;
    if (!valid && !overload) {
        // Never confirms and never clears: pending gives up, firing/clearing pause.
        if (t->state == THR_PENDING) {
            t->state = THR_NORMAL;
            t->elapsed_ms = 0;
        }
        return;
    }
    if (valid) {
        t->last_valid_w = b->power_w;
    }
    const double p = b->power_w;
    switch (t->state) {
    case THR_NORMAL:
        if (p > t->cfg.limit_w) {
            t->state = THR_PENDING;
            t->elapsed_ms = 0;
        } else {
            break;
        }
        __attribute__((fallthrough)); // this block counts toward confirmation
    case THR_PENDING:
        if (!(p > t->cfg.limit_w)) {
            t->state = THR_NORMAL;
            t->elapsed_ms = 0;
            break;
        }
        t->elapsed_ms += b->duration_ms;
        if (t->elapsed_ms >= t->cfg.confirm_ms) {
            t->state = THR_FIRING;
            t->elapsed_ms = 0;
            threshold_event(t, b, out, EVENT_THRESHOLD_ENTERED);
        }
        break;
    case THR_FIRING:
        if (p < t->cfg.clear_below_w) {
            t->state = THR_CLEARING;
            t->elapsed_ms = 0;
        } else {
            break;
        }
        __attribute__((fallthrough)); // this block counts toward clearing
    case THR_CLEARING:
        if (!(p < t->cfg.clear_below_w)) {
            t->state = THR_FIRING;
            t->elapsed_ms = 0;
            break;
        }
        t->elapsed_ms += b->duration_ms;
        if (t->elapsed_ms >= t->cfg.clear_ms) {
            t->state = THR_NORMAL; // resolved
            t->elapsed_ms = 0;
            threshold_event(t, b, out, EVENT_THRESHOLD_CLEARED);
        }
        break;
    }
}

thr_block_t threshold_block_from(bool finished, const metering_block_result_t *br,
                                 const calibration_t *cal, uint32_t duration_ms) {
    thr_block_t b = {.quality = QUALITY_INVALID,
                     .power_w = NAN,
                     .duration_ms = duration_ms,
                     .reason = "sample_gap"};
    if (!finished) {
        return b;
    }
    const double expected = (double)METERING_PAIRS_PER_S * duration_ms / 1000.0;
    const quality_input_t qi = {
        .sample_gap = br->sample_gap || !br->power_valid,
        .adc_clipped = br->adc_clipped,
        .valid_sample_ratio = expected > 0.0 ? br->pairs / expected : 0.0,
        .v_rms_v = br->v_rms_v,
        .i_rms_a = br->i_rms_a,
        .active_power_w = br->active_power_w,
        .i_offset_dev_mv = fabs(br->i_mean_mv - cal->current_zero_mv),
        .v_offset_dev_mv = fabs(br->v_mean_mv - cal->voltage_bias_mv),
        .calibration_accepted = calibration_accepted(cal),
        .zero_noise_current_a = cal->zero_noise_current_a,
        .clock_unsynchronized = false, // local evidence does not need wall-clock time
        .energy_continuity_uncertain = false,
    };
    const quality_result_t q = quality_classify(&qi, &QUALITY_LIMITS_PLAN_B);
    b.quality = q.state;
    b.power_w = br->active_power_w;
    b.reason = q.state == QUALITY_VALID ? NULL : quality_reason(q.flags);
    b.over_range_high = q.flags == QF_OUT_OF_RANGE && br->i_rms_a > QUALITY_LIMITS_PLAN_B.i_max_a;
    return b;
}
