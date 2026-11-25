// In-memory NVS fake with fault injection for host tests.
#pragma once

#include <stdbool.h>

#include "nvs_port.h"

#define FAKE_NVS_SLOTS 16

typedef struct {
    char key[16];
    unsigned char *data;
    size_t len;
    bool used;
} fake_nvs_slot_t;

typedef struct {
    fake_nvs_slot_t slots[FAKE_NVS_SLOTS];
    int fail_set_after; // -1: never; n: the (n+1)-th set fails
    int sets;
    int commits;
} fake_nvs_t;

nvs_port_t fake_nvs_init(fake_nvs_t *f);
void fake_nvs_free(fake_nvs_t *f);
