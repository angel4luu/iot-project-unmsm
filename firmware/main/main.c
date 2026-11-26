// Node entry point (T051): acquisition -> metering -> quality -> queue -> telemetry,
// plus the local UI and the bench calibration console.
//
// Tasks:
// - measure (core 1, highest): ADC pairs into 1 s blocks, the local threshold on
//   each block (T082), 5 s summaries, energy, quality, the RAM queues, and the 60 s
//   energy checkpoint;
// - telemetry: Wi-Fi/MQTT pump, retained status on connect and every 30 s, node
//   events, and the retained threshold config (T081, MQTT task);
// - ui: LED, buzzer, and OLED from the latest summary every 500 ms;
// - console: `cal ...` commands for the bench calibration procedure (T064).
#include <math.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
#include <sys/time.h>

#include "acquisition.h"
#include "board.h"
#include "calibration.h"
#include "checkpoint.h"
#include "clock.h"
#include "driver/uart.h"
#include "driver/uart_vfs.h"
#include "esp_event.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_netif_sntp.h"
#include "esp_random.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "event_queue.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "metering.h"
#include "nvs_port_esp.h"
#include "provisioning.h"
#include "provisioning_console.h"
#include "quality.h"
#include "queue.h"
#include "serialize.h"
#include "telemetry_mqtt.h"
#include "threshold.h"
#include "threshold_config.h"
#include "ui.h"
#include "ui_state.h"

// Identity not carried by provisioning (open item: add `circuit_id` to the manifest
// if the lab ever has more than one circuit per node).
#define NODE_CIRCUIT_ID "lab-load-001"
#define FIRMWARE_VERSION "0.1.0"
#define HARDWARE_REVISION "proto-a"
#define SNTP_SERVER "pool.ntp.org" // the DHCP-provided server is tried first
#define SNTP_INTERVAL_S 3600

static const char *TAG = "main";
static const int64_t SECOND_US = 1000000;

// ---- shared state (guarded by s_lock unless noted) -----------------------------------

static SemaphoreHandle_t s_lock;       // calibration, clock, UI snapshot, last summary
static SemaphoreHandle_t s_queue_lock; // the RAM queue
static nvs_port_t s_nvs;
static prov_config_t s_prov; // large PEM buffers: static
static char s_boot_id[REC_UUID_LEN + 1];
static node_identity_t s_id;
static calibration_t s_cal;
static clock_state_t s_clock;
static energy_counter_t s_energy; // measure task only
static checkpoint_state_t s_ckpt; // measure task only
static bool s_energy_uncertain;   // first summary after an unclean restart
static telemetry_queue_t s_queue;
static event_queue_t s_events; // guarded by s_queue_lock
static threshold_t s_thr;      // local threshold state machine
static ui_input_t s_ui;
static measurement_record_t s_last; // latest summary (for status and console)
static bool s_have_last;
static int64_t s_last_valid_end_ms = -1;
static volatile bool s_link_up; // Wi-Fi has an IP address
static char s_last_will[SERIALIZE_STATUS_MAX];

// Offset capture (console -> measure task)
static cal_offset_capture_t s_offset;
static volatile bool s_offset_active;
static int64_t s_offset_until_us;

static void lock(void) {
    xSemaphoreTake(s_lock, portMAX_DELAY);
}

static void unlock(void) {
    xSemaphoreGive(s_lock);
}

static void uuid4(char out[REC_UUID_LEN + 1], void *ctx) {
    (void)ctx;
    uint8_t b[16];
    esp_fill_random(b, sizeof b);
    b[6] = (uint8_t)((b[6] & 0x0F) | 0x40);
    b[8] = (uint8_t)((b[8] & 0x3F) | 0x80);
    snprintf(out, REC_UUID_LEN + 1,
             "%02x%02x%02x%02x-%02x%02x-%02x%02x-%02x%02x-%02x%02x%02x%02x%02x%02x", b[0], b[1],
             b[2], b[3], b[4], b[5], b[6], b[7], b[8], b[9], b[10], b[11], b[12], b[13], b[14],
             b[15]);
}

// ---- network and time ----------------------------------------------------------------

