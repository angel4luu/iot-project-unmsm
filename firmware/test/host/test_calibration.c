// T098 (calibration part): nominal coefficients, offset capture, sign correction,
// and append-only revisions in NVS (T044).
#include <math.h>
#include <string.h>

#include "calibration.h"
#include "fake_nvs.h"
#include "unity.h"

static fake_nvs_t fake;
static nvs_port_t nvs;
static calibration_t cal;

void setUp(void) {
    nvs = fake_nvs_init(&fake);
    calibration_nominal(&cal, &CAL_FRONTEND_NOMINAL);
}

void tearDown(void) {
    fake_nvs_free(&fake);
}

static void test_nominal_coefficients_follow_the_front_end(void) {
    TEST_ASSERT_DOUBLE_WITHIN(1e-6, 104.7 / 4.7, cal.voltage_gain);
    TEST_ASSERT_DOUBLE_WITHIN(1e-9, 14.7, cal.current_gain);
    TEST_ASSERT_DOUBLE_WITHIN(1e-9, 0.5, cal.phase_correction_pairs);
    TEST_ASSERT_DOUBLE_WITHIN(1e-6, 2500.0 * 10.0 / 14.7, cal.current_zero_mv);
    TEST_ASSERT_EQUAL_INT32(1, cal.current_sign);
    TEST_ASSERT_EQUAL(CAL_KIND_NOMINAL, cal.kind);
    TEST_ASSERT_FALSE(calibration_accepted(&cal)); // until frozen: calibration_missing
}

static cal_offset_result_t finish(uint32_t pairs, double mean_mv, double noise_mv) {
    cal_offset_capture_t cap;
    cal_offset_begin(&cap);
    for (uint32_t k = 0; k < pairs; k++) {
        const double x = mean_mv + ((k & 1u) ? noise_mv : -noise_mv);
        cal_offset_add(&cap, (uint16_t)lround(x));
    }
    return cal_offset_finish(&cap, 4000, &cal);
}

static void test_offset_capture_stores_the_zero(void) {
    TEST_ASSERT_EQUAL(CAL_OFFSET_OK, finish(240000, 1712.0, 1.0));
    TEST_ASSERT_DOUBLE_WITHIN(0.01, 1712.0, cal.current_zero_mv);
    TEST_ASSERT_DOUBLE_WITHIN(1e-9, 0.05, cal.zero_noise_current_a); // 3 sigma = 0.044 A
}

static void test_offset_capture_widens_a_noisy_limit(void) {
    TEST_ASSERT_EQUAL(CAL_OFFSET_OK, finish(240000, 1700.0, 4.0));
    TEST_ASSERT_DOUBLE_WITHIN(1e-6, 3.0 * 4.0 / 1000.0 * 14.7, cal.zero_noise_current_a);
}

static void test_offset_capture_rejects_short_or_disconnected(void) {
    TEST_ASSERT_EQUAL(CAL_OFFSET_TOO_SHORT, finish(200000, 1700.0, 1.0));
    TEST_ASSERT_EQUAL(CAL_OFFSET_DISCONNECTED, finish(240000, 40.0, 1.0));
    TEST_ASSERT_DOUBLE_WITHIN(1e-6, 2500.0 * 10.0 / 14.7, cal.current_zero_mv); // untouched
}

static void test_sign_correction(void) {
    TEST_ASSERT_FALSE(cal_correct_sign(&cal, 20.4, 1.0));
    TEST_ASSERT_FALSE(cal_correct_sign(&cal, -0.3, 1.0)); // noise, not a reversal
    TEST_ASSERT_TRUE(cal_correct_sign(&cal, -20.4, 1.0));
    TEST_ASSERT_EQUAL_INT32(-1, cal.current_sign);
}

static void test_freeze_appends_revisions_and_never_overwrites(void) {
    TEST_ASSERT_EQUAL_UINT32(0, calibration_revision_count(&nvs));
    calibration_t first = cal;
    TEST_ASSERT_EQUAL(CAL_STORE_OK, calibration_freeze(&nvs, "node-001", &first));
    TEST_ASSERT_EQUAL_STRING("node-001-nominal-r1", first.revision);
    TEST_ASSERT_TRUE(calibration_accepted(&first));
    TEST_ASSERT_EQUAL(CAL_STORE_FROZEN, calibration_freeze(&nvs, "node-001", &first));

    calibration_t second = cal;
    second.current_sign = -1;
    TEST_ASSERT_EQUAL(CAL_STORE_OK, calibration_freeze(&nvs, "node-001", &second));
    TEST_ASSERT_EQUAL_STRING("node-001-nominal-r2", second.revision);

    calibration_t got;
    TEST_ASSERT_TRUE(calibration_load_latest(&nvs, &got));
    TEST_ASSERT_EQUAL_STRING("node-001-nominal-r2", got.revision);
    TEST_ASSERT_EQUAL_INT32(-1, got.current_sign);
    TEST_ASSERT_TRUE(calibration_load(&nvs, 1, &got)); // the old revision is intact
    TEST_ASSERT_EQUAL_INT32(1, got.current_sign);
}

static void test_an_orphan_key_is_never_overwritten(void) {
    calibration_t junk = cal;
    nvs.set_blob(nvs.ctx, "cal_r1", &junk, sizeof junk); // power loss before the head moved
    calibration_t next = cal;
    TEST_ASSERT_EQUAL(CAL_STORE_EXISTS, calibration_freeze(&nvs, "node-001", &next));
}

static void test_corrupt_or_missing_revision_is_not_loaded(void) {
    calibration_t got;
    TEST_ASSERT_FALSE(calibration_load_latest(&nvs, &got));
    calibration_t c = cal;
    calibration_freeze(&nvs, "node-001", &c);
    c.voltage_gain = 99.0; // altered without updating the CRC
    nvs.set_blob(nvs.ctx, "cal_r1", &c, sizeof c);
    TEST_ASSERT_FALSE(calibration_load_latest(&nvs, &got));
}

static void test_bad_node_id_is_refused(void) {
    calibration_t c = cal;
    TEST_ASSERT_EQUAL(CAL_STORE_BAD_NODE, calibration_freeze(&nvs, "", &c));
    TEST_ASSERT_EQUAL(CAL_STORE_BAD_NODE,
                      calibration_freeze(&nvs, "a-node-id-that-is-far-too-long-for-it", &c));
}

int main(void) {
    UNITY_BEGIN();
    RUN_TEST(test_nominal_coefficients_follow_the_front_end);
    RUN_TEST(test_offset_capture_stores_the_zero);
    RUN_TEST(test_offset_capture_widens_a_noisy_limit);
    RUN_TEST(test_offset_capture_rejects_short_or_disconnected);
    RUN_TEST(test_sign_correction);
    RUN_TEST(test_freeze_appends_revisions_and_never_overwrites);
    RUN_TEST(test_an_orphan_key_is_never_overwritten);
    RUN_TEST(test_corrupt_or_missing_revision_is_not_loaded);
    RUN_TEST(test_bad_node_id_is_refused);
    return UNITY_END();
}
