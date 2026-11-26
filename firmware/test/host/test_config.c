// T077: retained threshold configuration: parsing, MVP bounds, NVS storage of the
// last accepted version, and rollback rejection by config_version (T081).
#include <stdio.h>
#include <string.h>

#include "fake_nvs.h"
#include "threshold_config.h"
#include "unity.h"

static fake_nvs_t fake;
static nvs_port_t nvs;
static char json[768];

void setUp(void) {
    nvs = fake_nvs_init(&fake);
}

void tearDown(void) {
    fake_nvs_free(&fake);
}

// A contract-valid payload (as `energyctl threshold publish` sends it) with overrides.
static const char *payload(unsigned version, const char *limit, const char *confirm,
                           const char *clear_below, const char *clear_ms) {
    char confirm_member[48] = "";
    if (confirm != NULL) {
        snprintf(confirm_member, sizeof confirm_member, "\"confirm_ms\":%s,", confirm);
    }
    snprintf(json, sizeof json,
             "{\"schema_version\":\"1.0.0\",\"config_version\":%u,\"node_id\":\"node-001\","
             "\"circuit_id\":\"lab-load-001\",\"effective_at\":\"2026-11-25T15:00:00.000Z\","
             "\"active_power_limit_W\":%s,%s\"clear_below_W\":%s,\"clear_ms\":%s,"
             "\"severity\":\"warning\",\"local_warning_enabled\":true}",
             version, limit, confirm_member, clear_below, clear_ms);
    return json;
}

static thr_cfg_parse_t parse(const char *s, thr_config_t *out) {
    return threshold_config_parse(s, strlen(s), "node-001", "lab-load-001", out);
}

static thr_config_t parsed(unsigned version, const char *limit) {
    thr_config_t c;
    TEST_ASSERT_EQUAL(THR_CFG_OK, parse(payload(version, limit, "10000", "14.25", "5000"), &c));
    return c;
}

static void test_parses_a_contract_payload(void) {
    thr_config_t c;
    TEST_ASSERT_EQUAL(THR_CFG_OK, parse(payload(3, "15", "12000", "14.25", "5000"), &c));
    TEST_ASSERT_EQUAL_UINT32(3, c.config_version);
    TEST_ASSERT_DOUBLE_WITHIN(1e-9, 15.0, c.limit_w);
    TEST_ASSERT_DOUBLE_WITHIN(1e-9, 14.25, c.clear_below_w);
    TEST_ASSERT_EQUAL_UINT32(12000, c.confirm_ms);
    TEST_ASSERT_EQUAL_UINT32(5000, c.clear_ms);
    TEST_ASSERT_EQUAL(SEVERITY_WARNING, c.severity);
    TEST_ASSERT_TRUE(c.local_warning_enabled);
}

static void test_spaced_json_and_critical_severity(void) {
    const char *s = "{ \"schema_version\" : \"1.0.0\", \"config_version\": 9, "
                    "\"node_id\": \"node-001\", \"circuit_id\": \"lab-load-001\", "
                    "\"effective_at\": \"2026-11-25T15:00:00Z\", \"active_power_limit_W\": 2.5e1, "
                    "\"confirm_ms\": 1000, \"clear_below_W\": 0, \"clear_ms\": 300000, "
                    "\"severity\": \"critical\", \"local_warning_enabled\": false }";
    thr_config_t c;
    TEST_ASSERT_EQUAL(THR_CFG_OK, parse(s, &c));
    TEST_ASSERT_DOUBLE_WITHIN(1e-9, 25.0, c.limit_w);
    TEST_ASSERT_EQUAL(SEVERITY_CRITICAL, c.severity);
    TEST_ASSERT_FALSE(c.local_warning_enabled);
}

static void test_confirm_ms_defaults_to_ten_seconds(void) {
    thr_config_t c;
    TEST_ASSERT_EQUAL(THR_CFG_OK, parse(payload(1, "15", NULL, "14.25", "5000"), &c));
    TEST_ASSERT_EQUAL_UINT32(THR_CONFIRM_MS_DEFAULT, c.confirm_ms);
    TEST_ASSERT_EQUAL_UINT32(10000, THR_CONFIRM_MS_DEFAULT);
}

