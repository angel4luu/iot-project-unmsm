#include "quality.h"

#include <math.h>
#include <string.h>

const quality_limits_t QUALITY_LIMITS_PLAN_B = {
    .v_min_v = 10.0,
    .v_max_v = 16.0,
    .i_min_a = 0.5,
    .i_max_a = 2.0,
    .min_valid_ratio = 0.99,
    .disconnect_dev_mv = 200.0,
};

static const char *const FLAG_NAMES[QF_COUNT] = {
    "clock_unsynchronized", "calibration_missing", "sample_gap",
    "adc_crc_error",        "adc_clipped",         "sensor_disconnected",
    "out_of_range",         "polarity_reversed",   "energy_continuity_uncertain",
};

// Most serious first, for the local display.
static const uint32_t REASON_ORDER[QF_COUNT] = {
    QF_SENSOR_DISCONNECTED, QF_ADC_CLIPPED,          QF_SAMPLE_GAP,
    QF_ADC_CRC_ERROR,       QF_OUT_OF_RANGE,         QF_POLARITY_REVERSED,
    QF_CALIBRATION_MISSING, QF_CLOCK_UNSYNCHRONIZED, QF_ENERGY_CONTINUITY_UNCERTAIN,
};

quality_result_t quality_classify(const quality_input_t *in, const quality_limits_t *lim) {
    uint32_t f = 0;
    if (in->sample_gap || !(in->valid_sample_ratio >= lim->min_valid_ratio)) {
        f |= QF_SAMPLE_GAP;
    }
    if (in->adc_crc_error) {
        f |= QF_ADC_CRC_ERROR;
    }
    if (in->adc_clipped) {
        f |= QF_ADC_CLIPPED;
    }
    if (in->i_offset_dev_mv > lim->disconnect_dev_mv ||
        in->v_offset_dev_mv > lim->disconnect_dev_mv) {
        f |= QF_SENSOR_DISCONNECTED;
    }
    const bool finite =
        isfinite(in->v_rms_v) && isfinite(in->i_rms_a) && isfinite(in->active_power_w);
    if (!finite) {
        f |= QF_SAMPLE_GAP; // no computable values: treat like missing samples
    } else {
        const bool no_load = in->i_rms_a < in->zero_noise_current_a;
        if (in->v_rms_v < lim->v_min_v || in->v_rms_v > lim->v_max_v ||
            (!no_load && (in->i_rms_a < lim->i_min_a || in->i_rms_a > lim->i_max_a))) {
            f |= QF_OUT_OF_RANGE;
        }
        if (!no_load && in->active_power_w < 0.0) {
            f |= QF_POLARITY_REVERSED;
        }
    }
    if (!in->calibration_accepted) {
        f |= QF_CALIBRATION_MISSING;
    }
    if (in->clock_unsynchronized) {
        f |= QF_CLOCK_UNSYNCHRONIZED;
    }
    if (in->energy_continuity_uncertain) {
        f |= QF_ENERGY_CONTINUITY_UNCERTAIN;
    }
    quality_result_t r = {.flags = f};
    r.state = (f & QF_INVALIDATING) ? QUALITY_INVALID : (f ? QUALITY_DEGRADED : QUALITY_VALID);
    return r;
}

const char *quality_state_name(quality_state_t s) {
    switch (s) {
    case QUALITY_VALID:
        return "valid";
    case QUALITY_DEGRADED:
        return "degraded";
    case QUALITY_INVALID:
        return "invalid";
    }
    return "invalid";
}

const char *quality_flag_name(uint32_t bit) {
    for (uint32_t k = 0; k < QF_COUNT; k++) {
        if (bit == (1u << k)) {
            return FLAG_NAMES[k];
        }
    }
    return NULL;
}

size_t quality_flags_join(uint32_t flags, char *buf, size_t len) {
    if (len == 0) {
        return 0;
    }
    size_t used = 0;
    buf[0] = '\0';
    for (uint32_t k = 0; k < QF_COUNT; k++) {
        if (!(flags & (1u << k))) {
            continue;
        }
        const char *name = FLAG_NAMES[k];
        const size_t need = strlen(name) + (used ? 1u : 0u);
        if (used + need + 1 > len) {
            buf[0] = '\0';
            return 0;
        }
        if (used) {
            buf[used++] = ',';
        }
        memcpy(buf + used, name, strlen(name) + 1);
        used += strlen(name);
    }
    return used;
}

const char *quality_reason(uint32_t flags) {
    for (uint32_t k = 0; k < QF_COUNT; k++) {
        if (flags & REASON_ORDER[k]) {
            return quality_flag_name(REASON_ORDER[k]);
        }
    }
    return "";
}