static void on_net_event(void *arg, esp_event_base_t base, int32_t id, void *data) {
    (void)arg;
    (void)data;
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        s_link_up = false;
        lock();
        clock_on_link(&s_clock, false);
        unlock();
        esp_wifi_connect();
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        s_link_up = true;
        lock();
        clock_on_link(&s_clock, true);
        unlock();
    }
}

static void on_sntp_sync(struct timeval *tv) {
    const int64_t utc_ms = (int64_t)tv->tv_sec * 1000 + tv->tv_usec / 1000;
    lock();
    clock_on_sntp_sync(&s_clock, utc_ms, esp_timer_get_time());
    unlock();
    ESP_LOGI(TAG, "SNTP sync");
}

static void network_start(void) {
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_sta();
    wifi_init_config_t init = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&init));
    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, on_net_event, NULL));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, on_net_event, NULL));
    wifi_config_t wc = {0};
    strlcpy((char *)wc.sta.ssid, s_prov.wifi_ssid, sizeof wc.sta.ssid);
    strlcpy((char *)wc.sta.password, s_prov.wifi_pass, sizeof wc.sta.password);
    wc.sta.threshold.authmode = WIFI_AUTH_WPA2_PSK;
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wc));
    ESP_ERROR_CHECK(esp_wifi_start());

    esp_sntp_config_t sc = ESP_NETIF_SNTP_DEFAULT_CONFIG(SNTP_SERVER);
    sc.server_from_dhcp = true;
    sc.renew_servers_after_new_IP = true;
    sc.index_of_first_server = 1;
    sc.sync_cb = on_sntp_sync;
    ESP_ERROR_CHECK(esp_netif_sntp_init(&sc));
}

// ---- measurement -------------------------------------------------------------------------

static metering_block_t s_block; // measure task only

static void on_pair(void *ctx, uint16_t v_mv, uint16_t i_mv) {
    (void)ctx;
    metering_block_add(&s_block, v_mv, i_mv);
    if (s_offset_active) {
        cal_offset_add(&s_offset, i_mv);
    }
}

static void on_gap(void *ctx) {
    (void)ctx;
    metering_block_gap(&s_block);
}

static void finish_summary(const metering_summary_t *sum, int64_t start_us, int64_t now_us,
                           const calibration_t *cal) {
    metering_values_t mv;
    const bool any = metering_summary_finish(sum, &mv);
    lock();
    const clock_reading_t cr = clock_read(&s_clock, now_us);
    unlock();

    const quality_input_t qi = {
        .sample_gap = mv.sample_gap || !any,
        .adc_clipped = mv.adc_clipped,
        .valid_sample_ratio = mv.valid_sample_ratio,
        .v_rms_v = mv.v_rms_v,
        .i_rms_a = mv.i_rms_a,
        .active_power_w = mv.active_power_w,
        .i_offset_dev_mv = mv.i_offset_dev_mv,
        .v_offset_dev_mv = mv.v_offset_dev_mv,
        .calibration_accepted = calibration_accepted(cal),
        .zero_noise_current_a = cal->zero_noise_current_a,
        .clock_unsynchronized = cr.source == CLOCK_SOURCE_UNSYNCHRONIZED,
        .energy_continuity_uncertain = s_energy_uncertain,
    };
    s_energy_uncertain = false;
    const quality_result_t q = quality_classify(&qi, &QUALITY_LIMITS_PLAN_B);

    static uint64_t sequence;
    measurement_record_t r;
    memset(&r, 0, sizeof r);
    uuid4(r.message_id, NULL);
    memcpy(r.boot_id, s_boot_id, sizeof r.boot_id);
    r.sequence = sequence++;
    r.duration_ms = (uint32_t)((now_us - start_us) / 1000);
    r.window_end_ms = cr.utc_ms;
    r.window_start_ms = cr.utc_ms - r.duration_ms;
    r.sample_count = mv.sample_count;
    r.clock_source = cr.source;
    r.last_sync_age_s = cr.last_sync_age_s;
    r.uptime_ms = (uint64_t)cr.uptime_ms;
    r.quality = q.state;
    r.flags = q.flags;
    r.valid_sample_ratio = mv.valid_sample_ratio;
    r.v_rms_v = mv.v_rms_v;
    r.i_rms_a = mv.i_rms_a;
    r.active_power_w = mv.active_power_w;
    r.energy_wh = s_energy.total_wh;
    memcpy(r.counter_id, s_energy.counter_id, sizeof r.counter_id);
    if (calibration_accepted(cal)) {
        strlcpy(r.calibration_revision, cal->revision, sizeof r.calibration_revision);
    }

    xSemaphoreTake(s_queue_lock, portMAX_DELAY);
    if (!queue_push(&s_queue, &r)) {
        ESP_LOGW(TAG, "queue full: oldest summary dropped");
    }
    const uint32_t queued = queue_pending(&s_queue);
    xSemaphoreGive(s_queue_lock);

    lock();
    s_last = r;
    s_have_last = true;
    if (q.state == QUALITY_VALID) {
        s_last_valid_end_ms = r.window_end_ms;
    }
    s_ui.have_summary = true;
    s_ui.quality = q.state;
    s_ui.flags = q.flags;
    s_ui.v_rms_v = r.v_rms_v;
    s_ui.i_rms_a = r.i_rms_a;
    s_ui.active_power_w = r.active_power_w;
    s_ui.energy_wh = r.energy_wh;
    s_ui.calibration_accepted = calibration_accepted(cal);
    s_ui.calibration_nominal = cal->kind == CAL_KIND_NOMINAL;
    s_ui.clock = cr.source;
    s_ui.queued = queued;
    unlock();
}

