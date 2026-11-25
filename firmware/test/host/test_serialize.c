// T097: the host build of serialize.c writes sample payloads to
// tests/fixtures/telemetry/firmware-*.json; tests/contract/test_firmware_payloads.py
// validates them against the normative JSON Schemas (`make firmware-test` runs
// first, then `make contracts-test`).
#include <math.h>
#include <stdio.h>
#include <string.h>

#include "serialize.h"
#include "unity.h"

#ifndef TELEMETRY_OUT
#error "TELEMETRY_OUT must point at tests/fixtures/telemetry"
#endif

static const node_identity_t ID = {
    .node_id = "node-001",
    .circuit_id = "lab-load-001",
    .boot_id = "123e4567-e89b-42d3-8456-426614174001",
    .firmware_version = "0.1.0",
    .hardware_revision = "proto-a",
};

static measurement_record_t m;
static char buf[SERIALIZE_MEASUREMENT_MAX];

void setUp(void) {
    memset(&m, 0, sizeof m);
    strcpy(m.message_id, "123e4567-e89b-42d3-a456-426614174000");
    strcpy(m.boot_id, ID.boot_id);
    strcpy(m.counter_id, "123e4567-e89b-42d3-9456-426614174002");
    strcpy(m.calibration_revision, "node-001-nominal-r1");
    m.sequence = 42;
    m.window_start_ms = 1791997200000; // 2026-10-14T17:00:00.000Z
    m.window_end_ms = 1791997205000;
    m.duration_ms = 5000;
    m.sample_count = 20000;
    m.clock_source = CLOCK_SOURCE_SNTP;
    m.last_sync_age_s = 30;
    m.uptime_ms = 3605000;
    m.quality = QUALITY_VALID;
    m.valid_sample_ratio = 1.0;
    m.v_rms_v = 12.6;
    m.i_rms_a = 1.62;
    m.active_power_w = 20.4;
    m.energy_wh = 12543.8;
}

void tearDown(void) {}

static void save(const char *name, const char *json) {
    char path[512];
    snprintf(path, sizeof path, "%s/firmware-%s.json", TELEMETRY_OUT, name);
    FILE *f = fopen(path, "w");
    TEST_ASSERT_NOT_NULL_MESSAGE(f, path);
    fputs(json, f);
    fputc('\n', f);
    fclose(f);
}

static void test_valid_measurement(void) {
    TEST_ASSERT_TRUE(serialize_measurement(&ID, &m, buf, sizeof buf) > 0);
    TEST_ASSERT_NOT_NULL(strstr(buf, "\"voltage_rms\":{\"value\":12.600,\"unit\":\"V\"}"));
    TEST_ASSERT_NOT_NULL(strstr(buf, "\"flags\":[]"));
    TEST_ASSERT_NOT_NULL(strstr(buf, "\"end\":\"2026-10-14T17:00:05.000Z\""));
    save("measurement-valid", buf);
}

static void test_invalid_measurement_has_null_values(void) {
    m.quality = QUALITY_INVALID;
    m.flags = QF_SAMPLE_GAP | QF_ADC_CLIPPED;
    m.valid_sample_ratio = 0.95;
    m.sample_count = 19000; // the record still holds numbers: they must not leak
    TEST_ASSERT_TRUE(serialize_measurement(&ID, &m, buf, sizeof buf) > 0);
    TEST_ASSERT_NULL(strstr(buf, "12.6"));
    TEST_ASSERT_NULL(strstr(buf, "20.4"));
    TEST_ASSERT_NOT_NULL(strstr(buf, "\"flags\":[\"sample_gap\",\"adc_clipped\"]"));
    save("measurement-invalid", buf);
}

static void test_holdover_measurement(void) {
    m.clock_source = CLOCK_SOURCE_HOLDOVER;
    m.last_sync_age_s = 4000;
    TEST_ASSERT_TRUE(serialize_measurement(&ID, &m, buf, sizeof buf) > 0);
    save("measurement-holdover", buf);
}

