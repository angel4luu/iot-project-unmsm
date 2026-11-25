#include "provisioning.h"

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct {
    const char *name;
    size_t offset;
    size_t max;
} key_info_t;

#define FIELD(k, f, m) [k] = {#f, offsetof(prov_config_t, f), (m)}

static const key_info_t KEYS[PROV_KEY_COUNT] = {
    FIELD(PROV_KEY_NODE_ID, node_id, PROV_NODE_ID_MAX),
    FIELD(PROV_KEY_WIFI_SSID, wifi_ssid, PROV_SSID_MAX),
    FIELD(PROV_KEY_WIFI_PASS, wifi_pass, PROV_PASS_MAX),
    FIELD(PROV_KEY_MQTT_HOST, mqtt_host, PROV_HOST_MAX),
    FIELD(PROV_KEY_MQTT_PORT, mqtt_port, 5),
    FIELD(PROV_KEY_CA_CERT, ca_cert, PROV_PEM_MAX),
    FIELD(PROV_KEY_NODE_CERT, node_cert, PROV_PEM_MAX),
    FIELD(PROV_KEY_NODE_KEY, node_key, PROV_PEM_MAX),
};

const char *prov_key_name(prov_key_t key) {
    return key < PROV_KEY_COUNT ? KEYS[key].name : "?";
}

static char *field_of(prov_config_t *c, prov_key_t k) {
    return (char *)c + KEYS[k].offset;
}

static void secure_zero(void *p, size_t n) {
    volatile unsigned char *v = p;
    while (n--) {
        *v++ = 0;
    }
}

void prov_session_wipe(prov_session_t *s) {
    secure_zero(&s->staged, sizeof s->staged);
    memset(s->present, 0, sizeof s->present);
}

void prov_session_init(prov_session_t *s, const nvs_port_t *nvs) {
    prov_session_wipe(s);
    s->nvs = nvs;
}

// ---- validation ---------------------------------------------------------------------

static bool is_identifier(const char *v) {
    size_t n = strlen(v);
    if (n < 1 || n > PROV_NODE_ID_MAX) {
        return false;
    }
    for (size_t i = 0; i < n; i++) {
        char ch = v[i];
        bool ok = (ch >= 'a' && ch <= 'z') || (ch >= '0' && ch <= '9') || (ch == '-' && i > 0);
        if (!ok) {
            return false;
        }
    }
    return true;
}

static bool is_hostname(const char *v) {
    size_t n = strlen(v);
    if (n < 1 || n > PROV_HOST_MAX || v[0] == '-' || v[0] == '.') {
        return false;
    }
    for (size_t i = 0; i < n; i++) {
        char ch = v[i];
        bool ok = (ch >= 'a' && ch <= 'z') || (ch >= 'A' && ch <= 'Z') ||
                  (ch >= '0' && ch <= '9') || ch == '-' || ch == '.';
        if (!ok) {
            return false;
        }
    }
    return true;
}

static bool is_port(const char *v) {
    size_t n = strlen(v);
    if (n < 1 || n > 5) {
        return false;
    }
    unsigned long port = 0;
    for (size_t i = 0; i < n; i++) {
        if (v[i] < '0' || v[i] > '9') {
            return false;
        }
        port = port * 10 + (unsigned long)(v[i] - '0');
    }
    return port >= 1 && port <= 65535;
}

static bool has_pem(const char *v, const char *begin, const char *end) {
    const char *b = strstr(v, begin);
    return b == v && strstr(b, end) != NULL;
}

static bool valid_value(prov_key_t k, const char *v) {
    size_t n = strlen(v);
    switch (k) {
    case PROV_KEY_NODE_ID:
        return is_identifier(v);
    case PROV_KEY_WIFI_SSID:
        return n >= 1 && n <= PROV_SSID_MAX;
    case PROV_KEY_WIFI_PASS:
        return n >= 8 && n <= PROV_PASS_MAX; // WPA2-PSK passphrase
    case PROV_KEY_MQTT_HOST:
        return is_hostname(v);
    case PROV_KEY_MQTT_PORT:
        return is_port(v);
    case PROV_KEY_CA_CERT:
    case PROV_KEY_NODE_CERT:
        return has_pem(v, "-----BEGIN CERTIFICATE-----", "-----END CERTIFICATE-----");
    case PROV_KEY_NODE_KEY:
        return strncmp(v, "-----BEGIN ", 11) == 0 && strstr(v, "PRIVATE KEY-----") != NULL;
    default:
        return false;
    }
}

// ---- command handling ---------------------------------------------------------------

static int hex_nibble(char c) {
    if (c >= '0' && c <= '9') {
        return c - '0';
    }
    if (c >= 'a' && c <= 'f') {
        return c - 'a' + 10;
    }
    if (c >= 'A' && c <= 'F') {
        return c - 'A' + 10;
    }
    return -1;
}

