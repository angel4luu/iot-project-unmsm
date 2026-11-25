// UI hardware (T050): SSD1306 OLED over I2C, RGB status LED, and active buzzer.
// The display content comes from ui_render() (ui_state.h); this only drives pins.
#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "ui_state.h"

// 0 for the SSD1306 (default); 2 for an SH1106 132-column controller (open decision:
// set it once the team's module is identified, build guide stage 2).
#ifndef UI_OLED_COLUMN_OFFSET
#define UI_OLED_COLUMN_OFFSET 0
#endif

// The plan's LED is common cathode (pin high = on). Set to 1 for common anode.
#ifndef UI_LED_COMMON_ANODE
#define UI_LED_COMMON_ANODE 0
#endif

typedef struct {
    int pin_sda, pin_scl;
    int pin_red, pin_green, pin_blue;
    int pin_buzzer;
} ui_pins_t;

// False when no OLED answers at 0x3C/0x3D; the LED and buzzer still work.
bool ui_hw_init(const ui_pins_t *pins);
void ui_hw_show(const ui_view_t *view);
