// Target NVS port: encrypted NVS with the HMAC key-protection scheme (R-007).
#pragma once

#include "esp_err.h"
#include "nvs_port.h"

// Initializes encrypted NVS once (generating the XTS keys from the eFuse HMAC key
// on first boot) and opens `namespace_name` read-write behind `out`.
esp_err_t nvs_port_esp_open(const char *namespace_name, nvs_port_t *out);
