#include "acquisition.h"

#include <string.h>

void acq_init(acq_t *a, uint8_t v_channel, uint8_t i_channel, acq_pair_fn on_pair,
              acq_gap_fn on_gap, void *ctx) {
    memset(a, 0, sizeof(*a));
    a->v_channel = v_channel;
    a->i_channel = i_channel;
    a->on_pair = on_pair;
    a->on_gap = on_gap;
    a->ctx = ctx;
}

static void gap(acq_t *a) {
    a->have_v = false;
    if (!a->gap_reported) {
        a->gap_reported = true;
        a->gaps++;
        a->on_gap(a->ctx);
    }
}

void acq_feed(acq_t *a, const adc_conversion_t *conv, size_t n) {
    for (size_t k = 0; k < n; k++) {
        const adc_conversion_t c = conv[k];
        if (c.channel == a->v_channel) {
            if (a->have_v) {
                gap(a); // the current conversion of the previous pair was lost
            }
            a->have_v = true;
            a->v_mv = c.mv;
        } else if (c.channel == a->i_channel && a->have_v) {
            a->have_v = false;
            a->gap_reported = false;
            a->pairs++;
            a->on_pair(a->ctx, a->v_mv, c.mv);
        } else {
            gap(a); // current without its voltage, or an unexpected channel
        }
    }
}

void acq_overrun(acq_t *a) {
    a->overruns++;
    gap(a);
}

adc_port_status_t acq_poll(acq_t *a, const adc_port_t *port, uint32_t timeout_ms) {
    adc_conversion_t buf[ACQ_READ_MAX];
    size_t n = 0;
    const adc_port_status_t st = port->read(port->ctx, buf, ACQ_READ_MAX, &n, timeout_ms);
    if (st == ADC_PORT_OVERRUN) {
        acq_overrun(a);
    }
    acq_feed(a, buf, n);
    return st;
}
