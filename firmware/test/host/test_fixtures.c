// T032/T033: the fixture loader, expected values, and the fake ADC replay.
#include <math.h>
#include <string.h>

#include "board.h"
#include "fake_adc.h"
#include "fixtures.h"
#include "unity.h"

static const char *NAMES[] = {"sine_inphase", "lag60",      "dc_offset",
                              "clipping",     "sample_gap", "no_current"};

void setUp(void) {}
void tearDown(void) {}

static void test_every_fixture_loads_one_second(void) {
    for (size_t k = 0; k < sizeof NAMES / sizeof NAMES[0]; k++) {
        fixture_t f;
        TEST_ASSERT_TRUE_MESSAGE(fixture_load(NAMES[k], &f), NAMES[k]);
        size_t want = strcmp(NAMES[k], "sample_gap") == 0 ? 3800 : 4000;
        TEST_ASSERT_EQUAL_size_t(want, f.count);
        TEST_ASSERT_EQUAL_UINT32(3999, f.pair[f.count - 1]);
        fixture_free(&f);
    }
}

static void test_expected_values_and_tolerances(void) {
    fixture_expected_t e;
    TEST_ASSERT_TRUE(fixture_expected("sine_inphase", &e));
    TEST_ASSERT_TRUE(e.valid);
    TEST_ASSERT_TRUE(fixture_within(e.active_power_w, 20.4, 0.01, 0.0));
    TEST_ASSERT_TRUE(fixture_expected("clipping", &e));
    TEST_ASSERT_FALSE(e.valid);
    TEST_ASSERT_EQUAL_STRING("adc_clipped", e.flags);
    TEST_ASSERT_TRUE(isnan(e.active_power_w));
    fixture_tolerance_t t;
    TEST_ASSERT_TRUE(fixture_tolerance(&t));
    TEST_ASSERT_EQUAL_DOUBLE(0.005, t.rel[0]);
    TEST_ASSERT_EQUAL_DOUBLE(0.05, t.abs[2]);
    TEST_ASSERT_FALSE(fixture_expected("no_such_fixture", &e));
}

static void test_fake_adc_alternates_v_then_i(void) {
    fixture_t f;
    TEST_ASSERT_TRUE(fixture_load("sine_inphase", &f));
    fake_adc_t fake;
    adc_port_t adc = fake_adc_init(&fake, &f);
    adc_conversion_t buf[7];
    size_t n = 0;
    TEST_ASSERT_EQUAL(ADC_PORT_OK, adc.read(adc.ctx, buf, 7, &n, 0));
    TEST_ASSERT_EQUAL_size_t(7, n);
    TEST_ASSERT_EQUAL_UINT8(BOARD_ADC_CH_VOLTAGE, buf[0].channel);
    TEST_ASSERT_EQUAL_UINT16(f.v_mv[0], buf[0].mv);
    TEST_ASSERT_EQUAL_UINT8(BOARD_ADC_CH_CURRENT, buf[1].channel);
    TEST_ASSERT_EQUAL_UINT16(f.i_mv[0], buf[1].mv);
    TEST_ASSERT_EQUAL_UINT8(BOARD_ADC_CH_VOLTAGE, buf[6].channel);
    size_t total = n;
    adc_conversion_t big[1024];
    while (adc.read(adc.ctx, big, 1024, &n, 0) == ADC_PORT_OK) {
        total += n;
    }
    TEST_ASSERT_EQUAL_size_t(8000, total);
    fixture_free(&f);
}

static void test_fake_adc_reports_gap_as_overrun(void) {
    fixture_t f;
    TEST_ASSERT_TRUE(fixture_load("sample_gap", &f));
    fake_adc_t fake;
    adc_port_t adc = fake_adc_init(&fake, &f);
    adc_conversion_t buf[1024];
    size_t n = 0, total = 0;
    int overruns = 0;
    adc_port_status_t st;
    while ((st = adc.read(adc.ctx, buf, 1024, &n, 0)) != ADC_PORT_END) {
        total += n;
        overruns += st == ADC_PORT_OVERRUN;
    }
    TEST_ASSERT_EQUAL(1, overruns);
    TEST_ASSERT_EQUAL_size_t(7600, total);
    fixture_free(&f);
}

int main(void) {
    UNITY_BEGIN();
    RUN_TEST(test_every_fixture_loads_one_second);
    RUN_TEST(test_expected_values_and_tolerances);
    RUN_TEST(test_fake_adc_alternates_v_then_i);
    RUN_TEST(test_fake_adc_reports_gap_as_overrun);
    return UNITY_END();
}
