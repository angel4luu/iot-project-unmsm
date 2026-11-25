#include "metering.h"

#include <math.h>
#include <string.h>

// ---- 1 s block ------------------------------------------------------------------------

void metering_block_reset(metering_block_t *b) {
    memset(b, 0, sizeof(*b));
}

void metering_block_add(metering_block_t *b, uint16_t v_mv, uint16_t i_mv) {
    if (v_mv <= METERING_ADC_MIN_MV || v_mv >= METERING_ADC_MAX_MV || i_mv <= METERING_ADC_MIN_MV ||
        i_mv >= METERING_ADC_MAX_MV) {
        b->clipped = true;
    }
    const double v = v_mv, i = i_mv;
    b->pairs++;
    b->sv += v;
    b->si += i;
    b->svv += v * v;
    b->sii += i * i;
    if (b->have_prev) {
        const double ip = b->prev_i;
        b->products++;
        b->svi += v * i;
        b->svi_prev += v * ip;
        b->sv_p += v;
        b->si_p += i;
        b->sip_p += ip;
    }
    b->prev_i = i_mv;
    b->have_prev = true;
}

void metering_block_gap(metering_block_t *b) {
    b->gaps++;
    b->have_prev = false; // no interpolation across lost conversions
}

static double rms_mv(double sum, double sumsq, double n) {
    const double mean = sum / n;
    const double var = sumsq / n - mean * mean;
    return var > 0.0 ? sqrt(var) : 0.0;
}

bool metering_block_finish(const metering_block_t *b, const calibration_t *cal,
                           metering_block_result_t *out) {
    memset(out, 0, sizeof(*out));
    if (b->pairs == 0) {
        return false;
    }
    const double n = b->pairs;
    const double mv = b->sv / n, mi = b->si / n;
    const double kv = cal->voltage_gain / 1000.0;                     // V per mV
    const double ki = cal->current_sign * cal->current_gain / 1000.0; // A per mV
    out->pairs = b->pairs;
    out->sample_gap = b->gaps > 0;
    out->adc_clipped = b->clipped;
    out->v_mean_mv = mv;
    out->i_mean_mv = mi;
    out->v_rms_v = rms_mv(b->sv, b->svv, n) * kv;
    out->i_rms_a = rms_mv(b->si, b->sii, n) * fabs(ki);
    if (b->products > 0) {
        // mean over P of (v - mv) * (i_al - mi), expanded into the streamed sums.
        const double d = cal->phase_correction_pairs;
        const double p = b->products;
        const double s_vi = (1.0 - d) * b->svi + d * b->svi_prev;
        const double s_i = (1.0 - d) * b->si_p + d * b->sip_p;
        const double mean_prod = (s_vi - mi * b->sv_p - mv * s_i + p * mv * mi) / p;
        out->active_power_w = mean_prod * kv * ki;
        out->power_valid = true;
    }
    return true;
}

// ---- 5 s summary ------------------------------------------------------------------------

void metering_summary_reset(metering_summary_t *s) {
    memset(s, 0, sizeof(*s));
    s->expected_pairs = METERING_PAIRS_PER_S * METERING_BLOCKS_PER_SUMMARY;
}

void metering_summary_add(metering_summary_t *s, const metering_block_result_t *b,
                          const calibration_t *cal) {
    const double w = b->pairs;
    s->blocks++;
    s->pairs += b->pairs;
    s->sample_gap = s->sample_gap || b->sample_gap;
    s->adc_clipped = s->adc_clipped || b->adc_clipped;
    s->any_power_invalid = s->any_power_invalid || !b->power_valid;
    s->w_vv += w * b->v_rms_v * b->v_rms_v;
    s->w_ii += w * b->i_rms_a * b->i_rms_a;
    s->w_p += w * b->active_power_w;
    const double di = fabs(b->i_mean_mv - cal->current_zero_mv);
    const double dv = fabs(b->v_mean_mv - cal->voltage_bias_mv);
    s->i_mean_max_dev_mv = di > s->i_mean_max_dev_mv ? di : s->i_mean_max_dev_mv;
    s->v_mean_max_dev_mv = dv > s->v_mean_max_dev_mv ? dv : s->v_mean_max_dev_mv;
}

bool metering_summary_finish(const metering_summary_t *s, metering_values_t *out) {
    memset(out, 0, sizeof(*out));
    if (s->pairs == 0) {
        out->sample_gap = true;
        return false;
    }
    const double n = s->pairs;
    out->sample_count = s->pairs;
    double ratio = n / (double)s->expected_pairs;
    out->valid_sample_ratio = ratio > 1.0 ? 1.0 : ratio;
    out->sample_gap =
        s->sample_gap || s->any_power_invalid || s->blocks < METERING_BLOCKS_PER_SUMMARY;
    out->adc_clipped = s->adc_clipped;
    out->v_rms_v = sqrt(s->w_vv / n);
    out->i_rms_a = sqrt(s->w_ii / n);
    out->active_power_w = s->w_p / n;
    out->i_offset_dev_mv = s->i_mean_max_dev_mv;
    out->v_offset_dev_mv = s->v_mean_max_dev_mv;
    return true;
}

// ---- energy ----------------------------------------------------------------------------

void energy_add(energy_counter_t *e, double active_power_w, int64_t dt_us) {
    if (dt_us <= 0 || !(active_power_w > 0.0) || !isfinite(active_power_w)) {
        return; // negative, zero, NaN power or a non-positive interval adds nothing
    }
    e->total_wh += active_power_w * ((double)dt_us / 1e6) / 3600.0;
}
