// T038: LED/OLED state mapping (plan › Local indication); a value that is not
// `valid` is never shown as a plain reading.
#include <string.h>

#include "ui_state.h"
#include "unity.h"

static ui_input_t in;
static ui_view_t v;

void setUp(void) {
    in = (ui_input_t){
        .have_summary = true,
        .quality = QUALITY_VALID,
        .v_rms_v = 12.6,
        .i_rms_a = 1.62,
        .active_power_w = 20.4,
        .energy_wh = 12543.8,
        .calibration_accepted = true,
        .calibration_nominal = true,
        .clock = CLOCK_SOURCE_SNTP,
        .link_up = true,
    };
}

void tearDown(void) {}

static bool shows(const char *text) {
    for (int k = 0; k < UI_LINES; k++) {
        if (strstr(v.lines[k], text) != NULL) {
            return true;
        }
    }
    return false;
}

static bool shows_any_reading(void) {
    return shows("12.6") || shows("1.62") || shows("20.4") || shows("12543");
}

static void check_font_and_width(void) {
    for (int k = 0; k < UI_LINES; k++) {
        TEST_ASSERT_TRUE(strlen(v.lines[k]) <= UI_COLS);
        for (const char *p = v.lines[k]; *p; p++) {
            TEST_ASSERT_TRUE_MESSAGE((*p >= 'A' && *p <= 'Z') || (*p >= '0' && *p <= '9') ||
                                         strchr(" -:.", *p) != NULL,
                                     v.lines[k]);
        }
    }
}

static void test_normal_is_green_with_units_quality_clock_link_and_marker(void) {
    ui_render(&in, &v);
    TEST_ASSERT_EQUAL(UI_MODE_NORMAL, v.mode);
    TEST_ASSERT_EQUAL(UI_LED_GREEN, v.led);
    TEST_ASSERT_FALSE(v.buzzer);
    TEST_ASSERT_TRUE(shows("12.60 V"));
    TEST_ASSERT_TRUE(shows("1.620 A"));
    TEST_ASSERT_TRUE(shows("20.40 W"));
    TEST_ASSERT_TRUE(shows("12543.800 WH"));
    TEST_ASSERT_TRUE(shows("VALIDA"));
    TEST_ASSERT_TRUE(shows("SNTP"));
    TEST_ASSERT_TRUE(shows("RED OK"));
    TEST_ASSERT_TRUE(shows("NO VALIDADO"));
    check_font_and_width();
}

static void test_warning_is_red_with_buzzer_value_and_limit(void) {
    in.warning_active = true;
    in.warning_value_w = 21.0;
    in.warning_limit_w = 15.0;
    ui_render(&in, &v);
    TEST_ASSERT_EQUAL(UI_LED_RED, v.led);
    TEST_ASSERT_TRUE(v.buzzer);
    TEST_ASSERT_TRUE(shows("21.0 W"));
    TEST_ASSERT_TRUE(shows("LIMITE 15.0 W"));
    check_font_and_width();
}

static void test_invalid_or_degraded_is_yellow_with_reason_and_no_reading(void) {
    const quality_state_t states[] = {QUALITY_INVALID, QUALITY_DEGRADED};
    for (size_t k = 0; k < 2; k++) {
        setUp();
        in.quality = states[k];
        in.flags = QF_SAMPLE_GAP;
        ui_render(&in, &v);
        TEST_ASSERT_EQUAL(UI_MODE_INVALID, v.mode);
        TEST_ASSERT_EQUAL(UI_LED_YELLOW, v.led);
        TEST_ASSERT_TRUE(shows("SAMPLE GAP"));
        TEST_ASSERT_FALSE(shows_any_reading());
        check_font_and_width();
    }
}

static void test_unsynchronized_clock_is_yellow(void) {
    in.clock = CLOCK_SOURCE_UNSYNCHRONIZED;
    ui_render(&in, &v);
    TEST_ASSERT_EQUAL(UI_LED_YELLOW, v.led);
    TEST_ASSERT_FALSE(shows_any_reading());
    TEST_ASSERT_TRUE(shows("SIN HORA"));
}

static void test_offline_is_blue_with_queue_count(void) {
    in.link_up = false;
    in.queued = 37;
    ui_render(&in, &v);
    TEST_ASSERT_EQUAL(UI_MODE_OFFLINE, v.mode);
    TEST_ASSERT_EQUAL(UI_LED_BLUE, v.led);
    TEST_ASSERT_TRUE(shows("EN COLA: 37"));
    TEST_ASSERT_TRUE(shows("SIN RED"));
    TEST_ASSERT_TRUE(shows("20.40 W")); // valid local values keep working offline
}

static void test_insufficient_data_is_white_with_reason(void) {
    in.warming_up = true;
    ui_render(&in, &v);
    TEST_ASSERT_EQUAL(UI_LED_WHITE, v.led);
    TEST_ASSERT_TRUE(shows("CALENTANDO"));
    setUp();
    in.calibration_accepted = false;
    ui_render(&in, &v);
    TEST_ASSERT_EQUAL(UI_MODE_INSUFFICIENT, v.mode);
    TEST_ASSERT_TRUE(shows("SIN CALIBRACION"));
    TEST_ASSERT_FALSE(shows_any_reading());
    setUp();
    in.have_summary = false;
    ui_render(&in, &v);
    TEST_ASSERT_TRUE(shows("ESPERANDO VENTANA"));
}

static void test_warning_never_shows_a_non_valid_value(void) {
    in.warning_active = true;
    in.warning_value_w = 21.0;
    in.quality = QUALITY_DEGRADED;
    ui_render(&in, &v);
    TEST_ASSERT_FALSE(shows("21.0"));
    TEST_ASSERT_TRUE(shows("VALOR NO VALIDO"));
}

static void test_priority_order(void) {
    in.warning_active = true;
    in.link_up = false;
    in.quality = QUALITY_INVALID;
    ui_render(&in, &v);
    TEST_ASSERT_EQUAL(UI_MODE_WARNING, v.mode);
    in.warning_active = false;
    in.warming_up = true;
    ui_render(&in, &v);
    TEST_ASSERT_EQUAL(UI_MODE_INSUFFICIENT, v.mode);
    in.warming_up = false;
    ui_render(&in, &v);
    TEST_ASSERT_EQUAL(UI_MODE_INVALID, v.mode); // invalid before offline
}

int main(void) {
    UNITY_BEGIN();
    RUN_TEST(test_normal_is_green_with_units_quality_clock_link_and_marker);
    RUN_TEST(test_warning_is_red_with_buzzer_value_and_limit);
    RUN_TEST(test_invalid_or_degraded_is_yellow_with_reason_and_no_reading);
    RUN_TEST(test_unsynchronized_clock_is_yellow);
    RUN_TEST(test_offline_is_blue_with_queue_count);
    RUN_TEST(test_insufficient_data_is_white_with_reason);
    RUN_TEST(test_warning_never_shows_a_non_valid_value);
    RUN_TEST(test_priority_order);
    return UNITY_END();
}
