// Acquisition (T043): turns the ADC1 continuous conversion stream into V/I pairs.
//
// The driver converts GPIO4 (voltage) then GPIO5 (current) at 8,000 conversions/s,
// so each pair is a voltage conversion followed by its current conversion one slot
// later (4,000 pairs/s; metering corrects that half-pair delay). Anything that
// breaks the alternation (a DMA pool overrun, a current without its voltage, two
// voltages in a row, an unknown channel) is reported as a gap: the pending sample
// is dropped and metering raises `sample_gap` for the block.
//
// Hardware-free: the ESP-IDF continuous driver sits behind adc_port_t
// (acquisition_esp.c on the target, fake_adc.c in host tests).
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "adc_port.h"

#define ACQ_READ_MAX 128 // conversions per poll

typedef void (*acq_pair_fn)(void *ctx, uint16_t v_mv, uint16_t i_mv);
typedef void (*acq_gap_fn)(void *ctx);

typedef struct {
    uint8_t v_channel, i_channel;
    acq_pair_fn on_pair;
    acq_gap_fn on_gap;
    void *ctx;
    bool have_v;
    uint16_t v_mv;
    bool gap_reported; // collapse consecutive breaks into one gap event
    uint32_t pairs, gaps, overruns;
} acq_t;

void acq_init(acq_t *a, uint8_t v_channel, uint8_t i_channel, acq_pair_fn on_pair,
              acq_gap_fn on_gap, void *ctx);
void acq_feed(acq_t *a, const adc_conversion_t *conv, size_t n);
// Conversions were lost (DMA overrun): drop the pending voltage and report a gap.
void acq_overrun(acq_t *a);
// Reads one batch from the port and feeds it; returns the port status.
adc_port_status_t acq_poll(acq_t *a, const adc_port_t *port, uint32_t timeout_ms);

// Target only: ESP-IDF continuous mode + curve-fitting calibration (acquisition_esp.c),
// alternating `v_channel` then `i_channel` on ADC1.
bool acquisition_esp_start(adc_port_t *out, uint8_t v_channel, uint8_t i_channel,
                           uint32_t conversions_per_s);