// Local threshold on one 1 s block (T082): drives the red LED and buzzer through the
// UI snapshot and queues the node events. Needs neither the network nor the clock.
static void evaluate_threshold(bool finished, const metering_block_result_t *br,
                               const calibration_t *cal, int64_t now_us, int64_t block_us) {
    static uint64_t event_sequence;
    const thr_block_t b = threshold_block_from(finished, br, cal, (uint32_t)(block_us / 1000));
    thr_events_t ev;
    lock();
    threshold_step(&s_thr, &b, &ev);
    s_ui.warning_active = threshold_warning_active(&s_thr);
    s_ui.warning_value_w = s_thr.last_valid_w;
    s_ui.warning_limit_w = s_thr.cfg.limit_w;
    const clock_reading_t cr = clock_read(&s_clock, now_us);
    const thr_state_t state = s_thr.state;
    unlock();
    for (uint32_t k = 0; k < ev.count; k++) {
        event_record_t *e = &ev.ev[k];
        uuid4(e->event_id, NULL);
        e->sequence = event_sequence++;
        e->observed_at_ms = cr.utc_ms;
        xSemaphoreTake(s_queue_lock, portMAX_DELAY);
        const bool kept = evq_push(&s_events, e);
        xSemaphoreGive(s_queue_lock);
        if (!kept) {
            ESP_LOGW(TAG, "event queue full: oldest event dropped");
        }
        ESP_LOGI(TAG, "threshold event %d (%s), config v%u", (int)e->type,
                 threshold_state_name(state), (unsigned)e->config_version);
    }
}

static void measure_task(void *arg) {
    (void)arg;
    adc_port_t port;
    if (!acquisition_esp_start(&port, BOARD_ADC_CH_VOLTAGE, BOARD_ADC_CH_CURRENT,
                               BOARD_ADC_CONVERSIONS_PER_S)) {
        ESP_LOGE(TAG, "ADC failed to start; no measurements");
        vTaskDelete(NULL);
        return;
    }
    acq_t acq;
    acq_init(&acq, BOARD_ADC_CH_VOLTAGE, BOARD_ADC_CH_CURRENT, on_pair, on_gap, NULL);
    metering_summary_t sum;
    metering_summary_reset(&sum);
    metering_block_reset(&s_block);
    int64_t block_start = esp_timer_get_time(), summary_start = block_start;
    uint32_t blocks = 0;
    calibration_t cal;
    lock();
    cal = s_cal;
    unlock();

    for (;;) {
        acq_poll(&acq, &port, 20);
        const int64_t now = esp_timer_get_time();
        if (s_offset_active && now >= s_offset_until_us) {
            s_offset_active = false; // the console task finishes the capture
        }
        if (now - block_start < SECOND_US) {
            continue;
        }
        metering_block_result_t br;
        const bool finished = metering_block_finish(&s_block, &cal, &br);
        if (finished) {
            metering_summary_add(&sum, &br, &cal);
            if (br.power_valid && !br.adc_clipped) {
                energy_add(&s_energy, br.active_power_w, now - block_start);
            }
        }
        evaluate_threshold(finished, &br, &cal, now, now - block_start);
        metering_block_reset(&s_block);
        block_start = now;
        if (++blocks < METERING_BLOCKS_PER_SUMMARY) {
            continue;
        }
        finish_summary(&sum, summary_start, now, &cal);
        if (!checkpoint_save(&s_nvs, &s_ckpt, &s_energy, false, false, now)) {
            ESP_LOGW(TAG, "energy checkpoint failed");
        }
        metering_summary_reset(&sum);
        summary_start = now;
        blocks = 0;
        lock();
        cal = s_cal; // pick up console changes at a summary boundary
        unlock();
    }
}

