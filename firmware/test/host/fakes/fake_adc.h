// ADC fake: replays a waveform fixture as the alternating V/I conversion stream
// the ESP32-S3 continuous driver produces. A gap in pair indices is reported as
// ADC_PORT_OVERRUN once, exactly where the real driver would lose conversions.
#pragma once

#include "adc_port.h"
#include "fixtures.h"

typedef struct {
    const fixture_t *fixture;
    size_t row;       // next pair row
    int half;         // 0: voltage next, 1: current next
    bool gap_pending; // overrun reported before resuming after a gap
} fake_adc_t;

adc_port_t fake_adc_init(fake_adc_t *f, const fixture_t *fixture);
