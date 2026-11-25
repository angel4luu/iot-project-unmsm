// T035: RMS, active power as mean(v*i) with phase correction, energy, and polarity,
// against the independent reference values (tests/fixtures/waveforms/expected.csv).
#include <math.h>
#include <string.h>

#include "acquisition.h"
#include "board.h"
#include "calibration.h"
#include "fake_adc.h"
#include "fixtures.h"
#include "metering.h"
#include "quality.h"
#include "unity.h"

static fixture_tolerance_t tol;
static calibration_t cal;

void setUp(void) {
    TEST_ASSERT_TRUE(fixture_tolerance(&tol));
    calibration_nominal(&cal, &CAL_FRONTEND_NOMINAL);
}

void tearDown(void) {}

static void on_pair(void *ctx, uint16_t v, uint16_t i) {
    metering_block_add(ctx, v, i);
}

static void on_gap(void *ctx) {
    metering_block_gap(ctx);
}

// Replays a fixture through the fake ADC and acquisition into one 1 s block.
static metering_block_result_t run(const char *name, const calibration_t *c) {
    fixture_t fx;
    TEST_ASSERT_TRUE_MESSAGE(fixture_load(name, &fx), name);
    fake_adc_t fake;
    adc_port_t port = fake_adc_init(&fake, &fx);
    metering_block_t block;
    metering_block_reset(&block);
    acq_t acq;
    acq_init(&acq, BOARD_ADC_CH_VOLTAGE, BOARD_ADC_CH_CURRENT, on_pair, on_gap, &block);
    while (acq_poll(&acq, &port, 0) != ADC_PORT_END) {
    }
    metering_block_result_t r;
    TEST_ASSERT_TRUE(metering_block_finish(&block, c, &r));
    TEST_ASSERT_EQUAL_UINT32(fx.count, r.pairs);
    fixture_free(&fx);
    return r;
}

static void check_close(const char *what, double got, double want, int q) {
    char msg[96];
    snprintf(msg, sizeof msg, "%s: got %.6f want %.6f", what, got, want);
    TEST_ASSERT_TRUE_MESSAGE(fixture_within(got, want, tol.rel[q], tol.abs[q]), msg);
}

static void check_valid_fixture(const char *name) {
    fixture_expected_t e;
    TEST_ASSERT_TRUE(fixture_expected(name, &e));
    TEST_ASSERT_TRUE(e.valid);
    const metering_block_result_t r = run(name, &cal);
    TEST_ASSERT_FALSE(r.sample_gap);
    TEST_ASSERT_FALSE(r.adc_clipped);
    TEST_ASSERT_TRUE(r.power_valid);
    check_close("V rms", r.v_rms_v, e.v_rms_v, 0);
    check_close("I rms", r.i_rms_a, e.i_rms_a, 1);
    check_close("P", r.active_power_w, e.active_power_w, 2);
    energy_counter_t en = {.total_wh = 0.0};
    energy_add(&en, r.active_power_w, 1000000); // fixtures are 1 s windows
    check_close("Wh", en.total_wh, e.energy_wh, 3);
}

static void test_sine_inphase(void) {
    check_valid_fixture("sine_inphase");
}
static void test_lag60(void) {
    check_valid_fixture("lag60");
}
static void test_dc_offset(void) {
    check_valid_fixture("dc_offset");
}
static void test_no_current(void) {
    check_valid_fixture("no_current");
}

static void test_power_is_mean_of_vi_not_vrms_times_irms(void) {
    const metering_block_result_t r = run("lag60", &cal);
    const double apparent = r.v_rms_v * r.i_rms_a;
    // A 60 degree lag halves the active power; Vrms*Irms would be twice as large.
    TEST_ASSERT_DOUBLE_WITHIN(0.02 * apparent, 0.5 * apparent, r.active_power_w);
}

static void test_phase_correction_moves_power_towards_reference(void) {
    fixture_expected_t e;
    TEST_ASSERT_TRUE(fixture_expected("lag60", &e));
    calibration_t none = cal;
    none.phase_correction_pairs = 0.0;
    const double corrected = run("lag60", &cal).active_power_w;
    const double uncorrected = run("lag60", &none).active_power_w;
    TEST_ASSERT_TRUE(fabs(corrected - e.active_power_w) < fabs(uncorrected - e.active_power_w));
}