// ---- threshold configuration (T081) ------------------------------------------------------

// Retained config from the server (MQTT task). Applied only once stored in NVS.
static void on_threshold_config(const char *json, size_t len) {
    thr_config_t c;
    const thr_cfg_parse_t p =
        threshold_config_parse(json, len, s_prov.node_id, NODE_CIRCUIT_ID, &c);
    if (p != THR_CFG_OK) {
        ESP_LOGW(TAG, "threshold config refused (parse %d)", (int)p);
        return;
    }
    const thr_cfg_accept_t r = threshold_config_accept(&s_nvs, &c);
    if (r == THR_CFG_ACCEPTED) {
        lock();
        threshold_set_config(&s_thr, &c);
        unlock();
    }
    ESP_LOGI(TAG, "threshold config v%u: %s", (unsigned)c.config_version,
             threshold_config_result_name(r));
}

// ---- telemetry ---------------------------------------------------------------------------

static size_t build_status(char *buf, size_t len, node_state_t state) {
    const int64_t now = esp_timer_get_time();
    lock();
    const clock_reading_t cr = clock_read(&s_clock, now);
    const bool degraded = s_have_last && s_last.quality != QUALITY_VALID;
    status_record_t st = {
        .observed_at_ms = cr.utc_ms,
        .state = state == NODE_OFFLINE ? NODE_OFFLINE : (degraded ? NODE_DEGRADED : NODE_ONLINE),
        .calibration_revision = calibration_accepted(&s_cal) ? s_cal.revision : NULL,
        .clock_source = cr.source,
        .acquisition_state = state == NODE_OFFLINE ? ACQ_STOPPED
                             : degraded            ? ACQ_DEGRADED
                                                   : ACQ_SAMPLING,
        .last_valid_window_end_ms = s_last_valid_end_ms,
        .last_error_code = state == NODE_OFFLINE ? "connection_lost" : NULL,
    };
    unlock();
    xSemaphoreTake(s_queue_lock, portMAX_DELAY);
    st.pending_records = queue_pending(&s_queue);
    st.oldest_pending_age_s = queue_oldest_age_s(&s_queue, (uint64_t)cr.uptime_ms);
    xSemaphoreGive(s_queue_lock);
    return serialize_status(&s_id, &st, buf, len);
}

static void telemetry_task(void *arg) {
    (void)arg;
    static char status[SERIALIZE_STATUS_MAX];
    int64_t last_status = 0;
    for (;;) {
        const int64_t now = esp_timer_get_time();
        telemetry_mqtt_pump(now);
        const bool edge = telemetry_mqtt_take_connected_edge();
        if (telemetry_mqtt_connected() &&
            (edge || now - last_status >= TELEMETRY_STATUS_EVERY_US)) {
            const size_t n = build_status(status, sizeof status, NODE_ONLINE);
            if (n > 0 && telemetry_mqtt_publish_status(status, n)) {
                last_status = now;
            }
        }
        lock();
        s_ui.link_up = s_link_up && telemetry_mqtt_connected();
        unlock();
        vTaskDelay(pdMS_TO_TICKS(100));
    }
}

// ---- UI ----------------------------------------------------------------------------------

static void ui_task(void *arg) {
    (void)arg;
    static ui_view_t view;
    for (;;) {
        lock();
        const ui_input_t in = s_ui;
        unlock();
        ui_render(&in, &view);
        ui_hw_show(&view);
        vTaskDelay(pdMS_TO_TICKS(500));
    }
}

