// T030: provisioning protocol, validation, NVS writes, and secret hygiene.
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "fake_nvs.h"
#include "provisioning.h"
#include "unity.h"

static fake_nvs_t fake;
static nvs_port_t nvs;
static prov_session_t *s;
static char reply[PROV_REPLY_MAX];

static const char *CERT = "-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n";
static const char *KEY = "-----BEGIN PRIVATE KEY-----\nMIGH\n-----END PRIVATE KEY-----\n";

void setUp(void) {
    nvs = fake_nvs_init(&fake);
    s = malloc(sizeof *s);
    prov_session_init(s, &nvs);
}

void tearDown(void) {
    free(s);
    fake_nvs_free(&fake);
}

static const char *send(const char *line) {
    prov_handle_line(s, line, reply, sizeof reply);
    return reply;
}

static const char *set(const char *key, const char *value) {
    static char line[2 * PROV_PEM_MAX + 64];
    int n = snprintf(line, sizeof line, "set %s ", key);
    for (const char *p = value; *p && n < (int)sizeof line - 3; p++) {
        n += snprintf(line + n, sizeof line - (size_t)n, "%02x", (unsigned char)*p);
    }
    return send(line);
}

static void stage_all(void) {
    TEST_ASSERT_EQUAL_STRING("ok", set("node_id", "node-001"));
    TEST_ASSERT_EQUAL_STRING("ok", set("wifi_ssid", "lab-wifi"));
    TEST_ASSERT_EQUAL_STRING("ok", set("wifi_pass", "correct horse"));
    TEST_ASSERT_EQUAL_STRING("ok", set("mqtt_host", "broker.lab.internal"));
    TEST_ASSERT_EQUAL_STRING("ok", set("mqtt_port", "8883"));
    TEST_ASSERT_EQUAL_STRING("ok", set("ca_cert", CERT));
    TEST_ASSERT_EQUAL_STRING("ok", set("node_cert", CERT));
    TEST_ASSERT_EQUAL_STRING("ok", set("node_key", KEY));
}

static void test_full_provisioning_round_trip(void) {
    TEST_ASSERT_EQUAL_STRING("ok empty", send("status"));
    stage_all();
    TEST_ASSERT_EQUAL_STRING("ok", send("commit"));
    TEST_ASSERT_EQUAL(1, fake.commits);
    TEST_ASSERT_EQUAL_STRING("ok provisioned", send("status"));
    prov_config_t *cfg = malloc(sizeof *cfg);
    TEST_ASSERT_TRUE(prov_load(&nvs, cfg));
    TEST_ASSERT_EQUAL_STRING("node-001", cfg->node_id);
    TEST_ASSERT_EQUAL_STRING("correct horse", cfg->wifi_pass);
    TEST_ASSERT_EQUAL_STRING("8883", cfg->mqtt_port);
    TEST_ASSERT_EQUAL_STRING(KEY, cfg->node_key);
    free(cfg);
}

static void test_commit_wipes_staged_secrets(void) {
    stage_all();
    send("commit");
    prov_config_t zero;
    memset(&zero, 0, sizeof zero);
    TEST_ASSERT_EQUAL_MEMORY(&zero, &s->staged, sizeof zero);
}

static void test_missing_key_blocks_commit_and_writes_nothing(void) {
    stage_all();
    send("set node_key");
    TEST_ASSERT_EQUAL_STRING("err syntax", reply);
    s->present[PROV_KEY_NODE_KEY] = false;
    TEST_ASSERT_EQUAL_STRING("err missing node_key", send("commit"));
    TEST_ASSERT_EQUAL(0, fake.sets);
    TEST_ASSERT_EQUAL_STRING("ok empty", send("status"));
}

