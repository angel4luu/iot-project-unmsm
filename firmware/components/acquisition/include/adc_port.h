// ADC port: the only way acquisition code reads conversions. The target build
// implements it with ESP-IDF continuous mode plus adc_cali; host tests use a
// fake that replays waveform fixtures (firmware/test/host/fakes/fake_adc.c).
#pragma once

#include <stddef.h>
#include <stdint.h>

typedef enum {
    ADC_PORT_OK = 0,
    ADC_PORT_TIMEOUT,
    ADC_PORT_OVERRUN, // DMA overrun or lost conversions: the caller marks a sample gap
    ADC_PORT_END,     // replay finished (host fakes only)
    ADC_PORT_ERROR,
} adc_port_status_t;

typedef struct {
    uint8_t channel; // ADC1 channel number
    uint16_t mv;     // calibrated millivolts at the pin
} adc_conversion_t;

typedef struct adc_port {
    // Read up to `max` conversions in sampling order; `*n` receives the count.
    adc_port_status_t (*read)(void *ctx, adc_conversion_t *out, size_t max, size_t *n,
                              uint32_t timeout_ms);
    void *ctx;
} adc_port_t;
