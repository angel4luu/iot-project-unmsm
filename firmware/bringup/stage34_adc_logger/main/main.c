// Build guide stages 3-4 (T029): raw ADC logger for the analog front end.
//
// Samples GPIO4 (voltage, ADC1_CH3) and GPIO5 (current, ADC1_CH4) alternately in
// continuous mode at 8,000 conversions/s, converts each to mV with the Espressif
// curve-fitting calibration, and prints mean/min/max per channel every second.
//
// Expected readings (plan.md, Front end and pin allocation):
//   - stage 3, adapter unplugged: GPIO4 mean about 1650 mV (bias), small spread;
//   - stage 3, adapter plugged: GPIO4 about 1650 +- 760 mV peak at 12 V RMS;
//   - stage 4, no loop current: GPIO5 mean about 1700 mV (ACS712 zero offset);
//   - stage 4, bulb on (1.7 A RMS): GPIO5 about 1700 +- 160 mV peak.
// Type `d` + Enter to dump the next second as CSV (`pair,v_mv,i_mv`), the same
// format as tests/fixtures/waveforms, so a bench capture can be replayed on the PC.
#include <limits.h>
#include <stdatomic.h>
#include <stdio.h>
#include <string.h>

#include "board.h"
#include "esp_adc/adc_cali.h"
#include "esp_adc/adc_cali_scheme.h"
#include "esp_adc/adc_continuous.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"

#define FRAME_BYTES 256
#define PAIRS_PER_S (BOARD_ADC_CONVERSIONS_PER_S / 2)

static const char *TAG = "stage34";
static atomic_int s_overruns;
static uint16_t s_dump_v[PAIRS_PER_S], s_dump_i[PAIRS_PER_S];

typedef struct {
    int64_t sum;
    int min, max;
    uint32_t n;
} stats_t;

static void stats_reset(stats_t *s) {
    *s = (stats_t){.min = INT_MAX, .max = INT_MIN};
}

static void stats_add(stats_t *s, int mv) {
    s->sum += mv;
    s->n++;
    s->min = mv < s->min ? mv : s->min;
    s->max = mv > s->max ? mv : s->max;
}

static bool IRAM_ATTR on_overflow(adc_continuous_handle_t h, const adc_continuous_evt_data_t *e,
                                  void *ctx) {
    (void)h;
    (void)e;
    (void)ctx;
    atomic_fetch_add(&s_overruns, 1);
    return false;
}

static adc_cali_handle_t cali_for(adc_channel_t ch) {
    adc_cali_curve_fitting_config_t cfg = {
        .unit_id = ADC_UNIT_1, .chan = ch, .atten = ADC_ATTEN_DB_12, .bitwidth = ADC_BITWIDTH_12};
    adc_cali_handle_t h = NULL;
    ESP_ERROR_CHECK(adc_cali_create_scheme_curve_fitting(&cfg, &h));
    return h;
}