// ---- bench calibration console (plan › Calibration and plausibility procedure) -----------

static void console_reply(const char *fmt, ...) __attribute__((format(printf, 1, 2)));
static void console_reply(const char *fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    printf("CAL ");
    vprintf(fmt, ap);
    printf("\n");
    va_end(ap);
    fflush(stdout);
}

static void cal_command(const char *line) {
    if (strcmp(line, "cal status") == 0) {
        lock();
        console_reply("revision=%s kind=%s sign=%d zero_mv=%.2f noise_a=%.4f last_p_w=%.3f "
                      "last_i_a=%.4f quality=%s",
                      calibration_accepted(&s_cal) ? s_cal.revision : "none",
                      s_cal.kind == CAL_KIND_NOMINAL ? "nominal" : "reference",
                      (int)s_cal.current_sign, s_cal.current_zero_mv, s_cal.zero_noise_current_a,
                      s_have_last ? s_last.active_power_w : NAN, s_have_last ? s_last.i_rms_a : NAN,
                      s_have_last ? quality_state_name(s_last.quality) : "none");
        unlock();
    } else if (strcmp(line, "cal offset") == 0) {
        if (s_cal.frozen) {
            console_reply("err frozen (start a new revision with `cal new`)");
            return;
        }
        cal_offset_begin(&s_offset);
        s_offset_until_us = esp_timer_get_time() + (int64_t)CAL_OFFSET_CAPTURE_S * SECOND_US;
        s_offset_active = true;
        console_reply("capturing %u s with the bulb OFF", (unsigned)CAL_OFFSET_CAPTURE_S);
        while (s_offset_active) {
            vTaskDelay(pdMS_TO_TICKS(200));
        }
        lock();
        const cal_offset_result_t r =
            cal_offset_finish(&s_offset, BOARD_ADC_CONVERSIONS_PER_S / 2, &s_cal);
        unlock();
        console_reply("%s zero_mv=%.2f noise_a=%.4f",
                      r == CAL_OFFSET_OK          ? "ok"
                      : r == CAL_OFFSET_TOO_SHORT ? "err too_short"
                                                  : "err disconnected",
                      s_cal.current_zero_mv, s_cal.zero_noise_current_a);
    } else if (strcmp(line, "cal sign") == 0) {
        lock();
        const bool flipped = s_have_last && s_last.i_rms_a >= s_cal.zero_noise_current_a &&
                             cal_correct_sign(&s_cal, s_last.active_power_w, 1.0);
        unlock();
        console_reply("%s (bulb ON; checks the latest 5 s summary)",
                      flipped ? "ok sign flipped" : "ok no change");
    } else if (strcmp(line, "cal freeze") == 0) {
        lock();
        const cal_store_result_t r = calibration_freeze(&s_nvs, s_prov.node_id, &s_cal);
        unlock();
        console_reply(r == CAL_STORE_OK ? "ok %s" : "err %s",
                      r == CAL_STORE_OK ? s_cal.revision : "store_failed");
    } else if (strcmp(line, "cal new") == 0) {
        lock();
        const calibration_t prev = s_cal;
        calibration_nominal(&s_cal, &CAL_FRONTEND_NOMINAL);
        s_cal.current_sign = prev.current_sign;
        unlock();
        console_reply("ok new unfrozen nominal revision (windows flagged calibration_missing)");
    } else {
        console_reply("err commands: cal status | cal offset | cal sign | cal freeze | cal new");
    }
}

static void console_task(void *arg) {
    (void)arg;
    if (uart_driver_install(CONFIG_ESP_CONSOLE_UART_NUM, 512, 0, 0, NULL, 0) == ESP_OK) {
        uart_vfs_dev_use_driver(CONFIG_ESP_CONSOLE_UART_NUM);
    }
    setvbuf(stdin, NULL, _IONBF, 0);
    char line[64];
    for (;;) {
        if (fgets(line, sizeof line, stdin) == NULL) {
            vTaskDelay(pdMS_TO_TICKS(200));
            continue;
        }
        line[strcspn(line, "\r\n")] = '\0';
        if (strncmp(line, "cal", 3) == 0) {
            cal_command(line);
        }
    }
}

