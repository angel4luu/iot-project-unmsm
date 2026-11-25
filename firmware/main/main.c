// Node entry point. Measurement, telemetry, and UI tasks are added by the
// user-story phases (plan › Firmware); Phase 2 provides encrypted NVS and
// first-boot credential provisioning.
#include "esp_log.h"
#include "nvs_port_esp.h"
#include "provisioning.h"
#include "provisioning_console.h"

static const char *TAG = "main";

void app_main(void) {
    nvs_port_t nvs;
    ESP_ERROR_CHECK(nvs_port_esp_open("node", &nvs));
    if (!prov_is_provisioned(&nvs)) {
        provisioning_console_run(&nvs);
    }
    ESP_LOGI(TAG, "credentials present; measurement tasks start in later phases");
}