void app_main(void) {
    adc_continuous_handle_t adc;
    adc_continuous_handle_cfg_t hcfg = {.max_store_buf_size = 4096, .conv_frame_size = FRAME_BYTES};
    ESP_ERROR_CHECK(adc_continuous_new_handle(&hcfg, &adc));
    adc_digi_pattern_config_t pattern[2] = {
        {.atten = ADC_ATTEN_DB_12,
         .channel = BOARD_ADC_CH_VOLTAGE,
         .unit = ADC_UNIT_1,
         .bit_width = ADC_BITWIDTH_12},
        {.atten = ADC_ATTEN_DB_12,
         .channel = BOARD_ADC_CH_CURRENT,
         .unit = ADC_UNIT_1,
         .bit_width = ADC_BITWIDTH_12},
    };
    adc_continuous_config_t cfg = {
        .pattern_num = 2,
        .adc_pattern = pattern,
        .sample_freq_hz = BOARD_ADC_CONVERSIONS_PER_S,
        .conv_mode = ADC_CONV_SINGLE_UNIT_1,
        .format = ADC_DIGI_OUTPUT_FORMAT_TYPE2,
    };
    ESP_ERROR_CHECK(adc_continuous_config(adc, &cfg));
    adc_continuous_evt_cbs_t cbs = {.on_pool_ovf = on_overflow};
    ESP_ERROR_CHECK(adc_continuous_register_event_callbacks(adc, &cbs, NULL));
    adc_cali_handle_t cal_v = cali_for(BOARD_ADC_CH_VOLTAGE);
    adc_cali_handle_t cal_i = cali_for(BOARD_ADC_CH_CURRENT);
    ESP_ERROR_CHECK(adc_continuous_start(adc));
    ESP_LOGI(TAG, "logging GPIO%d (V) and GPIO%d (I) at %d conversions/s; `d` dumps CSV",
             BOARD_PIN_VOLTAGE, BOARD_PIN_CURRENT, BOARD_ADC_CONVERSIONS_PER_S);

    uint8_t frame[FRAME_BYTES];
    stats_t sv, si;
    stats_reset(&sv);
    stats_reset(&si);
    bool dumping = false;
    int pending_v = -1; // voltage waiting for its paired current conversion
    uint32_t pairs = 0;
    TickType_t last = xTaskGetTickCount();
    for (;;) {
        uint32_t got = 0;
        esp_err_t err = adc_continuous_read(adc, frame, sizeof frame, &got, 100);
        if (err == ESP_OK) {
            for (uint32_t k = 0; k + SOC_ADC_DIGI_RESULT_BYTES <= got;
                 k += SOC_ADC_DIGI_RESULT_BYTES) {
                const adc_digi_output_data_t *d = (const adc_digi_output_data_t *)&frame[k];
                int mv = 0;
                if (d->type2.channel == BOARD_ADC_CH_VOLTAGE) {
                    adc_cali_raw_to_voltage(cal_v, d->type2.data, &mv);
                    stats_add(&sv, mv);
                    pending_v = mv;
                } else if (d->type2.channel == BOARD_ADC_CH_CURRENT && pending_v >= 0) {
                    adc_cali_raw_to_voltage(cal_i, d->type2.data, &mv);
                    stats_add(&si, mv);
                    if (dumping && pairs < PAIRS_PER_S) {
                        s_dump_v[pairs] = (uint16_t)pending_v;
                        s_dump_i[pairs] = (uint16_t)mv;
                    }
                    pairs++;
                    pending_v = -1;
                }
            }
        }
        if (xTaskGetTickCount() - last < pdMS_TO_TICKS(1000)) {
            continue;
        }
        last = xTaskGetTickCount();
        if (sv.n && si.n) {
            printf("V GPIO%d mean %4lld min %4d max %4d mV | I GPIO%d mean %4lld min %4d max %4d mV"
                   " | pairs %lu overruns %d\n",
                   BOARD_PIN_VOLTAGE, sv.sum / sv.n, sv.min, sv.max, BOARD_PIN_CURRENT,
                   si.sum / si.n, si.min, si.max, (unsigned long)pairs, atomic_load(&s_overruns));
        }
        if (dumping) {
            printf("# stage34 dump: %lu pairs, %d conversions/s, current 1 conversion after "
                   "voltage\npair,v_mv,i_mv\n",
                   (unsigned long)(pairs < PAIRS_PER_S ? pairs : PAIRS_PER_S),
                   BOARD_ADC_CONVERSIONS_PER_S);
            for (uint32_t p = 0; p < pairs && p < PAIRS_PER_S; p++) {
                printf("%lu,%u,%u\n", (unsigned long)p, s_dump_v[p], s_dump_i[p]);
            }
            printf("# end of dump\n");
            dumping = false;
        } else {
            int c = getchar(); // non-blocking on the default console
            dumping = c == 'd' || c == 'D';
        }
        stats_reset(&sv);
        stats_reset(&si);
        pairs = 0;
    }
}
