// I2C port for the OLED. Target: ESP-IDF i2c_master; host: a recording fake.
#pragma once

#include <stddef.h>
#include <stdint.h>

typedef struct i2c_port {
    int (*write)(void *ctx, uint8_t address, const uint8_t *data, size_t len); // 0 = ok
    void *ctx;
} i2c_port_t;
