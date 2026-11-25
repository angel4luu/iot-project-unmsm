// NVS port: key/value storage for credentials and the last accepted config.
// The target implementation uses encrypted NVS (HMAC scheme, nvs_port_esp.c);
// host tests use an in-memory fake (firmware/test/host/fakes/fake_nvs.c).
#pragma once

#include <stddef.h>

typedef enum {
    NVS_PORT_OK = 0,
    NVS_PORT_NOT_FOUND,
    NVS_PORT_TOO_LARGE, // value does not fit the caller's buffer
    NVS_PORT_ERROR,
} nvs_port_err_t;

typedef struct nvs_port {
    nvs_port_err_t (*set_blob)(void *ctx, const char *key, const void *data, size_t len);
    // `*len` is the buffer capacity on input and the stored size on output.
    nvs_port_err_t (*get_blob)(void *ctx, const char *key, void *buf, size_t *len);
    nvs_port_err_t (*erase_key)(void *ctx, const char *key);
    nvs_port_err_t (*commit)(void *ctx);
    void *ctx;
} nvs_port_t;
