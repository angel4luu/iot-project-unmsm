#include "ui_state.h"

#include <ctype.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>

// Writes one line, upper-cased and limited to the font's characters.
static void line(ui_view_t *v, int row, const char *fmt, ...) {
    char tmp[64];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(tmp, sizeof tmp, fmt, ap);
    va_end(ap);
    char *out = v->lines[row];
    size_t n = 0;
    for (const char *p = tmp; *p && n < UI_COLS; p++) {
        char c = (char)toupper((unsigned char)*p);
        if (!((c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == ' ' || c == '-' ||
              c == ':' || c == '.')) {
            c = ' '; // e.g. '_' in flag names
        }
        out[n++] = c;
    }
    out[n] = '\0';
}

static const char *clock_label(clock_source_t c) {
    switch (c) {
    case CLOCK_SOURCE_SNTP:
        return "SNTP";
    case CLOCK_SOURCE_HOLDOVER:
        return "HOLDOVER";
    case CLOCK_SOURCE_UNSYNCHRONIZED:
        return "SIN HORA";
    }
    return "SIN HORA";
}

static void footer(const ui_input_t *in, ui_view_t *v) {
    line(v, 6, "%s %s", clock_label(in->clock), in->link_up ? "RED OK" : "SIN RED");
    if (in->calibration_nominal) {
        line(v, 7, "NO VALIDADO");
    }
}

void ui_render(const ui_input_t *in, ui_view_t *v) {
    memset(v, 0, sizeof(*v));
    const bool value_ok = in->have_summary && in->quality == QUALITY_VALID &&
                          in->clock != CLOCK_SOURCE_UNSYNCHRONIZED;

    if (in->warning_active) {
        v->mode = UI_MODE_WARNING;
        v->led = UI_LED_RED;
        v->buzzer = true;
        line(v, 0, "ALERTA POTENCIA");
        if (value_ok) {
            line(v, 1, "%.1f W", in->warning_value_w);
        } else {
            line(v, 1, "VALOR NO VALIDO");
        }
        line(v, 2, "LIMITE %.1f W", in->warning_limit_w);
    } else if (in->warming_up || !in->have_summary || !in->calibration_accepted) {
        v->mode = UI_MODE_INSUFFICIENT;
        v->led = UI_LED_WHITE;
        line(v, 0, "DATOS INSUFICIENTES");
        line(v, 1, "%s",
             in->warming_up      ? "CALENTANDO"
             : !in->have_summary ? "ESPERANDO VENTANA"
                                 : "SIN CALIBRACION");
    } else if (!value_ok) {
        v->mode = UI_MODE_INVALID;
        v->led = UI_LED_YELLOW;
        line(v, 0, "MEDICION NO VALIDA");
        const char *reason = quality_reason(in->flags);
        line(v, 1, "%s",
             reason[0]                                  ? reason
             : in->clock == CLOCK_SOURCE_UNSYNCHRONIZED ? "clock unsynchronized"
                                                        : "calidad");
        line(v, 2, "V A W WH: ---");
    } else {
        v->mode = in->link_up ? UI_MODE_NORMAL : UI_MODE_OFFLINE;
        v->led = in->link_up ? UI_LED_GREEN : UI_LED_BLUE;
        line(v, 0, "%.2f V  %.3f A", in->v_rms_v, in->i_rms_a);
        line(v, 1, "%.2f W", in->active_power_w);
        line(v, 2, "%.3f WH", in->energy_wh);
        line(v, 3, "CALIDAD: VALIDA");
        if (!in->link_up) {
            line(v, 4, "EN COLA: %u", (unsigned)in->queued);
        }
    }
    footer(in, v);
}
