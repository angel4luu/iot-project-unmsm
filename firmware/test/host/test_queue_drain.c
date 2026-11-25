// T067: queue drain after an outage (plan > Telemetry: oldest first, >= 2 records/s,
// <= 10 in flight, new observations still enqueued). A simulated server ACKs every
// sent record after a fixed round trip; the pump runs every 100 ms and a new 5 s
// summary arrives as on the node.
#include <stdio.h>
#include <string.h>

#include "queue.h"
#include "unity.h"

#define PUMP_US 100000LL
#define SUMMARY_US 5000000LL
#define ACK_TIMEOUT_US 30000000LL
#define OUTAGE_RECORDS 120u // 10 min of 5 s summaries
#define MAX_SENT 4096u

static telemetry_queue_t q;

typedef struct {
    int64_t now_us;
    int64_t rtt_us;
    bool link_down;
    uint32_t fail_after; // sends before the link fails (0 = never)
    uint32_t sends;
    // every send, in order
    uint64_t sent_seq[MAX_SENT];
    int64_t sent_at[MAX_SENT];
    uint32_t n_sent;
    uint32_t max_in_flight;
    uint32_t lock_depth;
    uint64_t unsendable_seq; // UINT64_MAX = none
} server_t;

static server_t srv;

void setUp(void) {
    queue_init(&q);
    memset(&srv, 0, sizeof srv);
    srv.unsendable_seq = UINT64_MAX;
}

void tearDown(void) {}

static uint64_t next_seq;

static measurement_record_t rec(uint64_t n) {
    measurement_record_t r;
    memset(&r, 0, sizeof r);
    snprintf(r.message_id, sizeof r.message_id, "123e4567-e89b-42d3-a456-%012u", (unsigned)n);
    r.sequence = n;
    r.uptime_ms = 5000u * n;
    return r;
}

static void push_next(void) {
    measurement_record_t r = rec(next_seq++);
    TEST_ASSERT_TRUE(queue_push(&q, &r));
}

static void lock_cb(void *ctx) {
    (void)ctx;
    TEST_ASSERT_EQUAL_UINT32(0, srv.lock_depth);
    srv.lock_depth++;
}

static void unlock_cb(void *ctx) {
    (void)ctx;
    TEST_ASSERT_EQUAL_UINT32(1, srv.lock_depth);
    srv.lock_depth--;
}

static queue_send_result_t send_cb(void *ctx, const measurement_record_t *r) {
    (void)ctx;
    TEST_ASSERT_EQUAL_UINT32_MESSAGE(0, srv.lock_depth, "send must run without the lock");
    if (srv.link_down || (srv.fail_after != 0 && srv.sends >= srv.fail_after)) {
        return QUEUE_SEND_FAILED;
    }
    if (r->sequence == srv.unsendable_seq) {
        return QUEUE_SEND_UNSENDABLE;
    }
    TEST_ASSERT_TRUE(srv.n_sent < MAX_SENT);
    srv.sent_seq[srv.n_sent] = r->sequence;
    srv.sent_at[srv.n_sent] = srv.now_us;
    srv.n_sent++;
    srv.sends++;
    if (q.in_flight > srv.max_in_flight) {
        srv.max_in_flight = q.in_flight;
    }
    return QUEUE_SEND_OK;
}

static const queue_drain_ops_t ops = {
    .lock = lock_cb, .unlock = unlock_cb, .send = send_cb, .ctx = NULL};

// ACK everything sent at least one round trip ago (accepted).
static void deliver_acks(void) {
    for (uint32_t k = 0; k < srv.n_sent; k++) {
        if (srv.sent_at[k] >= 0 && srv.now_us - srv.sent_at[k] >= srv.rtt_us) {
            char id[REC_UUID_LEN + 1];
            measurement_record_t r = rec(srv.sent_seq[k]);
            memcpy(id, r.message_id, sizeof id);
            queue_ack(&q, id, ACK_ACCEPTED, NULL);
            srv.sent_at[k] = -1; // acknowledged
        }
    }
}

// Runs the node for `duration_us`: pump every 100 ms, a new summary every 5 s.
// Returns the time at which the queue held only records younger than one summary.
static int64_t run(int64_t duration_us, uint32_t backlog_target) {
    int64_t drained_at = -1;
    const int64_t end = srv.now_us + duration_us;
    for (; srv.now_us < end; srv.now_us += PUMP_US) {
        if (srv.now_us % SUMMARY_US == 0) {
            push_next();
        }
        deliver_acks();
        queue_drain(&q, srv.now_us, ACK_TIMEOUT_US, &ops);
        TEST_ASSERT_TRUE(q.in_flight <= QUEUE_MAX_IN_FLIGHT);
        if (drained_at < 0 && queue_pending(&q) <= backlog_target) {
            drained_at = srv.now_us;
        }
    }
    return drained_at;
}

static void fill_outage(void) {
    next_seq = 0;
    for (uint32_t k = 0; k < OUTAGE_RECORDS; k++) {
        push_next();
    }
}

static void assert_oldest_first_once_each(void) {
    // First sends are strictly increasing: oldest first, nothing skipped or repeated.
    for (uint32_t k = 1; k < srv.n_sent; k++) {
        TEST_ASSERT_TRUE_MESSAGE(srv.sent_seq[k] > srv.sent_seq[k - 1], "not oldest first");
    }
}

