// Quality classification and flags (T046; data-model › Measurement invariants).
//
// `valid` requires all four values, an accepted calibration, a synchronized or
// holdover clock, none of the flags below, and valid_sample_ratio >= 0.99.
//
// Flags that make a window `invalid` (values are null; the last valid values are
// never copied in): sample_gap, adc_crc_error, adc_clipped, sensor_disconnected,
// and a valid_sample_ratio below 0.99.
// Flags that make it `degraded` (values kept for diagnosis only): out_of_range,
// polarity_reversed, clock_unsynchronized, calibration_missing,
// energy_continuity_uncertain.
//
// Ranges (plan B): 10-16 V RMS and 0.5-2.0 A RMS. A current below the absolute
// noise limit is "no load" (bulb off), not out of range; power is then not
// checked for polarity.
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

typedef enum {
    QUALITY_VALID = 0,
    QUALITY_DEGRADED,
    QUALITY_INVALID,
} quality_state_t;

// Bit order is the schema's enum order (measurement.schema.json quality.flags).
enum {
    QF_CLOCK_UNSYNCHRONIZED = 1u << 0,
    QF_CALIBRATION_MISSING = 1u << 1,
    QF_SAMPLE_GAP = 1u << 2,
    QF_ADC_CRC_ERROR = 1u << 3,
    QF_ADC_CLIPPED = 1u << 4,
    QF_SENSOR_DISCONNECTED = 1u << 5,
    QF_OUT_OF_RANGE = 1u << 6,
    QF_POLARITY_REVERSED = 1u << 7,
    QF_ENERGY_CONTINUITY_UNCERTAIN = 1u << 8,
};
#define QF_COUNT 9u
#define QF_INVALIDATING (QF_SAMPLE_GAP | QF_ADC_CRC_ERROR | QF_ADC_CLIPPED | QF_SENSOR_DISCONNECTED)

typedef struct {
    double v_min_v, v_max_v;  // calibrated voltage range
    double i_min_a, i_max_a;  // calibrated current range
    double min_valid_ratio;   // 0.99
    double disconnect_dev_mv; // block offset this far from calibration: disconnected
} quality_limits_t;

extern const quality_limits_t QUALITY_LIMITS_PLAN_B;

typedef struct {
    // From metering
    bool sample_gap, adc_crc_error, adc_clipped;
    double valid_sample_ratio;
    double v_rms_v, i_rms_a, active_power_w;
    double i_offset_dev_mv, v_offset_dev_mv;
    // Context
    bool calibration_accepted;
    double zero_noise_current_a;
    bool clock_unsynchronized; // holdover is permitted and raises no flag
    bool energy_continuity_uncertain;
} quality_input_t;

typedef struct {
    quality_state_t state;
    uint32_t flags;
} quality_result_t;

quality_result_t quality_classify(const quality_input_t *in, const quality_limits_t *lim);
const char *quality_state_name(quality_state_t s);
// Schema name of one flag bit, or NULL.
const char *quality_flag_name(uint32_t bit);
// Writes the set flags as a comma-separated list in schema order ("" when none);
// returns the length, or 0 with an empty buffer when it does not fit.
size_t quality_flags_join(uint32_t flags, char *buf, size_t len);
// Short reason for local display: the most serious flag, or "" when valid.
const char *quality_reason(uint32_t flags);
