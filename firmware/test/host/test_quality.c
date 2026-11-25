// T036: quality classification (data-model › Measurement invariants).
#include <math.h>
#include <string.h>

#include "quality.h"
#include "unity.h"

static quality_input_t in;

void setUp(void) {
    // A clean bulb-on window: 12.6 V, 1.62 A, 20.4 W, synced, accepted calibration.
    in = (quality_input_t){
        .valid_sample_ratio = 1.0,
        .v_rms_v = 12.6,
        .i_rms_a = 1.62,
        .active_power_w = 20.4,
        .calibration_accepted = true,
        .zero_noise_current_a = 0.05,
    };
}

void tearDown(void) {}

static quality_result_t classify(void) {
    return quality_classify(&in, &QUALITY_LIMITS_PLAN_B);
}

static void test_clean_window_is_valid(void) {
    const quality_result_t q = classify();
    TEST_ASSERT_EQUAL(QUALITY_VALID, q.state);
    TEST_ASSERT_EQUAL_UINT32(0, q.flags);
}

static void test_holdover_clock_is_permitted(void) {
    in.clock_unsynchronized = false; // holdover reports no flag
    TEST_ASSERT_EQUAL(QUALITY_VALID, classify().state);
}

static void test_invalidating_flags(void) {
    in.sample_gap = true;
    TEST_ASSERT_EQUAL(QUALITY_INVALID, classify().state);
    setUp();
    in.adc_clipped = true;
    TEST_ASSERT_EQUAL_UINT32(QF_ADC_CLIPPED, classify().flags);
    TEST_ASSERT_EQUAL(QUALITY_INVALID, classify().state);
    setUp();
    in.adc_crc_error = true;
    TEST_ASSERT_EQUAL(QUALITY_INVALID, classify().state);
    setUp();
    in.i_offset_dev_mv = 900.0; // ACS712 output far from its calibrated zero
    TEST_ASSERT_EQUAL_UINT32(QF_SENSOR_DISCONNECTED, classify().flags);
    TEST_ASSERT_EQUAL(QUALITY_INVALID, classify().state);
}

static void test_ratio_below_099_is_a_gap(void) {
    in.valid_sample_ratio = 0.989;
    const quality_result_t q = classify();
    TEST_ASSERT_EQUAL(QUALITY_INVALID, q.state);
    TEST_ASSERT_TRUE(q.flags & QF_SAMPLE_GAP);
    setUp();
    in.valid_sample_ratio = 0.99;
    TEST_ASSERT_EQUAL(QUALITY_VALID, classify().state);
}

static void test_degrading_flags(void) {
    const struct {
        double v, i, p;
        bool cal, unsync, energy;
        uint32_t want;
    } cases[] = {
        {9.5, 1.62, 20.4, true, false, false, QF_OUT_OF_RANGE},
        {16.5, 1.62, 20.4, true, false, false, QF_OUT_OF_RANGE},
        {12.6, 0.3, 3.8, true, false, false, QF_OUT_OF_RANGE},
        {12.6, 2.4, 30.0, true, false, false, QF_OUT_OF_RANGE},
        {12.6, 1.62, -20.4, true, false, false, QF_POLARITY_REVERSED},
        {12.6, 1.62, 20.4, false, false, false, QF_CALIBRATION_MISSING},
        {12.6, 1.62, 20.4, true, true, false, QF_CLOCK_UNSYNCHRONIZED},
        {12.6, 1.62, 20.4, true, false, true, QF_ENERGY_CONTINUITY_UNCERTAIN},
    };
    for (size_t k = 0; k < sizeof cases / sizeof cases[0]; k++) {
        setUp();
        in.v_rms_v = cases[k].v;
        in.i_rms_a = cases[k].i;
        in.active_power_w = cases[k].p;
        in.calibration_accepted = cases[k].cal;
        in.clock_unsynchronized = cases[k].unsync;
        in.energy_continuity_uncertain = cases[k].energy;
        const quality_result_t q = classify();
        TEST_ASSERT_EQUAL_UINT32_MESSAGE(cases[k].want, q.flags, "flags");
        TEST_ASSERT_EQUAL_MESSAGE(QUALITY_DEGRADED, q.state, "state");
    }
}

static void test_bulb_off_is_no_load_not_out_of_range(void) {
    in.i_rms_a = 0.015; // below the 0.05 A noise limit
    in.active_power_w = -0.002;
    const quality_result_t q = classify();
    TEST_ASSERT_EQUAL(QUALITY_VALID, q.state); // no out_of_range, no polarity flag
}

static void test_non_finite_values_never_valid(void) {
    in.active_power_w = NAN;
    TEST_ASSERT_EQUAL(QUALITY_INVALID, classify().state);
}

static void test_flag_names_follow_the_schema(void) {
    char buf[256];
    TEST_ASSERT_EQUAL_size_t(0, quality_flags_join(0, buf, sizeof buf));
    TEST_ASSERT_EQUAL_STRING("", buf);
    quality_flags_join(QF_SAMPLE_GAP | QF_CLOCK_UNSYNCHRONIZED | QF_ENERGY_CONTINUITY_UNCERTAIN,
                       buf, sizeof buf);
    TEST_ASSERT_EQUAL_STRING("clock_unsynchronized,sample_gap,energy_continuity_uncertain", buf);
    TEST_ASSERT_EQUAL_size_t(0, quality_flags_join(QF_SAMPLE_GAP, buf, 5)); // does not fit
    TEST_ASSERT_EQUAL_STRING("", buf);
    TEST_ASSERT_EQUAL_STRING("adc_crc_error", quality_flag_name(QF_ADC_CRC_ERROR));
    TEST_ASSERT_NULL(quality_flag_name(3u));
}

static void test_reason_is_the_most_serious_flag(void) {
    TEST_ASSERT_EQUAL_STRING("", quality_reason(0));
    TEST_ASSERT_EQUAL_STRING("sensor_disconnected",
                             quality_reason(QF_CLOCK_UNSYNCHRONIZED | QF_SENSOR_DISCONNECTED));
    TEST_ASSERT_EQUAL_STRING("out_of_range",
                             quality_reason(QF_OUT_OF_RANGE | QF_CALIBRATION_MISSING));
}

int main(void) {
    UNITY_BEGIN();
    RUN_TEST(test_clean_window_is_valid);
    RUN_TEST(test_holdover_clock_is_permitted);
    RUN_TEST(test_invalidating_flags);
    RUN_TEST(test_ratio_below_099_is_a_gap);
    RUN_TEST(test_degrading_flags);
    RUN_TEST(test_bulb_off_is_no_load_not_out_of_range);
    RUN_TEST(test_non_finite_values_never_valid);
    RUN_TEST(test_flag_names_follow_the_schema);
    RUN_TEST(test_reason_is_the_most_serious_flag);
    return UNITY_END();
}