static void test_backlog_drains_oldest_first_at_least_2_per_s(void) {
    fill_outage();
    srv.rtt_us = 500000; // healthy LAN server
    const int64_t drained = run(5LL * 60 * 1000000, 1);
    TEST_ASSERT_TRUE(drained >= 0);
    assert_oldest_first_once_each();
    TEST_ASSERT_EQUAL_UINT32(QUEUE_MAX_IN_FLIGHT, srv.max_in_flight);
    // >= 2 records/s over the drain (the 120-record backlog plus live summaries)
    const double rate = (double)srv.n_sent / ((double)(drained + PUMP_US) / 1e6);
    TEST_ASSERT_TRUE_MESSAGE(rate >= 2.0, "drain slower than 2 records/s");
    TEST_ASSERT_TRUE(drained < 60LL * 1000000); // well inside SC-003's 5 min
}

static void test_slow_server_still_meets_2_per_s_and_5_min(void) {
    fill_outage();
    srv.rtt_us = 4900000; // just under 5 s round trip: 10 per 5 s = 2 records/s
    const int64_t drained = run(5LL * 60 * 1000000, 1);
    TEST_ASSERT_TRUE_MESSAGE(drained >= 0, "backlog not drained within 5 min");
    assert_oldest_first_once_each();
    TEST_ASSERT_EQUAL_UINT32(0, q.dropped);
}

static void test_new_observations_enqueued_during_drain_and_sent_after_older(void) {
    fill_outage();
    srv.rtt_us = 2000000;
    run(60LL * 1000000, 0);
    // 12 live summaries arrived during that minute; all are queued or already sent
    TEST_ASSERT_EQUAL_UINT64(OUTAGE_RECORDS + 12, next_seq);
    // conservation: every record is either acknowledged or still queued
    uint32_t acked = 0;
    for (uint32_t k = 0; k < srv.n_sent; k++) {
        acked += srv.sent_at[k] < 0 ? 1u : 0u;
    }
    TEST_ASSERT_EQUAL_UINT32((uint32_t)next_seq, acked + queue_pending(&q));
    TEST_ASSERT_TRUE(acked > OUTAGE_RECORDS); // live summaries got through too
    assert_oldest_first_once_each();
    TEST_ASSERT_EQUAL_UINT32(0, q.dropped);
}

static void test_link_failure_stops_and_resends_from_oldest(void) {
    fill_outage();
    srv.rtt_us = 1000000;
    srv.fail_after = 5;
    srv.now_us = 0;
    const uint32_t sent = queue_drain(&q, srv.now_us, ACK_TIMEOUT_US, &ops);
    TEST_ASSERT_EQUAL_UINT32(5, sent);
    TEST_ASSERT_EQUAL_UINT32(0, q.in_flight); // everything sendable again
    TEST_ASSERT_EQUAL_UINT32(OUTAGE_RECORDS, queue_pending(&q));
    srv.fail_after = 0;
    srv.n_sent = 0;
    queue_drain(&q, srv.now_us + PUMP_US, ACK_TIMEOUT_US, &ops);
    TEST_ASSERT_EQUAL_UINT64(0, srv.sent_seq[0]); // resent from the oldest
    TEST_ASSERT_EQUAL_UINT32(QUEUE_MAX_IN_FLIGHT, srv.n_sent);
}

static void test_unsendable_goes_to_diagnostics_and_drain_continues(void) {
    fill_outage();
    srv.unsendable_seq = 3;
    const uint32_t sent = queue_drain(&q, 0, ACK_TIMEOUT_US, &ops);
    TEST_ASSERT_EQUAL_UINT32(QUEUE_MAX_IN_FLIGHT, sent);
    TEST_ASSERT_EQUAL_UINT32(1, q.rejected);
    TEST_ASSERT_EQUAL_STRING("serialize_failed", q.diag[0].reason);
    TEST_ASSERT_EQUAL_UINT32(OUTAGE_RECORDS - 1, queue_pending(&q));
    TEST_ASSERT_EQUAL_UINT64(4, srv.sent_seq[3]); // 3 skipped, not retried
}

static void test_missing_acks_are_resent_after_timeout(void) {
    fill_outage();
    srv.rtt_us = ACK_TIMEOUT_US * 10; // server never answers in time
    queue_drain(&q, 0, ACK_TIMEOUT_US, &ops);
    TEST_ASSERT_EQUAL_UINT32(QUEUE_MAX_IN_FLIGHT, srv.n_sent);
    TEST_ASSERT_EQUAL_UINT32(0, queue_drain(&q, ACK_TIMEOUT_US - 1, ACK_TIMEOUT_US, &ops));
    TEST_ASSERT_EQUAL_UINT32(QUEUE_MAX_IN_FLIGHT,
                             queue_drain(&q, ACK_TIMEOUT_US, ACK_TIMEOUT_US, &ops));
    TEST_ASSERT_EQUAL_UINT64(0, srv.sent_seq[QUEUE_MAX_IN_FLIGHT]); // same oldest again
}

int main(void) {
    UNITY_BEGIN();
    RUN_TEST(test_backlog_drains_oldest_first_at_least_2_per_s);
    RUN_TEST(test_slow_server_still_meets_2_per_s_and_5_min);
    RUN_TEST(test_new_observations_enqueued_during_drain_and_sent_after_older);
    RUN_TEST(test_link_failure_stops_and_resends_from_oldest);
    RUN_TEST(test_unsendable_goes_to_diagnostics_and_drain_continues);
    RUN_TEST(test_missing_acks_are_resent_after_timeout);
    return UNITY_END();
}
