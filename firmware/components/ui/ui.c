#include "ui.h"

#include <string.h>

#include "driver/gpio.h"
#include "driver/i2c_master.h"
#include "esp_log.h"
#include "font5x7.h"

#define OLED_PAGES 8

static const char *TAG = "ui";
static i2c_master_dev_handle_t s_oled;
static ui_pins_t s_pins;
static char s_shown[UI_LINES][UI_COLS + 1];

static esp_err_t oled_cmd(const uint8_t *cmds, size_t n) {
    uint8_t buf[32] = {0x00}; // control byte: command stream
    memcpy(buf + 1, cmds, n);
    return i2c_master_transmit(s_oled, buf, n + 1, 100);
}

static esp_err_t oled_page(uint8_t page, const uint8_t *data, size_t n) {
    const uint8_t at[] = {(uint8_t)(0xB0 | page), (uint8_t)(0x00 | (UI_OLED_COLUMN_OFFSET & 0x0F)),
                          (uint8_t)(0x10 | (UI_OLED_COLUMN_OFFSET >> 4))};
    esp_err_t err = oled_cmd(at, sizeof at);
    uint8_t buf[129] = {0x40}; // control byte: data stream
    memcpy(buf + 1, data, n);
    return err == ESP_OK ? i2c_master_transmit(s_oled, buf, n + 1, 100) : err;
}

static void oled_text(uint8_t page, const char *text) {
    uint8_t row[128] = {0};
    for (size_t i = 0; text[i] && i < UI_COLS; i++) {
        memcpy(row + i * 6, font5x7_glyph(text[i]), 5);
    }
    oled_page(page, row, sizeof row);
}

static void out_pin(int pin) {
    gpio_reset_pin((gpio_num_t)pin);
    gpio_set_direction((gpio_num_t)pin, GPIO_MODE_OUTPUT);
    gpio_set_level((gpio_num_t)pin, UI_LED_COMMON_ANODE && pin != s_pins.pin_buzzer ? 1 : 0);
}

bool ui_hw_init(const ui_pins_t *pins) {
    s_pins = *pins;
    out_pin(pins->pin_red);
    out_pin(pins->pin_green);
    out_pin(pins->pin_blue);
    out_pin(pins->pin_buzzer);
    memset(s_shown, 0, sizeof s_shown);

    i2c_master_bus_config_t bus_cfg = {
        .i2c_port = I2C_NUM_0,
        .sda_io_num = pins->pin_sda,
        .scl_io_num = pins->pin_scl,
        .clk_source = I2C_CLK_SRC_DEFAULT,
        .glitch_ignore_cnt = 7,
        .flags.enable_internal_pullup = true,
    };
    i2c_master_bus_handle_t bus;
    if (i2c_new_master_bus(&bus_cfg, &bus) != ESP_OK) {
        return false;
    }
    uint16_t addr = 0;
    for (uint16_t a = 0x3C; a <= 0x3D && addr == 0; a++) {
        if (i2c_master_probe(bus, a, 50) == ESP_OK) {
            addr = a;
        }
    }
    if (addr == 0) {
        ESP_LOGW(TAG, "no OLED at 0x3C/0x3D; LED and buzzer only");
        return false;
    }
    i2c_device_config_t dev = {
        .dev_addr_length = I2C_ADDR_BIT_LEN_7, .device_address = addr, .scl_speed_hz = 400000};
    if (i2c_master_bus_add_device(bus, &dev, &s_oled) != ESP_OK) {
        return false;
    }
    const uint8_t init[] = {0xAE, 0xD5, 0x80, 0xA8, 0x3F, 0xD3, 0x00, 0x40, 0x8D,
                            0x14, 0x20, 0x02, 0xA1, 0xC8, 0xDA, 0x12, 0x81, 0x7F,
                            0xD9, 0xF1, 0xDB, 0x40, 0xA4, 0xA6, 0xAF};
    if (oled_cmd(init, sizeof init) != ESP_OK) {
        s_oled = NULL;
        return false;
    }
    const uint8_t blank[128] = {0};
    for (uint8_t p = 0; p < OLED_PAGES; p++) {
        oled_page(p, blank, sizeof blank);
    }
    return true;
}

static void led(int pin, bool on) {
    gpio_set_level((gpio_num_t)pin, (on ^ (UI_LED_COMMON_ANODE != 0)) ? 1 : 0);
}

void ui_hw_show(const ui_view_t *v) {
    const bool r = v->led == UI_LED_RED || v->led == UI_LED_YELLOW || v->led == UI_LED_WHITE;
    const bool g = v->led == UI_LED_GREEN || v->led == UI_LED_YELLOW || v->led == UI_LED_WHITE;
    const bool b = v->led == UI_LED_BLUE || v->led == UI_LED_WHITE;
    led(s_pins.pin_red, r);
    led(s_pins.pin_green, g);
    led(s_pins.pin_blue, b);
    gpio_set_level((gpio_num_t)s_pins.pin_buzzer, v->buzzer ? 1 : 0);
    if (s_oled == NULL) {
        return;
    }
    for (uint8_t p = 0; p < UI_LINES && p < OLED_PAGES; p++) {
        if (strcmp(s_shown[p], v->lines[p]) != 0) { // redraw changed lines only
            oled_text(p, v->lines[p]);
            memcpy(s_shown[p], v->lines[p], sizeof s_shown[p]);
        }
    }
}
