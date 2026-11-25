// T048: RAM offline queue (write before publish, remove on accepted/duplicate,
// terminal rejection to diagnostics, oldest first, <= 10 in flight, >= 256 records).
#include <stdio.h>
#include <string.h>

#include "queue.h"
#include "unity.h"

static telemetry_queue_t q; // large: static, as on the target

void setUp(void) {
    queue_init(&q);
}

void tearDown(void) {}

static measurement_record_t rec(uint32_t n) {
    measurement_record_t r;
    memset(&r, 0, sizeof r);
    snprintf(r.message_id, sizeof r.message_id, "123e4567-e89b-42d3-a456-%012u", (unsigned)n);
    r.sequence = n;
    r.uptime_ms = 5000u * n;
    return r;
}

static void test_capacity_is_at_least_256(void) {
    TEST_ASSERT_TRUE(QUEUE_CAPACITY >= 256u);
    for (uint32_t k = 0; k < 256; k++) {
        measurement_record_t r = rec(k);
        TEST_ASSERT_TRUE(queue_push(&q, &r));
    }
    TEST_ASSERT_EQUAL_UINT32(256, queue_pending(&q));
    TEST_ASSERT_EQUAL_UINT32(0, q.dropped);
}

static void test_oldest_first_and_at_most_10_in_flight(void) {
    for (uint32_t k = 0; k < 20; k++) {
        measurement_record_t r = rec(k);
        queue_push(&q, &r);
    }
    for (uint32_t k = 0; k < 10; k++) {
        const measurement_record_t *r = queue_next(&q, 0);
        TEST_ASSERT_NOT_NULL(r);
        TEST_ASSERT_EQUAL_UINT64(k, r->sequence);
    }
    TEST_ASSERT_NULL(queue_next(&q, 0));
    TEST_ASSERT_EQUAL_UINT32(20, queue_pending(&q)); // nothing removed without an ACK
}

static void test_ack_rules(void) {
    for (uint32_t k = 0; k < 3; k++) {
        measurement_record_t r = rec(k);
        queue_push(&q, &r);
        queue_next(&q, 0);
    }
    measurement_record_t r0 = rec(0), r1 = rec(1), r2 = rec(2);
    TEST_ASSERT_TRUE(queue_ack(&q, r1.message_id, ACK_DUPLICATE, NULL)); // out of order is fine
    TEST_ASSERT_TRUE(queue_ack(&q, r0.message_id, ACK_ACCEPTED, NULL));
    TEST_ASSERT_TRUE(queue_ack(&q, r2.message_id, ACK_REJECTED, "schema_violation"));
    TEST_ASSERT_EQUAL_UINT32(0, queue_pending(&q));
    TEST_ASSERT_EQUAL_UINT32(1, q.rejected);
    TEST_ASSERT_EQUAL_STRING("schema_violation", q.diag[0].reason);
    TEST_ASSERT_EQUAL_STRING(r2.message_id, q.diag[0].message_id);
    TEST_ASSERT_FALSE(queue_ack(&q, r0.message_id, ACK_ACCEPTED, NULL)); // late duplicate ACK
}

static void test_requeue_after_reconnect_or_timeout(void) {
    for (uint32_t k = 0; k < 3; k++) {
        measurement_record_t r = rec(k);
        queue_push(&q, &r);
    }
    queue_next(&q, 100);
    queue_next(&q, 200);
    queue_requeue_stale(&q, 1100, 1000);
    TEST_ASSERT_EQUAL_UINT32(1, q.in_flight); // only the one sent at 100 timed out
    TEST_ASSERT_EQUAL_UINT64(0, queue_next(&q, 1100)->sequence);
    queue_requeue_all(&q);
    TEST_ASSERT_EQUAL_UINT32(0, q.in_flight);
    TEST_ASSERT_EQUAL_UINT64(0, queue_next(&q, 0)->sequence); // resend oldest first
}