static void test_invalid_values_are_refused(void) {
    struct {
        const char *key, *value;
    } cases[] = {
        {"node_id", "Node-001"},   {"node_id", "-node"},   {"wifi_pass", "short"},
        {"mqtt_host", "bad host"}, {"mqtt_port", "70000"}, {"mqtt_port", "0"},
        {"ca_cert", "not a pem"},  {"node_key", CERT},
    };
    tearDown(); // each case below gets a fresh session and NVS
    for (size_t i = 0; i < sizeof cases / sizeof cases[0]; i++) {
        setUp();
        stage_all();
        set(cases[i].key, cases[i].value);
        char want[PROV_REPLY_MAX];
        snprintf(want, sizeof want, "err invalid_value %s", cases[i].key);
        TEST_ASSERT_EQUAL_STRING_MESSAGE(want, send("commit"), cases[i].value);
        TEST_ASSERT_EQUAL(0, fake.sets);
        tearDown();
    }
    setUp();
}

static void test_bad_hex_and_overlong_values(void) {
    TEST_ASSERT_EQUAL_STRING("err bad_hex wifi_ssid", send("set wifi_ssid 6g"));
    TEST_ASSERT_EQUAL_STRING("err bad_hex wifi_ssid", send("set wifi_ssid 616"));
    TEST_ASSERT_EQUAL_STRING("err bad_hex wifi_ssid", send("set wifi_ssid 6100"));
    char ssid[40];
    memset(ssid, 'a', 33);
    ssid[33] = '\0';
    TEST_ASSERT_EQUAL_STRING("err too_long wifi_ssid", set("wifi_ssid", ssid));
    TEST_ASSERT_FALSE(s->present[PROV_KEY_WIFI_SSID]);
}

static void test_unknown_input_is_refused(void) {
    TEST_ASSERT_EQUAL_STRING("err unknown_key", send("set admin_password 61"));
    TEST_ASSERT_EQUAL_STRING("err unknown_command", send("dump"));
    TEST_ASSERT_EQUAL_STRING("err unknown_command", send(""));
}

static void test_replies_never_echo_values(void) {
    TEST_ASSERT_NULL(strstr(set("wifi_pass", "s3cret-pass"), "s3cret"));
    TEST_ASSERT_NULL(strstr(set("wifi_pass", "x"), "x "));
}

static void test_abort_wipes(void) {
    stage_all();
    TEST_ASSERT_EQUAL_STRING("ok", send("abort"));
    TEST_ASSERT_EQUAL_STRING("err missing node_id", send("commit"));
}

static void test_nvs_failure_is_reported_and_wipes(void) {
    fake.fail_set_after = 3;
    stage_all();
    TEST_ASSERT_EQUAL_STRING("err nvs_error mqtt_host", send("commit"));
    TEST_ASSERT_FALSE(s->present[PROV_KEY_NODE_ID]);
    for (int i = 0; i < FAKE_NVS_SLOTS; i++) {
        TEST_ASSERT_FALSE_MESSAGE(fake.slots[i].used, "partial credentials left in NVS");
    }
    TEST_ASSERT_EQUAL_STRING("ok empty", send("status"));
}

static void test_tampered_nvs_does_not_load(void) {
    stage_all();
    send("commit");
    nvs.set_blob(nvs.ctx, "mqtt_port", "99999", 5);
    TEST_ASSERT_FALSE(prov_is_provisioned(&nvs));
}

int main(void) {
    UNITY_BEGIN();
    RUN_TEST(test_full_provisioning_round_trip);
    RUN_TEST(test_commit_wipes_staged_secrets);
    RUN_TEST(test_missing_key_blocks_commit_and_writes_nothing);
    RUN_TEST(test_invalid_values_are_refused);
    RUN_TEST(test_bad_hex_and_overlong_values);
    RUN_TEST(test_unknown_input_is_refused);
    RUN_TEST(test_replies_never_echo_values);
    RUN_TEST(test_abort_wipes);
    RUN_TEST(test_nvs_failure_is_reported_and_wipes);
    RUN_TEST(test_tampered_nvs_does_not_load);
    return UNITY_END();
}
