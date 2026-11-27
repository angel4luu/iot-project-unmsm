// T026: the pin map keeps the plan's allocation (static asserts run at compile time).
#include "board.h"
#include "unity.h"

void setUp(void) {}
void tearDown(void) {}

static void test_pin_allocation_matches_plan(void) {
    TEST_ASSERT_EQUAL(4, BOARD_PIN_VOLTAGE);
    TEST_ASSERT_EQUAL(5, BOARD_PIN_CURRENT);
    TEST_ASSERT_EQUAL(8, BOARD_PIN_I2C_SDA);
    TEST_ASSERT_EQUAL(9, BOARD_PIN_I2C_SCL);
    TEST_ASSERT_EQUAL(16, BOARD_PIN_BUZZER);
    TEST_ASSERT_EQUAL(17, BOARD_PIN_LED_RED);
    TEST_ASSERT_EQUAL(18, BOARD_PIN_LED_GREEN);
    TEST_ASSERT_EQUAL(15, BOARD_PIN_LED_BLUE);
    TEST_ASSERT_EQUAL(8000, BOARD_ADC_CONVERSIONS_PER_S);
}

static void test_forbidden_pins_are_detected(void) {
    const int forbidden[] = {0, 3, 19, 20, 35, 36, 37, 45, 46};
    for (size_t i = 0; i < sizeof forbidden / sizeof forbidden[0]; i++) {
        TEST_ASSERT_TRUE(BOARD_PIN_FORBIDDEN(forbidden[i]));
    }
    TEST_ASSERT_FALSE(BOARD_PIN_FORBIDDEN(4));
    TEST_ASSERT_FALSE(BOARD_PIN_IS_ADC1(11, 10)); // ADC2 territory
}

int main(void) {
    UNITY_BEGIN();
    RUN_TEST(test_pin_allocation_matches_plan);
    RUN_TEST(test_forbidden_pins_are_detected);
    return UNITY_END();
}