// ---- boot --------------------------------------------------------------------------------

void app_main(void) {
    ESP_ERROR_CHECK(nvs_port_esp_open("node", &s_nvs));
    if (!prov_is_provisioned(&s_nvs)) {
        provisioning_console_run(&s_nvs);
    }
    if (!prov_load(&s_nvs, &s_prov)) {
        ESP_LOGE(TAG, "credentials unreadable; reprovision the node");
        return;
    }
    s_lock = xSemaphoreCreateMutex();
    s_queue_lock = xSemaphoreCreateMutex();
    uuid4(s_boot_id, NULL);
    s_id = (node_identity_t){
        .node_id = s_prov.node_id,
        .circuit_id = NODE_CIRCUIT_ID,
        .boot_id = s_boot_id,
        .firmware_version = FIRMWARE_VERSION,
        .hardware_revision = HARDWARE_REVISION,
    };
    clock_init(&s_clock, SNTP_INTERVAL_S);
    if (!calibration_load_latest(&s_nvs, &s_cal)) {
        calibration_nominal(&s_cal, &CAL_FRONTEND_NOMINAL);
        ESP_LOGW(TAG, "no accepted calibration: windows flagged calibration_missing");
    }
    const checkpoint_restore_t ck =
        checkpoint_restore(&s_nvs, &s_ckpt, &s_energy, uuid4, NULL, esp_timer_get_time());
    s_energy_uncertain = ck == CHECKPOINT_RESUMED_UNCLEAN;
    ESP_LOGI(TAG, "boot %s, energy %s %.6f Wh (%s)", s_boot_id, s_energy.counter_id,
             s_energy.total_wh,
             ck == CHECKPOINT_NEW_COUNTER       ? "new counter"
             : ck == CHECKPOINT_RESUMED_UNCLEAN ? "resumed after unclean restart"
                                                : "resumed");
    queue_init(&s_queue);
    evq_init(&s_events);
    threshold_init(&s_thr);
    thr_config_t thr_cfg;
    if (threshold_config_load(&s_nvs, &thr_cfg)) {
        threshold_set_config(&s_thr, &thr_cfg);
        ESP_LOGI(TAG, "threshold config v%u: limit %.3f W", (unsigned)thr_cfg.config_version,
                 thr_cfg.limit_w);
    } else {
        ESP_LOGW(TAG, "no threshold config yet: no local threshold until the server sends one");
    }
    s_ui.calibration_nominal = s_cal.kind == CAL_KIND_NOMINAL;
    s_ui.calibration_accepted = calibration_accepted(&s_cal);

    const ui_pins_t pins = {
        .pin_sda = BOARD_PIN_I2C_SDA,
        .pin_scl = BOARD_PIN_I2C_SCL,
        .pin_red = BOARD_PIN_LED_RED,
        .pin_green = BOARD_PIN_LED_GREEN,
        .pin_blue = BOARD_PIN_LED_BLUE,
        .pin_buzzer = BOARD_PIN_BUZZER,
    };
    if (!ui_hw_init(&pins)) {
        ESP_LOGW(TAG, "OLED not found; LED and buzzer only");
    }
    network_start();
    if (build_status(s_last_will, sizeof s_last_will, NODE_OFFLINE) == 0) {
        ESP_LOGE(TAG, "last will does not serialize");
        return;
    }
    const telemetry_mqtt_cfg_t tcfg = {
        .prov = &s_prov,
        .id = &s_id,
        .queue = &s_queue,
        .events = &s_events,
        .queue_lock = s_queue_lock,
        .on_config = on_threshold_config,
        .last_will_json = s_last_will,
    };
    if (!telemetry_mqtt_start(&tcfg)) {
        ESP_LOGE(TAG, "MQTT client failed to start; measuring locally only");
    }
    xTaskCreatePinnedToCore(measure_task, "measure", 6144, NULL, 10, NULL, 1);
    xTaskCreate(telemetry_task, "telemetry", 8192, NULL, 5, NULL);
    xTaskCreate(ui_task, "ui", 4096, NULL, 3, NULL);
    xTaskCreate(console_task, "console", 4096, NULL, 2, NULL);
}
