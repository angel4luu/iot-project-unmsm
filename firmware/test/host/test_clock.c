// T031: clock states, holdover, monotonic uptime, and RFC 3339 formatting.
#include <string.h>

#include "clock.h"
#include "unity.h"

#define S(x) ((int64_t)(x) * 1000000LL)
static const int64_t SYNC_UTC_MS = 1791997200000LL; // 2026-10-14T17:00:00.000Z
static clock_state_t c;

void setUp(void) {
    clock_init(&c, 900); // 15-minute SNTP poll: fresh for 2 x 900 + 60 s
}
void tearDown(void) {}

static void test_boot_is_unsynchronized(void) {
    clock_reading_t r = clock_read(&c, S(12));
    TEST_ASSERT_EQUAL(CLOCK_SOURCE_UNSYNCHRONIZED, r.source);
    TEST_ASSERT_EQUAL_INT64(-1, r.last_sync_age_s);
    TEST_ASSERT_EQUAL_INT64(12000, r.uptime_ms);
    TEST_ASSERT_EQUAL_STRING("unsynchronized", clock_source_name(r.source));
}

static void test_sync_gives_sntp_and_runs_on_monotonic_time(void) {
    clock_on_sntp_sync(&c, SYNC_UTC_MS, S(10));
    clock_reading_t r = clock_read(&c, S(15) + 250000);
    TEST_ASSERT_EQUAL(CLOCK_SOURCE_SNTP, r.source);
    TEST_ASSERT_EQUAL_INT64(SYNC_UTC_MS + 5250, r.utc_ms);
    TEST_ASSERT_EQUAL_INT64(5, r.last_sync_age_s);
}

static void test_link_loss_is_holdover_with_age(void) {
    clock_on_sntp_sync(&c, SYNC_UTC_MS, S(10));
    clock_on_link(&c, false);
    clock_reading_t r = clock_read(&c, S(130));
    TEST_ASSERT_EQUAL(CLOCK_SOURCE_HOLDOVER, r.source);
    TEST_ASSERT_EQUAL_INT64(120, r.last_sync_age_s);
    TEST_ASSERT_EQUAL_INT64(SYNC_UTC_MS + 120000, r.utc_ms);
}

static void test_stale_sync_is_holdover_even_with_link(void) {
    clock_on_sntp_sync(&c, SYNC_UTC_MS, 0);
    TEST_ASSERT_EQUAL(CLOCK_SOURCE_SNTP, clock_read(&c, S(1860)).source);
    TEST_ASSERT_EQUAL(CLOCK_SOURCE_HOLDOVER, clock_read(&c, S(1861)).source);
}

static void test_resync_returns_to_sntp(void) {
    clock_on_sntp_sync(&c, SYNC_UTC_MS, 0);
    clock_on_link(&c, false);
    clock_on_sntp_sync(&c, SYNC_UTC_MS + 600000, S(600));
    TEST_ASSERT_EQUAL(CLOCK_SOURCE_SNTP, clock_read(&c, S(601)).source);
}

static void test_link_up_alone_does_not_synchronize(void) {
    clock_on_link(&c, true);
    TEST_ASSERT_EQUAL(CLOCK_SOURCE_UNSYNCHRONIZED, clock_read(&c, S(5)).source);
}

static void test_wall_clock_step_does_not_change_uptime(void) {
    clock_on_sntp_sync(&c, SYNC_UTC_MS, S(10));
    clock_on_sntp_sync(&c, SYNC_UTC_MS - 3600000, S(20)); // SNTP steps back one hour
    clock_reading_t r = clock_read(&c, S(30));
    TEST_ASSERT_EQUAL_INT64(30000, r.uptime_ms);
    TEST_ASSERT_EQUAL_INT64(SYNC_UTC_MS - 3600000 + 10000, r.utc_ms);
}

static void test_format_rfc3339_with_millis(void) {
    char buf[CLOCK_RFC3339_LEN];
    TEST_ASSERT_EQUAL(24, clock_format_utc(SYNC_UTC_MS + 5, buf, sizeof buf));
    TEST_ASSERT_EQUAL_STRING("2026-10-14T17:00:00.005Z", buf);
    clock_format_utc(0, buf, sizeof buf);
    TEST_ASSERT_EQUAL_STRING("1970-01-01T00:00:00.000Z", buf);
    clock_format_utc(951782400000LL, buf, sizeof buf); // leap day 2000
    TEST_ASSERT_EQUAL_STRING("2000-02-29T00:00:00.000Z", buf);
    clock_format_utc(253402300799999LL, buf, sizeof buf);
    TEST_ASSERT_EQUAL_STRING("9999-12-31T23:59:59.999Z", buf);
}

static void test_format_rejects_bad_input(void) {
    char buf[CLOCK_RFC3339_LEN];
    char small[10];
    TEST_ASSERT_EQUAL(0, clock_format_utc(-1, buf, sizeof buf));
    TEST_ASSERT_EQUAL(0, clock_format_utc(253402300800000LL, buf, sizeof buf));
    TEST_ASSERT_EQUAL(0, clock_format_utc(0, small, sizeof small));
    TEST_ASSERT_EQUAL(0, clock_format_utc(0, NULL, 30));
}

int main(void) {
    UNITY_BEGIN();
    RUN_TEST(test_boot_is_unsynchronized);
    RUN_TEST(test_sync_gives_sntp_and_runs_on_monotonic_time);
    RUN_TEST(test_link_loss_is_holdover_with_age);
    RUN_TEST(test_stale_sync_is_holdover_even_with_link);
    RUN_TEST(test_resync_returns_to_sntp);
    RUN_TEST(test_link_up_alone_does_not_synchronize);
    RUN_TEST(test_wall_clock_step_does_not_change_uptime);
    RUN_TEST(test_format_rfc3339_with_millis);
    RUN_TEST(test_format_rejects_bad_input);
    return UNITY_END();
}