static void test_full_queue_drops_the_oldest(void) {
    for (uint32_t k = 0; k < QUEUE_CAPACITY; k++) {
        measurement_record_t r = rec(k);
        TEST_ASSERT_TRUE(queue_push(&q, &r));
    }
    measurement_record_t extra = rec(QUEUE_CAPACITY);
    TEST_ASSERT_FALSE(queue_push(&q, &extra));
    TEST_ASSERT_EQUAL_UINT32(1, q.dropped);
    TEST_ASSERT_EQUAL_UINT32(QUEUE_CAPACITY, queue_pending(&q));
    TEST_ASSERT_EQUAL_UINT64(1, queue_next(&q, 0)->sequence);
}

static void test_holes_from_out_of_order_acks_are_reclaimed(void) {
    for (uint32_t round = 0; round < 3 * QUEUE_CAPACITY; round++) {
        measurement_record_t r = rec(round);
        TEST_ASSERT_TRUE(queue_push(&q, &r));
        const measurement_record_t *sent = queue_next(&q, 0);
        TEST_ASSERT_NOT_NULL(sent);
        TEST_ASSERT_TRUE(queue_ack(&q, sent->message_id, ACK_ACCEPTED, NULL));
    }
    TEST_ASSERT_EQUAL_UINT32(0, queue_pending(&q));
    TEST_ASSERT_EQUAL_UINT32(0, q.span);
    TEST_ASSERT_EQUAL_UINT32(0, q.dropped);
}

static void test_oldest_age(void) {
    TEST_ASSERT_EQUAL_INT64(0, queue_oldest_age_s(&q, 99999));
    measurement_record_t r = rec(2); // uptime 10 s
    queue_push(&q, &r);
    TEST_ASSERT_EQUAL_INT64(50, queue_oldest_age_s(&q, 60000));
}

static void test_parse_server_acks(void) {
    char id[REC_UUID_LEN + 1], reason[QUEUE_REASON_MAX + 1];
    ack_status_t st;
    const char *ok =
        "{\"schema_version\":\"1.0.0\",\"acknowledged_at\":\"2026-10-14T17:00:05.300Z\","
        "\"message_id\":\"123e4567-e89b-42d3-a456-426614174000\",\"node_id\":\"node-001\","
        "\"boot_id\":\"123e4567-e89b-42d3-8456-426614174001\",\"sequence\":42,"
        "\"status\":\"accepted\",\"reason_code\":null,\"stored_at\":\"2026-10-14T17:00:05.250Z\"}";
    TEST_ASSERT_TRUE(queue_parse_ack(ok, strlen(ok), id, &st, reason));
    TEST_ASSERT_EQUAL_STRING("123e4567-e89b-42d3-a456-426614174000", id);
    TEST_ASSERT_EQUAL(ACK_ACCEPTED, st);
    TEST_ASSERT_EQUAL_STRING("", reason);
    const char *rej = "{\"message_id\": \"123e4567-e89b-42d3-a456-426614174000\", \"status\": "
                      "\"rejected\", \"reason_code\": \"identity_conflict\"}";
    TEST_ASSERT_TRUE(queue_parse_ack(rej, strlen(rej), id, &st, reason));
    TEST_ASSERT_EQUAL(ACK_REJECTED, st);
    TEST_ASSERT_EQUAL_STRING("identity_conflict", reason);
    const char *bad[] = {
        "{}", "{\"message_id\":\"short\",\"status\":\"accepted\"}",
        "{\"message_id\":\"123e4567-e89b-42d3-a456-426614174000\",\"status\":\"ok\"}", "not json"};
    for (size_t k = 0; k < sizeof bad / sizeof bad[0]; k++) {
        TEST_ASSERT_FALSE(queue_parse_ack(bad[k], strlen(bad[k]), id, &st, reason));
    }
}

int main(void) {
    UNITY_BEGIN();
    RUN_TEST(test_capacity_is_at_least_256);
    RUN_TEST(test_oldest_first_and_at_most_10_in_flight);
    RUN_TEST(test_ack_rules);
    RUN_TEST(test_requeue_after_reconnect_or_timeout);
    RUN_TEST(test_full_queue_drops_the_oldest);
    RUN_TEST(test_holes_from_out_of_order_acks_are_reclaimed);
    RUN_TEST(test_oldest_age);
    RUN_TEST(test_parse_server_acks);
    return UNITY_END();
}
