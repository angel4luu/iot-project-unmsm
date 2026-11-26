// T082 (delivery part): node events leave the RAM queue only on the broker's QoS 1
// PUBACK, are resent after a reconnect or timeout, and survive a measurement outage.
#include <stdio.h>
#include <string.h>

#include "event_queue.h"
#include "unity.h"

static event_queue_t q;
static event_record_t out;
static char reason[EVQ_REASON_MAX + 1];

void setUp(void) {
    evq_init(&q);
}

void tearDown(void) {}

static event_record_t ev(uint32_t n, const char *why) {
    event_record_t e;
    memset(&e, 0, sizeof e);
    snprintf(e.event_id, sizeof e.event_id, "123e4567-e89b-42d3-a456-%012u", (unsigned)n);
    e.sequence = n;
    e.config_version = 1;
    e.reason_code = why;
    return e;
}

static void push(uint32_t n) {
    const event_record_t e = ev(n, NULL);
    evq_push(&q, &e);
}

static void test_removed_only_on_puback(void) {
    push(0);
    push(1);
    const int a = evq_next(&q, 0, &out, reason);
    TEST_ASSERT_EQUAL_UINT64(0, out.sequence);
    evq_sent(&q, a, 11);
    const int b = evq_next(&q, 0, &out, reason);
    TEST_ASSERT_EQUAL_UINT64(1, out.sequence);
    evq_sent(&q, b, 12);
    TEST_ASSERT_EQUAL(-1, evq_next(&q, 0, &out, reason));
    TEST_ASSERT_EQUAL_UINT32(2, evq_pending(&q));
    TEST_ASSERT_FALSE(evq_puback(&q, 99)); // someone else's PUBACK (a measurement)
    TEST_ASSERT_TRUE(evq_puback(&q, 12));
    TEST_ASSERT_TRUE(evq_puback(&q, 11));
    TEST_ASSERT_EQUAL_UINT32(0, evq_pending(&q));
}

static void test_resent_after_reconnect_or_timeout(void) {
    push(0);
    evq_sent(&q, evq_next(&q, 0, &out, reason), 5);
    evq_requeue_stale(&q, 10, 30);
    TEST_ASSERT_EQUAL(-1, evq_next(&q, 10, &out, reason));
    evq_requeue_stale(&q, 30, 30);
    const int again = evq_next(&q, 30, &out, reason);
    TEST_ASSERT_TRUE(again >= 0);
    TEST_ASSERT_EQUAL_UINT64(0, out.sequence); // same event, same event_id
    evq_sent(&q, again, 6);
    evq_requeue_all(&q); // reconnect
    TEST_ASSERT_TRUE(evq_next(&q, 40, &out, reason) >= 0);
}

static void test_failed_send_is_sendable_again(void) {
    push(0);
    evq_sent(&q, evq_next(&q, 0, &out, reason), -1);
    TEST_ASSERT_TRUE(evq_next(&q, 0, &out, reason) >= 0);
}

static void test_puback_before_the_id_is_recorded(void) {
    push(0);
    const int idx = evq_next(&q, 0, &out, reason);
    TEST_ASSERT_FALSE(evq_puback(&q, 7)); // MQTT task was faster than the publisher
    evq_sent(&q, idx, 7);
    TEST_ASSERT_EQUAL_UINT32(0, evq_pending(&q));
}

static void test_reason_is_copied(void) {
    char why[16];
    strcpy(why, "adc_clipped");
    const event_record_t e = ev(0, why);
    evq_push(&q, &e);
    strcpy(why, "overwritten");
    evq_next(&q, 0, &out, reason);
    TEST_ASSERT_EQUAL_STRING("adc_clipped", out.reason_code);
    push(1);
    evq_next(&q, 0, &out, reason);
    TEST_ASSERT_NULL(out.reason_code);
}

static void test_full_queue_drops_oldest_and_counts(void) {
    for (uint32_t k = 0; k < EVQ_CAPACITY; k++) {
        push(k);
    }
    const event_record_t e = ev(EVQ_CAPACITY, NULL);
    TEST_ASSERT_FALSE(evq_push(&q, &e));
    TEST_ASSERT_EQUAL_UINT32(1, q.dropped);
    TEST_ASSERT_EQUAL_UINT32(EVQ_CAPACITY, evq_pending(&q));
    evq_next(&q, 0, &out, reason);
    TEST_ASSERT_EQUAL_UINT64(1, out.sequence);
}

int main(void) {
    UNITY_BEGIN();
    RUN_TEST(test_removed_only_on_puback);
    RUN_TEST(test_resent_after_reconnect_or_timeout);
    RUN_TEST(test_failed_send_is_sendable_again);
    RUN_TEST(test_puback_before_the_id_is_recorded);
    RUN_TEST(test_reason_is_copied);
    RUN_TEST(test_full_queue_drops_oldest_and_counts);
    return UNITY_END();
}
