// MQTT port: publishing and subscribing without ESP-MQTT in host tests.
#pragma once

#include <stdbool.h>
#include <stddef.h>

typedef struct mqtt_port {
    // Returns a message id >= 0 when queued, or a negative value on error.
    int (*publish)(void *ctx, const char *topic, const char *payload, size_t len, int qos,
                   bool retain);
    int (*subscribe)(void *ctx, const char *topic, int qos);
    bool (*connected)(void *ctx);
    void *ctx;
} mqtt_port_t;