// Decodes hex into `out` (NUL-terminated); returns false on bad hex, NUL bytes, or overflow.
static bool hex_decode(const char *hex, char *out, size_t max, bool *too_long) {
    size_t n = strlen(hex);
    *too_long = false;
    if (n == 0 || n % 2 != 0) {
        return false;
    }
    if (n / 2 > max) {
        *too_long = true;
        return false;
    }
    for (size_t i = 0; i < n / 2; i++) {
        int hi = hex_nibble(hex[2 * i]);
        int lo = hex_nibble(hex[2 * i + 1]);
        if (hi < 0 || lo < 0 || (hi == 0 && lo == 0)) {
            return false;
        }
        out[i] = (char)(hi << 4 | lo);
    }
    out[n / 2] = '\0';
    return true;
}

static int find_key(const char *name, size_t len) {
    for (int k = 0; k < PROV_KEY_COUNT; k++) {
        if (strlen(KEYS[k].name) == len && strncmp(KEYS[k].name, name, len) == 0) {
            return k;
        }
    }
    return -1;
}

static void reply_set(char *reply, size_t len, const char *code, const char *key) {
    if (key) {
        snprintf(reply, len, "err %s %s", code, key);
    } else {
        snprintf(reply, len, "%s", code);
    }
}

static void handle_set(prov_session_t *s, const char *args, char *reply, size_t len) {
    const char *sp = strchr(args, ' ');
    if (sp == NULL) {
        reply_set(reply, len, "err syntax", NULL);
        return;
    }
    int k = find_key(args, (size_t)(sp - args));
    if (k < 0) {
        reply_set(reply, len, "err unknown_key", NULL);
        return;
    }
    char *dst = field_of(&s->staged, (prov_key_t)k);
    bool too_long;
    if (!hex_decode(sp + 1, dst, KEYS[k].max, &too_long)) {
        secure_zero(dst, KEYS[k].max + 1);
        s->present[k] = false;
        reply_set(reply, len, too_long ? "too_long" : "bad_hex", KEYS[k].name);
        return;
    }
    s->present[k] = true;
    reply_set(reply, len, "ok", NULL);
}

static void handle_commit(prov_session_t *s, char *reply, size_t len) {
    for (int k = 0; k < PROV_KEY_COUNT; k++) {
        if (!s->present[k]) {
            reply_set(reply, len, "missing", KEYS[k].name);
            return;
        }
        if (!valid_value((prov_key_t)k, field_of(&s->staged, (prov_key_t)k))) {
            reply_set(reply, len, "invalid_value", KEYS[k].name);
            return;
        }
    }
    for (int k = 0; k < PROV_KEY_COUNT; k++) {
        const char *v = field_of(&s->staged, (prov_key_t)k);
        if (s->nvs->set_blob(s->nvs->ctx, KEYS[k].name, v, strlen(v)) != NVS_PORT_OK) {
            for (int j = 0; j < PROV_KEY_COUNT; j++) { // never leave partial credentials
                s->nvs->erase_key(s->nvs->ctx, KEYS[j].name);
            }
            s->nvs->commit(s->nvs->ctx);
            prov_session_wipe(s);
            reply_set(reply, len, "nvs_error", KEYS[k].name);
            return;
        }
    }
    nvs_port_err_t err = s->nvs->commit(s->nvs->ctx);
    prov_session_wipe(s);
    reply_set(reply, len, err == NVS_PORT_OK ? "ok" : "err nvs_error", NULL);
}

void prov_handle_line(prov_session_t *s, const char *line, char *reply, size_t reply_len) {
    if (strncmp(line, "set ", 4) == 0) {
        handle_set(s, line + 4, reply, reply_len);
    } else if (strcmp(line, "commit") == 0) {
        handle_commit(s, reply, reply_len);
    } else if (strcmp(line, "abort") == 0) {
        prov_session_wipe(s);
        reply_set(reply, reply_len, "ok", NULL);
    } else if (strcmp(line, "status") == 0) {
        reply_set(reply, reply_len, prov_is_provisioned(s->nvs) ? "ok provisioned" : "ok empty",
                  NULL);
    } else {
        reply_set(reply, reply_len, "err unknown_command", NULL);
    }
}

// ---- loading ------------------------------------------------------------------------

bool prov_load(const nvs_port_t *nvs, prov_config_t *out) {
    secure_zero(out, sizeof *out);
    for (int k = 0; k < PROV_KEY_COUNT; k++) {
        char *dst = field_of(out, (prov_key_t)k);
        size_t n = KEYS[k].max;
        if (nvs->get_blob(nvs->ctx, KEYS[k].name, dst, &n) != NVS_PORT_OK || n > KEYS[k].max) {
            secure_zero(out, sizeof *out);
            return false;
        }
        dst[n] = '\0';
        if (!valid_value((prov_key_t)k, dst)) {
            secure_zero(out, sizeof *out);
            return false;
        }
    }
    return true;
}

bool prov_is_provisioned(const nvs_port_t *nvs) {
    prov_config_t *tmp = malloc(sizeof *tmp);
    if (tmp == NULL) {
        return false;
    }
    bool ok = prov_load(nvs, tmp);
    secure_zero(tmp, sizeof *tmp);
    free(tmp);
    return ok;
}