static void test_limit_bounds(void) {
    thr_config_t c;
    TEST_ASSERT_EQUAL(THR_CFG_OK, parse(payload(1, "25", "10000", "1", "5000"), &c));
    TEST_ASSERT_EQUAL(THR_CFG_OK, parse(payload(1, "0.5", "10000", "0", "5000"), &c));
    TEST_ASSERT_EQUAL(THR_CFG_OUT_OF_BOUNDS, parse(payload(1, "25.001", "10000", "1", "5000"), &c));
    TEST_ASSERT_EQUAL(THR_CFG_OUT_OF_BOUNDS, parse(payload(1, "2500", "10000", "1", "5000"), &c));
    TEST_ASSERT_EQUAL(THR_CFG_OUT_OF_BOUNDS, parse(payload(1, "0", "10000", "0", "5000"), &c));
    TEST_ASSERT_EQUAL(THR_CFG_OUT_OF_BOUNDS, parse(payload(1, "-5", "10000", "0", "5000"), &c));
}

static void test_confirm_and_clear_duration_bounds(void) {
    thr_config_t c;
    TEST_ASSERT_EQUAL(THR_CFG_OK, parse(payload(1, "15", "1000", "14", "1000"), &c));
    TEST_ASSERT_EQUAL(THR_CFG_OK, parse(payload(1, "15", "300000", "14", "300000"), &c));
    TEST_ASSERT_EQUAL(THR_CFG_OUT_OF_BOUNDS, parse(payload(1, "15", "999", "14", "5000"), &c));
    TEST_ASSERT_EQUAL(THR_CFG_OUT_OF_BOUNDS, parse(payload(1, "15", "300001", "14", "5000"), &c));
    TEST_ASSERT_EQUAL(THR_CFG_OUT_OF_BOUNDS, parse(payload(1, "15", "10000", "14", "999"), &c));
    TEST_ASSERT_EQUAL(THR_CFG_OUT_OF_BOUNDS, parse(payload(1, "15", "10000", "14", "300001"), &c));
    TEST_ASSERT_EQUAL(THR_CFG_BAD_JSON, parse(payload(1, "15", "1000.5", "14", "5000"), &c));
}

static void test_clear_below_bounds(void) {
    thr_config_t c;
    TEST_ASSERT_EQUAL(THR_CFG_OK, parse(payload(1, "15", "10000", "0", "5000"), &c));
    TEST_ASSERT_EQUAL(THR_CFG_OK, parse(payload(1, "15", "10000", "14.999", "5000"), &c));
    TEST_ASSERT_EQUAL(THR_CFG_OUT_OF_BOUNDS, parse(payload(1, "15", "10000", "15", "5000"), &c));
    TEST_ASSERT_EQUAL(THR_CFG_OUT_OF_BOUNDS, parse(payload(1, "15", "10000", "16", "5000"), &c));
    TEST_ASSERT_EQUAL(THR_CFG_OUT_OF_BOUNDS, parse(payload(1, "15", "10000", "-0.1", "5000"), &c));
}

static void test_rejects_other_targets_and_malformed_payloads(void) {
    thr_config_t c;
    const char *ok = payload(1, "15", "10000", "14", "5000");
    TEST_ASSERT_EQUAL(THR_CFG_WRONG_TARGET,
                      threshold_config_parse(ok, strlen(ok), "node-002", "lab-load-001", &c));
    TEST_ASSERT_EQUAL(THR_CFG_WRONG_TARGET,
                      threshold_config_parse(ok, strlen(ok), "node-001", "other-load", &c));
    char bad[768];
    strcpy(bad, ok);
    memcpy(strstr(bad, "1.0.0"), "2.0.0", 5);
    TEST_ASSERT_EQUAL(THR_CFG_BAD_SCHEMA, parse(bad, &c));
    strcpy(bad, ok);
    memcpy(strstr(bad, "\"warning\""), "\"urgent!\"", 9);
    TEST_ASSERT_EQUAL(THR_CFG_BAD_JSON, parse(bad, &c));
    TEST_ASSERT_EQUAL(THR_CFG_BAD_JSON, parse("{}", &c));
    TEST_ASSERT_EQUAL(THR_CFG_BAD_JSON, parse("not json", &c));
    TEST_ASSERT_EQUAL(THR_CFG_BAD_JSON, parse(payload(0, "15", "10000", "14", "5000"), &c));
    // Truncated: the payload is not NUL-terminated on the wire; only `len` counts.
    TEST_ASSERT_EQUAL(THR_CFG_BAD_JSON,
                      threshold_config_parse(ok, strlen(ok) / 2, "node-001", "lab-load-001", &c));
}

