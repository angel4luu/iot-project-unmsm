// T037: monotonic Wh integration and NVS checkpoint recovery (research R-003).
#include <string.h>

#include "checkpoint.h"
#include "fake_nvs.h"
#include "metering.h"
#include "unity.h"

static fake_nvs_t fake;
static nvs_port_t nvs;
static int uuids;

void setUp(void) {
    nvs = fake_nvs_init(&fake);
    uuids = 0;
}

void tearDown(void) {
    fake_nvs_free(&fake);
}

static void uuid(char out[METERING_UUID_LEN + 1], void *ctx) {
    (void)ctx;
    uuids++;
    snprintf(out, METERING_UUID_LEN + 1, "123e4567-e89b-42d3-9456-42661417%04d", uuids);
}

static const int64_t S = 1000000;

static void test_first_boot_starts_a_new_counter_at_zero(void) {
    checkpoint_state_t st;
    energy_counter_t e;
    TEST_ASSERT_EQUAL(CHECKPOINT_NEW_COUNTER, checkpoint_restore(&nvs, &st, &e, uuid, NULL, 0));
    TEST_ASSERT_EQUAL_DOUBLE(0.0, e.total_wh);
    TEST_ASSERT_EQUAL_STRING("123e4567-e89b-42d3-9456-426614170001", e.counter_id);
}

static void test_saves_every_60_s_only(void) {
    checkpoint_state_t st;
    energy_counter_t e;
    checkpoint_restore(&nvs, &st, &e, uuid, NULL, 0);
    const int sets = fake.sets;
    TEST_ASSERT_TRUE(checkpoint_save(&nvs, &st, &e, false, false, 59 * S));
    TEST_ASSERT_EQUAL_INT(sets, fake.sets);
    TEST_ASSERT_TRUE(checkpoint_save(&nvs, &st, &e, false, false, 60 * S));
    TEST_ASSERT_EQUAL_INT(sets + 1, fake.sets);
}

static void test_orderly_shutdown_resumes_without_flag(void) {
    checkpoint_state_t st;
    energy_counter_t e;
    checkpoint_restore(&nvs, &st, &e, uuid, NULL, 0);
    energy_add(&e, 20.0, 3600 * S); // 20 Wh
    TEST_ASSERT_TRUE(checkpoint_save(&nvs, &st, &e, true, true, 3600 * S));
    char id[METERING_UUID_LEN + 1];
    memcpy(id, e.counter_id, sizeof id);

    energy_counter_t r;
    TEST_ASSERT_EQUAL(CHECKPOINT_RESUMED_CLEAN, checkpoint_restore(&nvs, &st, &r, uuid, NULL, 0));
    TEST_ASSERT_EQUAL_STRING(id, r.counter_id);
    TEST_ASSERT_DOUBLE_WITHIN(1e-9, 20.0, r.total_wh);
}

static void test_crash_resumes_last_checkpoint_as_uncertain(void) {
    checkpoint_state_t st;
    energy_counter_t e;
    checkpoint_restore(&nvs, &st, &e, uuid, NULL, 0);
    energy_add(&e, 20.0, 60 * S);
    checkpoint_save(&nvs, &st, &e, false, false, 60 * S); // periodic save
    energy_add(&e, 20.0, 30 * S);                         // lost: no save before the crash

    energy_counter_t r;
    TEST_ASSERT_EQUAL(CHECKPOINT_RESUMED_UNCLEAN, checkpoint_restore(&nvs, &st, &r, uuid, NULL, 0));
    TEST_ASSERT_EQUAL_STRING(e.counter_id, r.counter_id); // same counter, flagged instead
    TEST_ASSERT_DOUBLE_WITHIN(1e-9, 20.0 * 60 / 3600.0, r.total_wh);
    TEST_ASSERT_EQUAL_INT(1, uuids);
}

static void test_restart_after_clean_resume_then_crash_is_unclean(void) {
    checkpoint_state_t st;
    energy_counter_t e;
    checkpoint_restore(&nvs, &st, &e, uuid, NULL, 0);
    checkpoint_save(&nvs, &st, &e, true, true, 0);
    TEST_ASSERT_EQUAL(CHECKPOINT_RESUMED_CLEAN, checkpoint_restore(&nvs, &st, &e, uuid, NULL, 0));
    // The restore marked the run as started; a crash now is detected next boot.
    TEST_ASSERT_EQUAL(CHECKPOINT_RESUMED_UNCLEAN, checkpoint_restore(&nvs, &st, &e, uuid, NULL, 0));
}

static void test_newest_valid_record_wins_and_corruption_falls_back(void) {
    checkpoint_state_t st;
    energy_counter_t e;
    checkpoint_restore(&nvs, &st, &e, uuid, NULL, 0); // writes seq 0 (ekp_a)
    e.total_wh = 1.0;
    checkpoint_save(&nvs, &st, &e, false, true, 0); // seq 1 (ekp_b)
    e.total_wh = 2.0;
    checkpoint_save(&nvs, &st, &e, false, true, 0); // seq 2 (ekp_a)

    // Corrupt the newest record (ekp_a): the older one (1.0 Wh) is used.
    unsigned char junk[8] = {1, 2, 3, 4, 5, 6, 7, 8};
    nvs.set_blob(nvs.ctx, "ekp_a", junk, sizeof junk);
    energy_counter_t r;
    TEST_ASSERT_EQUAL(CHECKPOINT_RESUMED_UNCLEAN, checkpoint_restore(&nvs, &st, &r, uuid, NULL, 0));
    TEST_ASSERT_EQUAL_DOUBLE(1.0, r.total_wh);
}

static void test_no_valid_record_means_new_counter(void) {
    unsigned char junk[8] = {0};
    nvs.set_blob(nvs.ctx, "ekp_a", junk, sizeof junk);
    nvs.set_blob(nvs.ctx, "ekp_b", junk, sizeof junk);
    checkpoint_state_t st;
    energy_counter_t r;
    TEST_ASSERT_EQUAL(CHECKPOINT_NEW_COUNTER, checkpoint_restore(&nvs, &st, &r, uuid, NULL, 0));
    TEST_ASSERT_EQUAL_DOUBLE(0.0, r.total_wh);
}

static void test_nvs_failure_is_reported(void) {
    checkpoint_state_t st;
    energy_counter_t e;
    checkpoint_restore(&nvs, &st, &e, uuid, NULL, 0);
    fake.fail_set_after = fake.sets;
    TEST_ASSERT_FALSE(checkpoint_save(&nvs, &st, &e, false, true, 0));
}

int main(void) {
    UNITY_BEGIN();
    RUN_TEST(test_first_boot_starts_a_new_counter_at_zero);
    RUN_TEST(test_saves_every_60_s_only);
    RUN_TEST(test_orderly_shutdown_resumes_without_flag);
    RUN_TEST(test_crash_resumes_last_checkpoint_as_uncertain);
    RUN_TEST(test_restart_after_clean_resume_then_crash_is_unclean);
    RUN_TEST(test_newest_valid_record_wins_and_corruption_falls_back);
    RUN_TEST(test_no_valid_record_means_new_counter);
    RUN_TEST(test_nvs_failure_is_reported);
    return UNITY_END();
}
