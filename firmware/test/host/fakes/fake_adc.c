#include "fake_adc.h"

#include "board.h"

static adc_port_status_t fake_read(void *ctx, adc_conversion_t *out, size_t max, size_t *n,
                                   uint32_t timeout_ms) {
    (void)timeout_ms;
    fake_adc_t *f = ctx;
    *n = 0;
    while (*n < max && f->row < f->fixture->count) {
        if (f->half == 0 && f->row > 0 &&
            f->fixture->pair[f->row] != f->fixture->pair[f->row - 1] + 1 && !f->gap_pending) {
            f->gap_pending = true;
            return ADC_PORT_OVERRUN; // conversions read before the gap stay in out[0..*n)
        }
        f->gap_pending = false;
        if (f->half == 0) {
            out[*n] = (adc_conversion_t){BOARD_ADC_CH_VOLTAGE, f->fixture->v_mv[f->row]};
            f->half = 1;
        } else {
            out[*n] = (adc_conversion_t){BOARD_ADC_CH_CURRENT, f->fixture->i_mv[f->row]};
            f->half = 0;
            f->row++;
        }
        (*n)++;
    }
    return (*n == 0 && f->row >= f->fixture->count) ? ADC_PORT_END : ADC_PORT_OK;
}

adc_port_t fake_adc_init(fake_adc_t *f, const fixture_t *fixture) {
    *f = (fake_adc_t){.fixture = fixture};
    return (adc_port_t){fake_read, f};
}
