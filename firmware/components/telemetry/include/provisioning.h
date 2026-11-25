// Wired credential provisioning into encrypted NVS (research R-007, T030).
//
// scripts/provision-node.py reads an ignored per-device manifest and sends one
// command per line over the USB console of a trusted, wired PC:
//
//   set <key> <hex value>   stage a value in RAM (replaces an earlier one)
//   commit                  validate every key, write all to NVS, wipe RAM
//   abort                   wipe RAM
//   status                  "ok provisioned" or "ok empty"
//
// Replies are "ok", "ok <state>", or "err <code>[ <key>]"; values are never echoed
// or logged. Hex encoding keeps PEM newlines and Wi-Fi passwords line-safe.
#pragma once

#include <stdbool.h>
#include <stddef.h>

#include "nvs_port.h"

#define PROV_NODE_ID_MAX 32
#define PROV_SSID_MAX 32
#define PROV_PASS_MAX 63
#define PROV_HOST_MAX 253
#define PROV_PEM_MAX 4096
#define PROV_REPLY_MAX 64

typedef enum {
    PROV_KEY_NODE_ID = 0,
    PROV_KEY_WIFI_SSID,
    PROV_KEY_WIFI_PASS,
    PROV_KEY_MQTT_HOST,
    PROV_KEY_MQTT_PORT,
    PROV_KEY_CA_CERT,
    PROV_KEY_NODE_CERT,
    PROV_KEY_NODE_KEY,
    PROV_KEY_COUNT,
} prov_key_t;

typedef struct {
    char node_id[PROV_NODE_ID_MAX + 1];
    char wifi_ssid[PROV_SSID_MAX + 1];
    char wifi_pass[PROV_PASS_MAX + 1];
    char mqtt_host[PROV_HOST_MAX + 1];
    char mqtt_port[6];
    char ca_cert[PROV_PEM_MAX + 1];
    char node_cert[PROV_PEM_MAX + 1];
    char node_key[PROV_PEM_MAX + 1];
} prov_config_t;

typedef struct {
    prov_config_t staged;
    bool present[PROV_KEY_COUNT];
    const nvs_port_t *nvs;
} prov_session_t;

void prov_session_init(prov_session_t *s, const nvs_port_t *nvs);
// Handles one line (without the newline); writes a reply of at most PROV_REPLY_MAX.
void prov_handle_line(prov_session_t *s, const char *line, char *reply, size_t reply_len);
// Wipes staged secrets from RAM.
void prov_session_wipe(prov_session_t *s);

bool prov_is_provisioned(const nvs_port_t *nvs);
// Loads every key from NVS; returns false if any is missing or invalid.
bool prov_load(const nvs_port_t *nvs, prov_config_t *out);
const char *prov_key_name(prov_key_t key);
