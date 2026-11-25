// Build guide stage 1 (T027): board alone. Boots, joins Wi-Fi with the provisioned
// credentials (scripts/provision-node.py), and cycles the RGB LED red/green/blue.
#include <string.h>

#include "board.h"
#include "driver/gpio.h"
#include "esp_event.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "nvs_port_esp.h"
#include "provisioning.h"
#include "provisioning_console.h"

static const char *TAG = "stage1";
static EventGroupHandle_t s_events;
#define GOT_IP BIT0

static void on_event(void *arg, esp_event_base_t base, int32_t id, void *data) {
    (void)arg;
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        ESP_LOGW(TAG, "Wi-Fi disconnected; retrying");
        esp_wifi_connect();
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        const ip_event_got_ip_t *ev = data;
        ESP_LOGI(TAG, "PASS Wi-Fi joined, IP " IPSTR, IP2STR(&ev->ip_info.ip));
        xEventGroupSetBits(s_events, GOT_IP);
    }
}

static void wifi_join(const prov_config_t *cfg) {
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_sta();
    wifi_init_config_t init = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&init));
    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, on_event, NULL));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, on_event, NULL));
    wifi_config_t wc = {0};
    strncpy((char *)wc.sta.ssid, cfg->wifi_ssid, sizeof wc.sta.ssid);
    strncpy((char *)wc.sta.password, cfg->wifi_pass, sizeof wc.sta.password);
    wc.sta.threshold.authmode = WIFI_AUTH_WPA2_PSK;
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wc));
    ESP_ERROR_CHECK(esp_wifi_start());
    memset(&wc, 0, sizeof wc);
}

void app_main(void) {
    ESP_LOGI(TAG, "PASS boot (ESP32-S3, stage 1 bring-up)");
    s_events = xEventGroupCreate();
    const gpio_num_t leds[] = {BOARD_PIN_LED_RED, BOARD_PIN_LED_GREEN, BOARD_PIN_LED_BLUE};
    const char *names[] = {"red", "green", "blue"};
    for (int i = 0; i < 3; i++) {
        gpio_reset_pin(leds[i]);
        gpio_set_direction(leds[i], GPIO_MODE_OUTPUT);
        gpio_set_level(leds[i], 0);
    }

    nvs_port_t nvs;
    ESP_ERROR_CHECK(nvs_port_esp_open("node", &nvs));
    if (!prov_is_provisioned(&nvs)) {
        provisioning_console_run(&nvs);
    }
    static prov_config_t cfg;
    if (prov_load(&nvs, &cfg)) {
        wifi_join(&cfg);
        memset(&cfg, 0, sizeof cfg);
    } else {
        ESP_LOGE(TAG, "FAIL credentials unreadable");
    }

    for (int n = 0;; n = (n + 1) % 3) {
        for (int i = 0; i < 3; i++) {
            gpio_set_level(leds[i], i == n);
        }
        ESP_LOGI(TAG, "LED %s%s", names[n],
                 (xEventGroupGetBits(s_events) & GOT_IP) ? " (Wi-Fi up)" : "");
        vTaskDelay(pdMS_TO_TICKS(1000));
    }
}