static void test_clipping_and_gap_are_detected(void) {
    TEST_ASSERT_TRUE(run("clipping", &cal).adc_clipped);
    const metering_block_result_t g = run("sample_gap", &cal);
    TEST_ASSERT_TRUE(g.sample_gap);
    TEST_ASSERT_FALSE(g.adc_clipped);
}

static void test_reversed_polarity_is_flagged_and_never_decrements_energy(void) {
    calibration_t reversed = cal;
    reversed.current_sign = -1;
    const metering_block_result_t r = run("sine_inphase", &reversed);
    TEST_ASSERT_TRUE(r.active_power_w < -19.0);
    energy_counter_t en = {.total_wh = 5.0};
    energy_add(&en, r.active_power_w, 1000000);
    TEST_ASSERT_EQUAL_DOUBLE(5.0, en.total_wh);
    const quality_input_t in = {
        .valid_sample_ratio = 1.0,
        .v_rms_v = r.v_rms_v,
        .i_rms_a = r.i_rms_a,
        .active_power_w = r.active_power_w,
        .calibration_accepted = true,
        .zero_noise_current_a = 0.05,
    };
    const quality_result_t q = quality_classify(&in, &QUALITY_LIMITS_PLAN_B);
    TEST_ASSERT_EQUAL(QUALITY_DEGRADED, q.state);
    TEST_ASSERT_EQUAL_UINT32(QF_POLARITY_REVERSED, q.flags);
}

static void test_summary_of_five_blocks(void) {
    const metering_block_result_t r = run("sine_inphase", &cal);
    metering_summary_t s;
    metering_summary_reset(&s);
    for (int k = 0; k < 5; k++) {
        metering_summary_add(&s, &r, &cal);
    }
    metering_values_t v;
    TEST_ASSERT_TRUE(metering_summary_finish(&s, &v));
    TEST_ASSERT_EQUAL_UINT32(20000, v.sample_count);
    TEST_ASSERT_EQUAL_DOUBLE(1.0, v.valid_sample_ratio);
    TEST_ASSERT_FALSE(v.sample_gap);
    TEST_ASSERT_DOUBLE_WITHIN(1e-9, r.v_rms_v, v.v_rms_v);
    TEST_ASSERT_DOUBLE_WITHIN(1e-9, r.active_power_w, v.active_power_w);
    TEST_ASSERT_TRUE(v.i_offset_dev_mv < 5.0); // nominal ACS712 zero at the pin
}

static void test_short_summary_is_a_gap(void) {
    const metering_block_result_t r = run("sine_inphase", &cal);
    metering_summary_t s;
    metering_summary_reset(&s);
    for (int k = 0; k < 4; k++) {
        metering_summary_add(&s, &r, &cal);
    }
    metering_values_t v;
    TEST_ASSERT_TRUE(metering_summary_finish(&s, &v));
    TEST_ASSERT_TRUE(v.sample_gap);
    TEST_ASSERT_DOUBLE_WITHIN(1e-9, 0.8, v.valid_sample_ratio);
}

static void test_energy_uses_monotonic_dt_only(void) {
    energy_counter_t en = {.total_wh = 0.0};
    energy_add(&en, 20.0, 5000000);
    TEST_ASSERT_DOUBLE_WITHIN(1e-12, 20.0 * 5.0 / 3600.0, en.total_wh);
    energy_add(&en, 20.0, -3000000); // a backwards step adds nothing
    energy_add(&en, NAN, 1000000);
    TEST_ASSERT_DOUBLE_WITHIN(1e-12, 20.0 * 5.0 / 3600.0, en.total_wh);
}

int main(void) {
    UNITY_BEGIN();
    RUN_TEST(test_sine_inphase);
    RUN_TEST(test_lag60);
    RUN_TEST(test_dc_offset);
    RUN_TEST(test_no_current);
    RUN_TEST(test_power_is_mean_of_vi_not_vrms_times_irms);
    RUN_TEST(test_phase_correction_moves_power_towards_reference);
    RUN_TEST(test_clipping_and_gap_are_detected);
    RUN_TEST(test_reversed_polarity_is_flagged_and_never_decrements_energy);
    RUN_TEST(test_summary_of_five_blocks);
    RUN_TEST(test_short_summary_is_a_gap);
    RUN_TEST(test_energy_uses_monotonic_dt_only);
    return UNITY_END();
}
