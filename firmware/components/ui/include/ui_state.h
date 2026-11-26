// Local indication logic (T038, T050; plan › Local indication). Pure: decides the
// RGB LED colour, the buzzer, and the OLED text; ui.c drives the hardware.
//
// | Mode         | LED    | OLED                                                  |
// |--------------|--------|-------------------------------------------------------|
// | warning      | red    | alert banner with value and limit (buzzer on)          |
// | insufficient | white  | reason (warm-up, no summary yet, no accepted calibration) |
// | invalid      | yellow | value fields replaced by the quality reason            |
// | offline      | blue   | link state and number of queued records                |
// | normal       | green  | V, A, W, Wh with units, quality, clock and link state  |
//
// Priority is the table order. A value that is not `valid` is never shown as a
// plain reading (SC-006), and a nominal calibration always shows "NO VALIDADO".
// OLED text uses only capitals, digits, space and "-:." (the 5x7 font), at most
// UI_COLS characters per line, and is in Spanish for the bench team.
#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "clock.h"
#include "quality.h"

#define UI_LINES 8
#define UI_COLS 21

typedef enum {
    UI_MODE_NORMAL = 0,
    UI_MODE_WARNING,
    UI_MODE_INVALID,
    UI_MODE_OFFLINE,
    UI_MODE_INSUFFICIENT,
} ui_mode_t;

typedef enum {
    UI_LED_GREEN = 0,
    UI_LED_RED,
    UI_LED_YELLOW,
    UI_LED_BLUE,
    UI_LED_WHITE,
} ui_led_t;

typedef struct {
    bool have_summary; // at least one 5 s summary since boot
    bool warming_up;
    quality_state_t quality;
    uint32_t flags;
    double v_rms_v, i_rms_a, active_power_w, energy_wh;
    bool calibration_accepted;
    bool calibration_nominal; // "not validated" marker
    clock_source_t clock;
    bool link_up; // Wi-Fi and MQTT connected
    uint32_t queued;
    bool warning_active; // threshold firing or clearing, never pending (user story 3)
    double warning_value_w, warning_limit_w;
} ui_input_t;

typedef struct {
    ui_mode_t mode;
    ui_led_t led;
    bool buzzer;
    char lines[UI_LINES][UI_COLS + 1];
} ui_view_t;

void ui_render(const ui_input_t *in, ui_view_t *out);
