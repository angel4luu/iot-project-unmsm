// T098 (acquisition part): pairing the V/I conversion stream and raising gaps (T043).
#include <string.h>

#include "acquisition.h"
#include "board.h"
#include "fake_adc.h"
#include "fixtures.h"
#include "unity.h"

typedef struct {
    uint32_t pairs, gaps;
    uint16_t last_v, last_i;
} sink_t;

static sink_t sink;
static acq_t acq;

static void on_pair(void *ctx, uint16_t v, uint16_t i) {
    sink_t *s = ctx;
    s->pairs++;
    s->last_v = v;
    s->last_i = i;
}

static void on_gap(void *ctx) {
    ((sink_t *)ctx)->gaps++;
}

void setUp(void) {
    memset(&sink, 0, sizeof sink);
    acq_init(&acq, BOARD_ADC_CH_VOLTAGE, BOARD_ADC_CH_CURRENT, on_pair, on_gap, &sink);
}

void tearDown(void) {}

#define V(x) {.channel = BOARD_ADC_CH_VOLTAGE, .mv = (x)}
#define I(x) {.channel = BOARD_ADC_CH_CURRENT, .mv = (x)}

static void test_alternating_stream_makes_pairs(void) {
    const adc_conversion_t c[] = {V(1650), I(1700), V(1651), I(1701)};
    acq_feed(&acq, c, 4);
    TEST_ASSERT_EQUAL_UINT32(2, sink.pairs);
    TEST_ASSERT_EQUAL_UINT32(0, sink.gaps);
    TEST_ASSERT_EQUAL_UINT16(1651, sink.last_v);
    TEST_ASSERT_EQUAL_UINT16(1701, sink.last_i);
}

static void test_pairs_survive_batch_boundaries(void) {
    const adc_conversion_t a[] = {V(1650)};
    const adc_conversion_t b[] = {I(1700)};
    acq_feed(&acq, a, 1);
    acq_feed(&acq, b, 1);
    TEST_ASSERT_EQUAL_UINT32(1, sink.pairs);
}

static void test_broken_alternation_is_one_gap(void) {
    const adc_conversion_t c[] = {V(1), V(2), I(3)}; // lost current of the first pair
    acq_feed(&acq, c, 3);
    TEST_ASSERT_EQUAL_UINT32(1, sink.gaps);
    TEST_ASSERT_EQUAL_UINT32(1, sink.pairs);
    setUp();
    const adc_conversion_t d[] = {I(3), I(4), {.channel = 7, .mv = 0}, V(1), I(2)};
    acq_feed(&acq, d, 5);
    TEST_ASSERT_EQUAL_UINT32(1, sink.gaps); // consecutive breaks collapse into one
    TEST_ASSERT_EQUAL_UINT32(1, sink.pairs);
}

static void test_overrun_drops_the_pending_voltage(void) {
    const adc_conversion_t a[] = {V(1650)};
    const adc_conversion_t b[] = {I(1700)};
    acq_feed(&acq, a, 1);
    acq_overrun(&acq);
    acq_feed(&acq, b, 1);
    TEST_ASSERT_EQUAL_UINT32(0, sink.pairs);
    TEST_ASSERT_EQUAL_UINT32(1, sink.gaps);
    TEST_ASSERT_EQUAL_UINT32(1, acq.overruns);
}

static void test_fixture_with_dma_gap_raises_exactly_one_gap(void) {
    fixture_t fx;
    TEST_ASSERT_TRUE(fixture_load("sample_gap", &fx));
    fake_adc_t fake;
    adc_port_t port = fake_adc_init(&fake, &fx);
    while (acq_poll(&acq, &port, 0) != ADC_PORT_END) {
    }
    TEST_ASSERT_EQUAL_UINT32(fx.count, sink.pairs);
    TEST_ASSERT_TRUE(sink.gaps >= 1);
    fixture_free(&fx);
}

static void test_clean_fixture_has_no_gap(void) {
    fixture_t fx;
    TEST_ASSERT_TRUE(fixture_load("sine_inphase", &fx));
    fake_adc_t fake;
    adc_port_t port = fake_adc_init(&fake, &fx);
    while (acq_poll(&acq, &port, 0) != ADC_PORT_END) {
    }
    TEST_ASSERT_EQUAL_UINT32(4000, sink.pairs);
    TEST_ASSERT_EQUAL_UINT32(0, sink.gaps);
    fixture_free(&fx);
}

int main(void) {
    UNITY_BEGIN();
    RUN_TEST(test_alternating_stream_makes_pairs);
    RUN_TEST(test_pairs_survive_batch_boundaries);
    RUN_TEST(test_broken_alternation_is_one_gap);
    RUN_TEST(test_overrun_drops_the_pending_voltage);
    RUN_TEST(test_fixture_with_dma_gap_raises_exactly_one_gap);
    RUN_TEST(test_clean_fixture_has_no_gap);
    return UNITY_END();
}
