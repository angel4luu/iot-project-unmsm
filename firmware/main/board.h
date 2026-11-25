// Board pin map for the ESP32-S3-DevKitC-1 node (plan.md, Front end and pin allocation).
//
// Analog inputs use ADC1 only (ADC2 is unusable while Wi-Fi is on). Never use the
// strapping pins (GPIO0, 3, 45, 46), the USB pins (GPIO19, 20), or the
// octal-PSRAM pins of some modules (GPIO35-37). The static asserts below keep it so.
#pragma once

// Analog front end: ADC1, continuous (DMA) mode, alternating V/I.
#define BOARD_ADC_UNIT 1
#define BOARD_PIN_VOLTAGE 4 // ADC1_CH3, R1/R2 junction, 22 nF to GND
#define BOARD_ADC_CH_VOLTAGE 3
#define BOARD_PIN_CURRENT 5 // ADC1_CH4, R3/R4 junction, 22 nF to GND
#define BOARD_ADC_CH_CURRENT 4
#define BOARD_ADC_CONVERSIONS_PER_S 8000 // 4,000 V/I pairs per second

// OLED on I2C (module has its own pull-ups).
#define BOARD_PIN_I2C_SDA 8
#define BOARD_PIN_I2C_SCL 9

// Buzzer: 1 kOhm to the 2N2222 base; active 5 V buzzer between 5 V and collector.
#define BOARD_PIN_BUZZER 16

// RGB status LED, common cathode, 470 Ohm in series with each anode.
#define BOARD_PIN_LED_RED 17
#define BOARD_PIN_LED_GREEN 18
#define BOARD_PIN_LED_BLUE 21

#define BOARD_PIN_FORBIDDEN(p)                                                                     \
    ((p) == 0 || (p) == 3 || (p) == 45 || (p) == 46 || (p) == 19 || (p) == 20 ||                   \
     ((p) >= 35 && (p) <= 37))

// ESP32-S3 ADC1 covers GPIO1-GPIO10 (channel = GPIO - 1).
#define BOARD_PIN_IS_ADC1(p, ch) ((p) >= 1 && (p) <= 10 && (ch) == (p) - 1)

_Static_assert(BOARD_PIN_IS_ADC1(BOARD_PIN_VOLTAGE, BOARD_ADC_CH_VOLTAGE), "voltage on ADC1");
_Static_assert(BOARD_PIN_IS_ADC1(BOARD_PIN_CURRENT, BOARD_ADC_CH_CURRENT), "current on ADC1");
_Static_assert(!BOARD_PIN_FORBIDDEN(BOARD_PIN_VOLTAGE), "forbidden pin");
_Static_assert(!BOARD_PIN_FORBIDDEN(BOARD_PIN_CURRENT), "forbidden pin");
_Static_assert(!BOARD_PIN_FORBIDDEN(BOARD_PIN_I2C_SDA), "forbidden pin");
_Static_assert(!BOARD_PIN_FORBIDDEN(BOARD_PIN_I2C_SCL), "forbidden pin");
_Static_assert(!BOARD_PIN_FORBIDDEN(BOARD_PIN_BUZZER), "forbidden pin");
_Static_assert(!BOARD_PIN_FORBIDDEN(BOARD_PIN_LED_RED), "forbidden pin");
_Static_assert(!BOARD_PIN_FORBIDDEN(BOARD_PIN_LED_GREEN), "forbidden pin");
_Static_assert(!BOARD_PIN_FORBIDDEN(BOARD_PIN_LED_BLUE), "forbidden pin");