static void test_unsynchronized_degraded_measurement(void) {
    m.clock_source = CLOCK_SOURCE_UNSYNCHRONIZED;
    m.last_sync_age_s = -1;
    m.window_start_ms = 60000; // since boot: diagnostic only
    m.window_end_ms = 65000;
    m.quality = QUALITY_DEGRADED;
    m.flags = QF_CLOCK_UNSYNCHRONIZED | QF_CALIBRATION_MISSING | QF_ENERGY_CONTINUITY_UNCERTAIN;
    m.calibration_revision[0] = '\0';
    m.active_power_w = -0.25; // signed diagnostic value is kept
    TEST_ASSERT_TRUE(serialize_measurement(&ID, &m, buf, sizeof buf) > 0);
    TEST_ASSERT_NOT_NULL(strstr(buf, "\"last_sync_age_s\":null"));
    TEST_ASSERT_NOT_NULL(strstr(buf, "\"calibration_revision\":null"));
    TEST_ASSERT_NOT_NULL(strstr(buf, "\"value\":-0.250"));
    save("measurement-unsynchronized", buf);
}

static void test_degraded_value_outside_wire_bounds_is_null(void) {
    m.quality = QUALITY_DEGRADED;
    m.flags = QF_OUT_OF_RANGE;
    m.v_rms_v = 450.0; // beyond the schema's 300 V bound
    m.i_rms_a = NAN;
    TEST_ASSERT_TRUE(serialize_measurement(&ID, &m, buf, sizeof buf) > 0);
    TEST_ASSERT_NOT_NULL(strstr(buf, "\"voltage_rms\":{\"value\":null"));
    TEST_ASSERT_NOT_NULL(strstr(buf, "\"current_rms\":{\"value\":null"));
    save("measurement-out-of-bounds", buf);
}

static void test_status_and_event(void) {
    char sbuf[SERIALIZE_STATUS_MAX];
    const status_record_t s = {
        .observed_at_ms = 1791997230000,
        .state = NODE_ONLINE,
        .calibration_revision = "node-001-nominal-r1",
        .clock_source = CLOCK_SOURCE_SNTP,
        .acquisition_state = ACQ_SAMPLING,
        .pending_records = 3,
        .oldest_pending_age_s = 12,
        .last_valid_window_end_ms = 1791997225000,
    };
    TEST_ASSERT_TRUE(serialize_status(&ID, &s, sbuf, sizeof sbuf) > 0);
    save("status-online", sbuf);

    status_record_t will = s; // the retained last will
    will.state = NODE_OFFLINE;
    will.acquisition_state = ACQ_STOPPED;
    will.calibration_revision = NULL;
    will.last_valid_window_end_ms = -1;
    will.last_error_code = "connection_lost";
    TEST_ASSERT_TRUE(serialize_status(&ID, &will, sbuf, sizeof sbuf) > 0);
    save("status-last-will", sbuf);

    char ebuf[SERIALIZE_EVENT_MAX];
    event_record_t e = {
        .sequence = 43,
        .observed_at_ms = 1791997215000,
        .type = EVENT_MEASUREMENT_QUALITY_CHANGED,
        .severity = SEVERITY_INFO,
        .config_version = 1,
        .quality = QUALITY_INVALID,
        .reason_code = "sample_gap",
    };
    strcpy(e.event_id, "123e4567-e89b-42d3-a456-426614174010");
    TEST_ASSERT_TRUE(serialize_event(&ID, &e, ebuf, sizeof ebuf) > 0);
    TEST_ASSERT_NOT_NULL(strstr(ebuf, "\"measured_value\":null"));
    save("event-quality", ebuf);
}

static void test_refusals(void) {
    char tiny[64];
    TEST_ASSERT_EQUAL_size_t(0, serialize_measurement(&ID, &m, tiny, sizeof tiny));
    strcpy(m.message_id, "not-a-uuid");
    TEST_ASSERT_EQUAL_size_t(0, serialize_measurement(&ID, &m, buf, sizeof buf));
    setUp();
    m.flags = 1u << 20; // unknown flag
    TEST_ASSERT_EQUAL_size_t(0, serialize_measurement(&ID, &m, buf, sizeof buf));
    setUp();
    node_identity_t bad = ID;
    bad.node_id = "node\"001"; // would need escaping: refused, never emitted
    TEST_ASSERT_EQUAL_size_t(0, serialize_measurement(&bad, &m, buf, sizeof buf));
}

int main(void) {
    UNITY_BEGIN();
    RUN_TEST(test_valid_measurement);
    RUN_TEST(test_invalid_measurement_has_null_values);
    RUN_TEST(test_holdover_measurement);
    RUN_TEST(test_unsynchronized_degraded_measurement);
    RUN_TEST(test_degraded_value_outside_wire_bounds_is_null);
    RUN_TEST(test_status_and_event);
    RUN_TEST(test_refusals);
    return UNITY_END();
}
