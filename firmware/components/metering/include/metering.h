// Metering (T045; plan › Quantities and aggregation).
//
// One-second blocks of paired samples (4,000 pairs/s) are combined into a 5 s
// summary (20,000 pairs). Per block, each channel's offset is its mean over the
// block (60 whole cycles at 60 Hz), so a drifting ACS712 zero or bias does not
// bias RMS or power. Active power is the mean of v*i after aligning each current
// sample to its voltage instant (FR-003); it is never Vrms*Irms.
//
// Streaming sums only: no sample buffer, O(1) per pair, so the same code runs on
// the ESP32-S3 and in the host tests against the T096 reference values.
#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "calibration.h"

#define METERING_PAIRS_PER_S 4000u
#define METERING_BLOCKS_PER_SUMMARY 5u
#define METERING_ADC_MIN_MV 0u    // rail values mean clipping
#define METERING_ADC_MAX_MV 3100u // ADC1 at 12 dB, calibrated full scale

typedef struct {
    uint32_t pairs;    // pairs accumulated
    uint32_t products; // pairs with a usable predecessor (phase interpolation)
    uint32_t gaps;     // gap events (lost conversions)
    bool clipped;      // any sample at a rail
    double sv, si;     // sums of raw mV
    double svv, sii;   // sums of squares
    // Product set (pairs with a contiguous predecessor). With the aligned current
    // i_al = (1 - d) * i + d * i_prev, where d comes from the calibration:
    double svi, svi_prev;     // sums of v * i and v * i_prev
    double sv_p, si_p, sip_p; // sums of v, i and i_prev
    uint16_t prev_i;
    bool have_prev;
} metering_block_t;

typedef struct {
    uint32_t pairs;
    bool sample_gap;
    bool adc_clipped;
    double v_mean_mv, i_mean_mv; // channel offsets seen at the pin (diagnostics)
    double v_rms_v, i_rms_a, active_power_w;
    bool power_valid; // false when no product could be formed
} metering_block_result_t;

void metering_block_reset(metering_block_t *b);
void metering_block_add(metering_block_t *b, uint16_t v_mv, uint16_t i_mv);
// Conversions were lost: the next pair is not contiguous with the previous one.
void metering_block_gap(metering_block_t *b);
// False when the block is empty.
bool metering_block_finish(const metering_block_t *b, const calibration_t *cal,
                           metering_block_result_t *out);

// ---- 5 s summary ------------------------------------------------------------------------

typedef struct {
    uint32_t blocks;
    uint32_t pairs;
    uint32_t expected_pairs;
    bool sample_gap, adc_clipped, any_power_invalid;
    double w_vv, w_ii, w_p; // pair-weighted Vrms^2, Irms^2, P
    double v_mean_mv, i_mean_mv;
    double i_mean_max_dev_mv, v_mean_max_dev_mv; // worst block offset vs calibration
} metering_summary_t;

typedef struct {
    uint32_t sample_count;
    double valid_sample_ratio;
    bool sample_gap, adc_clipped;
    double v_rms_v, i_rms_a, active_power_w;
    double i_offset_dev_mv, v_offset_dev_mv; // largest |block mean - calibrated zero|
} metering_values_t;

void metering_summary_reset(metering_summary_t *s);
void metering_summary_add(metering_summary_t *s, const metering_block_result_t *b,
                          const calibration_t *cal);
bool metering_summary_finish(const metering_summary_t *s, metering_values_t *out);

// ---- imported energy ---------------------------------------------------------------------

#define METERING_UUID_LEN 36

typedef struct {
    char counter_id[METERING_UUID_LEN + 1];
    double total_wh;
} energy_counter_t;

// Adds max(power, 0) * dt / 3600 (Wh). `dt_us` is monotonic time, never wall clock,
// so an SNTP step cannot add or remove energy. Negative power never decrements.
void energy_add(energy_counter_t *e, double active_power_w, int64_t dt_us);
