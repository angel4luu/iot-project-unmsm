// Target adc_port_t: ESP-IDF ADC1 continuous (DMA) mode with curve-fitting
// calibration, alternating GPIO4 (voltage) and GPIO5 (current) at 8,000
// conversions/s (plan › Front end and pin allocation). A DMA pool overflow is
// reported as ADC_PORT_OVERRUN so the caller marks a sample gap.
#include <stdatomic.h>
#include <string.h>

#include "acquisition.h"
#include "esp_adc/adc_cali.h"
#include "esp_adc/adc_cali_scheme.h"
#include "esp_adc/adc_continuous.h"
#include "esp_log.h"

#define FRAME_BYTES 256

static const char *TAG = "acq";

typedef struct {
    adc_continuous_handle_t adc;
    uint8_t v_channel, i_channel;
    adc_cali_handle_t cal_v, cal_i;
    atomic_int overflows;
    uint8_t frame[FRAME_BYTES];
} esp_adc_t;

static esp_adc_t s_adc;

static bool IRAM_ATTR on_overflow(adc_continuous_handle_t h, const adc_continuous_evt_data_t *e,
                                  void *ctx) {
    (void)h;
    (void)e;
    atomic_fetch_add(&((esp_adc_t *)ctx)->overflows, 1);
    return false;
}

static adc_port_status_t esp_read(void *ctx, adc_conversion_t *out, size_t max, size_t *n,
                                  uint32_t timeout_ms) {
    esp_adc_t *a = ctx;
    *n = 0;
    if (atomic_exchange(&a->overflows, 0) > 0) {
        return ADC_PORT_OVERRUN;
    }
    size_t want = max * SOC_ADC_DIGI_RESULT_BYTES;
    want = want < sizeof(a->frame) ? want : sizeof(a->frame);
    uint32_t got = 0;
    const esp_err_t err = adc_continuous_read(a->adc, a->frame, (uint32_t)want, &got, timeout_ms);
    if (err == ESP_ERR_TIMEOUT) {
        return ADC_PORT_TIMEOUT;
    }
    if (err != ESP_OK) {
        return ADC_PORT_ERROR;
    }
    for (uint32_t k = 0; k + SOC_ADC_DIGI_RESULT_BYTES <= got && *n < max;
         k += SOC_ADC_DIGI_RESULT_BYTES) {
        const adc_digi_output_data_t *d = (const adc_digi_output_data_t *)&a->frame[k];
        const uint8_t ch = (uint8_t)d->type2.channel;
        adc_cali_handle_t cal = ch == a->v_channel   ? a->cal_v
                                : ch == a->i_channel ? a->cal_i
                                                     : NULL;
        int mv = 0;
        if (cal == NULL || adc_cali_raw_to_voltage(cal, d->type2.data, &mv) != ESP_OK) {
            mv = 0; // unknown channel: acquisition treats it as a break in the pattern
        }
        out[*n] = (adc_conversion_t){.channel = ch, .mv = (uint16_t)(mv < 0 ? 0 : mv)};
        (*n)++;
    }
    return ADC_PORT_OK;
}

static adc_cali_handle_t cali_for(adc_channel_t ch) {
    adc_cali_curve_fitting_config_t cfg = {
        .unit_id = ADC_UNIT_1, .chan = ch, .atten = ADC_ATTEN_DB_12, .bitwidth = ADC_BITWIDTH_12};
    adc_cali_handle_t h = NULL;
    return adc_cali_create_scheme_curve_fitting(&cfg, &h) == ESP_OK ? h : NULL;
}

bool acquisition_esp_start(adc_port_t *out, uint8_t v_channel, uint8_t i_channel,
                           uint32_t conversions_per_s) {
    memset(&s_adc, 0, sizeof(s_adc));
    s_adc.v_channel = v_channel;
    s_adc.i_channel = i_channel;
    adc_continuous_handle_cfg_t hcfg = {.max_store_buf_size = 4096, .conv_frame_size = FRAME_BYTES};
    if (adc_continuous_new_handle(&hcfg, &s_adc.adc) != ESP_OK) {
        return false;
    }
    adc_digi_pattern_config_t pattern[2] = {
        {.atten = ADC_ATTEN_DB_12,
         .channel = v_channel,
         .unit = ADC_UNIT_1,
         .bit_width = ADC_BITWIDTH_12},
        {.atten = ADC_ATTEN_DB_12,
         .channel = i_channel,
         .unit = ADC_UNIT_1,
         .bit_width = ADC_BITWIDTH_12},
    };
    adc_continuous_config_t cfg = {
        .pattern_num = 2,
        .adc_pattern = pattern,
        .sample_freq_hz = conversions_per_s,
        .conv_mode = ADC_CONV_SINGLE_UNIT_1,
        .format = ADC_DIGI_OUTPUT_FORMAT_TYPE2,
    };
    adc_continuous_evt_cbs_t cbs = {.on_pool_ovf = on_overflow};
    s_adc.cal_v = cali_for((adc_channel_t)v_channel);
    s_adc.cal_i = cali_for((adc_channel_t)i_channel);
    if (s_adc.cal_v == NULL || s_adc.cal_i == NULL ||
        adc_continuous_config(s_adc.adc, &cfg) != ESP_OK ||
        adc_continuous_register_event_callbacks(s_adc.adc, &cbs, &s_adc) != ESP_OK ||
        adc_continuous_start(s_adc.adc) != ESP_OK) {
        ESP_LOGE(TAG, "ADC continuous start failed");
        return false;
    }
    *out = (adc_port_t){.read = esp_read, .ctx = &s_adc};
    return true;
}