static void test_accept_stores_and_survives_reboot(void) {
    thr_config_t loaded;
    TEST_ASSERT_FALSE(threshold_config_load(&nvs, &loaded));
    const thr_config_t c = parsed(4, "15");
    TEST_ASSERT_EQUAL(THR_CFG_ACCEPTED, threshold_config_accept(&nvs, &c));
    TEST_ASSERT_TRUE(threshold_config_load(&nvs, &loaded));
    TEST_ASSERT_TRUE(threshold_config_equal(&c, &loaded));
}

static void test_rollback_is_rejected(void) {
    const thr_config_t v5 = parsed(5, "15");
    TEST_ASSERT_EQUAL(THR_CFG_ACCEPTED, threshold_config_accept(&nvs, &v5));
    const thr_config_t v4 = parsed(4, "20");
    TEST_ASSERT_EQUAL(THR_CFG_ROLLBACK, threshold_config_accept(&nvs, &v4));
    const thr_config_t v5b = parsed(5, "20"); // same version, other content
    TEST_ASSERT_EQUAL(THR_CFG_ROLLBACK, threshold_config_accept(&nvs, &v5b));
    TEST_ASSERT_EQUAL(THR_CFG_UNCHANGED, threshold_config_accept(&nvs, &v5)); // retained resend
    thr_config_t loaded;
    TEST_ASSERT_TRUE(threshold_config_load(&nvs, &loaded));
    TEST_ASSERT_EQUAL_UINT32(5, loaded.config_version);
    TEST_ASSERT_DOUBLE_WITHIN(1e-9, 15.0, loaded.limit_w);
    const thr_config_t v6 = parsed(6, "20");
    TEST_ASSERT_EQUAL(THR_CFG_ACCEPTED, threshold_config_accept(&nvs, &v6));
}

static void test_invalid_config_is_never_stored(void) {
    thr_config_t c = parsed(1, "15");
    c.clear_below_w = 15.0;
    TEST_ASSERT_EQUAL(THR_CFG_INVALID, threshold_config_accept(&nvs, &c));
    thr_config_t loaded;
    TEST_ASSERT_FALSE(threshold_config_load(&nvs, &loaded));
}

static void test_nvs_failure_is_not_applied(void) {
    fake.fail_set_after = 0;
    const thr_config_t c = parsed(1, "15");
    TEST_ASSERT_EQUAL(THR_CFG_NVS_ERROR, threshold_config_accept(&nvs, &c));
    thr_config_t loaded;
    TEST_ASSERT_FALSE(threshold_config_load(&nvs, &loaded));
}

static void test_corrupt_record_loads_as_none(void) {
    const thr_config_t c = parsed(2, "15");
    TEST_ASSERT_EQUAL(THR_CFG_ACCEPTED, threshold_config_accept(&nvs, &c));
    for (int k = 0; k < FAKE_NVS_SLOTS; k++) {
        if (fake.slots[k].used && fake.slots[k].len > 8) {
            fake.slots[k].data[8] ^= 0xFF;
        }
    }
    thr_config_t loaded;
    TEST_ASSERT_FALSE(threshold_config_load(&nvs, &loaded));
}

int main(void) {
    UNITY_BEGIN();
    RUN_TEST(test_parses_a_contract_payload);
    RUN_TEST(test_spaced_json_and_critical_severity);
    RUN_TEST(test_confirm_ms_defaults_to_ten_seconds);
    RUN_TEST(test_limit_bounds);
    RUN_TEST(test_confirm_and_clear_duration_bounds);
    RUN_TEST(test_clear_below_bounds);
    RUN_TEST(test_rejects_other_targets_and_malformed_payloads);
    RUN_TEST(test_accept_stores_and_survives_reboot);
    RUN_TEST(test_rollback_is_rejected);
    RUN_TEST(test_invalid_config_is_never_stored);
    RUN_TEST(test_nvs_failure_is_not_applied);
    RUN_TEST(test_corrupt_record_loads_as_none);
    return UNITY_END();
}
