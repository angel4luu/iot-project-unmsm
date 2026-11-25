// Build guide stage 2 (T028): peripherals without any analog front end.
// 1. Scans the I2C bus (OLED expected at 0x3C or 0x3D) and writes test text.
// 2. Beeps the buzzer for 200 ms through the 2N2222 on GPIO16.
// 3. Lights the RGB LED red, green, blue, one second each.
//
// The OLED controller is still an open decision: SSD1306 by default; set
// OLED_COLUMN_OFFSET to 2 for an SH1106 module (128x64, page addressing).
#include <string.h>

#include "board.h"
#include "driver/gpio.h"
#include "driver/i2c_master.h"
#include "esp_log.h"
#include "font5x7.h"
#include "freertos/FreeRTOS.h"

#define OLED_COLUMN_OFFSET 0
#define OLED_PAGES 8

static const char *TAG = "stage2";
static i2c_master_dev_handle_t s_oled;

static esp_err_t oled_cmd(const uint8_t *cmds, size_t n) {
    uint8_t buf[32] = {0x00}; // control byte: command stream
    memcpy(buf + 1, cmds, n);
    return i2c_master_transmit(s_oled, buf, n + 1, 100);
}

static esp_err_t oled_page(uint8_t page, const uint8_t *data, size_t n) {
    const uint8_t at[] = {(uint8_t)(0xB0 | page), (uint8_t)(0x00 | (OLED_COLUMN_OFFSET & 0x0F)),
                          (uint8_t)(0x10 | (OLED_COLUMN_OFFSET >> 4))};
    esp_err_t err = oled_cmd(at, sizeof at);
    uint8_t buf[129] = {0x40}; // control byte: data stream
    memcpy(buf + 1, data, n);
    return err == ESP_OK ? i2c_master_transmit(s_oled, buf, n + 1, 100) : err;
}

static void oled_text(uint8_t page, const char *text) {
    uint8_t row[128] = {0};
    for (size_t i = 0; text[i] && i < 21; i++) {
        memcpy(row + i * 6, font5x7_glyph(text[i]), 5);
    }
    oled_page(page, row, sizeof row);
}

static bool oled_init(i2c_master_bus_handle_t bus) {
    uint16_t addr = 0;
    for (uint16_t a = 0x08; a < 0x78; a++) {
        if (i2c_master_probe(bus, a, 50) == ESP_OK) {
            ESP_LOGI(TAG, "I2C device at 0x%02X", a);
            if (a == 0x3C || a == 0x3D) {
                addr = a;
            }
        }
    }
    if (addr == 0) {
        ESP_LOGE(TAG, "FAIL no OLED at 0x3C/0x3D: check SDA=GPIO%d, SCL=GPIO%d, VCC, GND",
                 BOARD_PIN_I2C_SDA, BOARD_PIN_I2C_SCL);
        return false;
    }
    i2c_device_config_t dev = {
        .dev_addr_length = I2C_ADDR_BIT_LEN_7, .device_address = addr, .scl_speed_hz = 400000};
    ESP_ERROR_CHECK(i2c_master_bus_add_device(bus, &dev, &s_oled));
    const uint8_t init[] = {0xAE, 0xD5, 0x80, 0xA8, 0x3F, 0xD3, 0x00, 0x40, 0x8D,
                            0x14, 0x20, 0x02, 0xA1, 0xC8, 0xDA, 0x12, 0x81, 0x7F,
                            0xD9, 0xF1, 0xDB, 0x40, 0xA4, 0xA6, 0xAF};
    if (oled_cmd(init, sizeof init) != ESP_OK) {
        ESP_LOGE(TAG, "FAIL OLED did not acknowledge init");
        return false;
    }
    const uint8_t blank[128] = {0};
    for (uint8_t p = 0; p < OLED_PAGES; p++) {
        oled_page(p, blank, sizeof blank);
    }
    return true;
}

static void out_pin(gpio_num_t pin) {
    gpio_reset_pin(pin);
    gpio_set_direction(pin, GPIO_MODE_OUTPUT);
    gpio_set_level(pin, 0);
}

void app_main(void) {
    i2c_master_bus_config_t bus_cfg = {
        .i2c_port = I2C_NUM_0,
        .sda_io_num = BOARD_PIN_I2C_SDA,
        .scl_io_num = BOARD_PIN_I2C_SCL,
        .clk_source = I2C_CLK_SRC_DEFAULT,
        .glitch_ignore_cnt = 7,
        .flags.enable_internal_pullup = false, // the module has its own pull-ups
    };
    i2c_master_bus_handle_t bus;
    ESP_ERROR_CHECK(i2c_new_master_bus(&bus_cfg, &bus));
    if (oled_init(bus)) {
        oled_text(0, "UNMSM GRUPO 5");
        oled_text(2, "STAGE 2 OLED OK");
        oled_text(4, "0123456789 V A W WH");
        ESP_LOGI(TAG, "PASS OLED text written; confirm it is readable");
    }

    out_pin(BOARD_PIN_BUZZER);
    gpio_set_level(BOARD_PIN_BUZZER, 1);
    vTaskDelay(pdMS_TO_TICKS(200));
    gpio_set_level(BOARD_PIN_BUZZER, 0);
    ESP_LOGI(TAG, "buzzer beeped 200 ms; confirm it was heard");

    const gpio_num_t leds[] = {BOARD_PIN_LED_RED, BOARD_PIN_LED_GREEN, BOARD_PIN_LED_BLUE};
    const char *names[] = {"red", "green", "blue"};
    for (int i = 0; i < 3; i++) {
        out_pin(leds[i]);
    }
    for (;;) {
        for (int i = 0; i < 3; i++) {
            gpio_set_level(leds[i], 1);
            ESP_LOGI(TAG, "LED %s on; confirm the colour", names[i]);
            vTaskDelay(pdMS_TO_TICKS(1000));
            gpio_set_level(leds[i], 0);
        }
    }
}
