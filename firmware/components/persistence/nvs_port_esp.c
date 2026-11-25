#include "nvs_port_esp.h"

#include "esp_log.h"
#include "nvs.h"
#include "nvs_flash.h"
#include "nvs_sec_provider.h"

static const char *TAG = "nvs_port";
static nvs_handle_t s_handle;

static nvs_port_err_t map(esp_err_t err) {
    switch (err) {
    case ESP_OK:
        return NVS_PORT_OK;
    case ESP_ERR_NVS_NOT_FOUND:
        return NVS_PORT_NOT_FOUND;
    case ESP_ERR_NVS_INVALID_LENGTH:
        return NVS_PORT_TOO_LARGE;
    default:
        return NVS_PORT_ERROR;
    }
}

static nvs_port_err_t set_blob(void *ctx, const char *key, const void *data, size_t len) {
    return map(nvs_set_blob(*(nvs_handle_t *)ctx, key, data, len));
}

static nvs_port_err_t get_blob(void *ctx, const char *key, void *buf, size_t *len) {
    return map(nvs_get_blob(*(nvs_handle_t *)ctx, key, buf, len));
}

static nvs_port_err_t erase_key(void *ctx, const char *key) {
    return map(nvs_erase_key(*(nvs_handle_t *)ctx, key));
}

static nvs_port_err_t commit(void *ctx) {
    return map(nvs_commit(*(nvs_handle_t *)ctx));
}

static esp_err_t secure_init(void) {
    nvs_sec_scheme_t *scheme = NULL;
    nvs_sec_config_hmac_t hmac_cfg = NVS_SEC_PROVIDER_CFG_HMAC_DEFAULT();
    esp_err_t err = nvs_sec_provider_register_hmac(&hmac_cfg, &scheme);
    if (err != ESP_OK) {
        return err;
    }
    nvs_sec_cfg_t cfg = {0};
    err = nvs_flash_read_security_cfg_v2(scheme, &cfg);
    if (err == ESP_ERR_NVS_SEC_HMAC_KEY_NOT_FOUND) {
        // First boot: derives XTS keys from a freshly burned eFuse HMAC key (irreversible).
        ESP_LOGW(TAG, "no NVS HMAC key in eFuse; generating one");
        err = nvs_flash_generate_keys_v2(scheme, &cfg);
    }
    if (err != ESP_OK) {
        return err;
    }
    err = nvs_flash_secure_init(&cfg);
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_LOGW(TAG, "NVS partition unusable; erasing (credentials must be provisioned again)");
        ESP_ERROR_CHECK(nvs_flash_erase());
        err = nvs_flash_secure_init(&cfg);
    }
    return err;
}

esp_err_t nvs_port_esp_open(const char *namespace_name, nvs_port_t *out) {
    static bool s_ready;
    if (!s_ready) {
        esp_err_t err = secure_init();
        if (err != ESP_OK) {
            ESP_LOGE(TAG, "encrypted NVS init failed: %s", esp_err_to_name(err));
            return err;
        }
        s_ready = true;
    }
    esp_err_t err = nvs_open(namespace_name, NVS_READWRITE, &s_handle);
    if (err != ESP_OK) {
        return err;
    }
    *out = (nvs_port_t){set_blob, get_blob, erase_key, commit, &s_handle};
    return ESP_OK;
}
