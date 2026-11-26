// T076: local threshold state machine (normal -> pending -> firing -> clearing ->
// resolved -> normal), events, local warning, and block evidence. The transition
// cases come from tests/fixtures/threshold/cases.txt, which the simulator's Python
// mirror also runs, so the node and the simulator follow the same table.
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "threshold.h"
#include "unity.h"

#define MAX_BLOCKS 32

static threshold_t thr;

void setUp(void) {
    threshold_init(&thr);
}

void tearDown(void) {}

static thr_config_t config(double limit, double clear, uint32_t confirm_ms, uint32_t clear_ms) {
    return (thr_config_t){
        .config_version = 1,
        .limit_w = limit,
        .clear_below_w = clear,
        .confirm_ms = confirm_ms,
        .clear_ms = clear_ms,
        .severity = SEVERITY_WARNING,
        .local_warning_enabled = true,
    };
}

static thr_block_t valid(double w) {
    return (thr_block_t){.quality = QUALITY_VALID, .power_w = w, .duration_ms = 1000};
}

static thr_block_t invalid(void) {
    return (thr_block_t){.quality = QUALITY_INVALID,
                         .power_w = NAN,
                         .duration_ms = 1000,
                         .reason = "sensor_disconnected"};
}

static char state_letter(thr_state_t s) {
    return "NPFC"[s];
}

static char event_letter(event_type_t t) {
    return t == EVENT_THRESHOLD_ENTERED ? 'E' : t == EVENT_THRESHOLD_CLEARED ? 'R' : 'Q';
}

// Splits `s` on whitespace into at most `max` tokens (in place).
static int tokens(char *s, char **out, int max) {
    int n = 0;
    for (char *tok = strtok(s, " \t"); tok != NULL && n < max; tok = strtok(NULL, " \t")) {
        out[n++] = tok;
    }
    return n;
}

static char *trim(char *s) {
    while (*s == ' ' || *s == '\t') {
        s++;
    }
    char *end = s + strlen(s);
    while (end > s && (end[-1] == ' ' || end[-1] == '\t' || end[-1] == '\n' || end[-1] == '\r')) {
        *--end = '\0';
    }
    return s;
}

static void run_case(char *line) {
    char *field[5];
    int nf = 0;
    for (char *p = line; nf < 5; nf++) {
        field[nf] = p;
        char *bar = strchr(p, '|');
        if (bar == NULL) {
            nf++;
            break;
        }
        *bar = '\0';
        p = bar + 1;
    }
    TEST_ASSERT_EQUAL_INT_MESSAGE(5, nf, line);
    const char *name = trim(field[0]);
    char *cfg_tok[4], *blk[MAX_BLOCKS], *st[MAX_BLOCKS], *evt[MAX_BLOCKS];
    TEST_ASSERT_EQUAL_INT_MESSAGE(4, tokens(field[1], cfg_tok, 4), name);
    const int nb = tokens(field[2], blk, MAX_BLOCKS);
    TEST_ASSERT_EQUAL_INT_MESSAGE(nb, tokens(field[3], st, MAX_BLOCKS), name);
    TEST_ASSERT_EQUAL_INT_MESSAGE(nb, tokens(field[4], evt, MAX_BLOCKS), name);

    threshold_init(&thr);
    const thr_config_t c =
        config(strtod(cfg_tok[0], NULL), strtod(cfg_tok[1], NULL),
               (uint32_t)strtoul(cfg_tok[2], NULL, 10), (uint32_t)strtoul(cfg_tok[3], NULL, 10));
    threshold_set_config(&thr, &c);
    for (int k = 0; k < nb; k++) {
        char msg[128];
        snprintf(msg, sizeof msg, "%s, block %d", name, k);
        const thr_block_t b = strcmp(blk[k], "x") == 0 ? invalid() : valid(strtod(blk[k], NULL));
        thr_events_t ev;
        threshold_step(&thr, &b, &ev);
        TEST_ASSERT_EQUAL_CHAR_MESSAGE(trim(st[k])[0], state_letter(thr.state), msg);
        char got[THR_MAX_EVENTS + 1] = {0};
        for (uint32_t e = 0; e < ev.count; e++) {
            got[e] = event_letter(ev.ev[e].type);
        }
        TEST_ASSERT_EQUAL_STRING_MESSAGE(strcmp(evt[k], "-") == 0 ? "" : evt[k], got, msg);
        const bool warn = thr.state == THR_FIRING || thr.state == THR_CLEARING;
        TEST_ASSERT_EQUAL_MESSAGE(warn, threshold_warning_active(&thr), msg);
    }
}

static void test_shared_transition_table(void) {
    FILE *f = fopen(THRESHOLD_CASES, "r");
    TEST_ASSERT_NOT_NULL_MESSAGE(f, THRESHOLD_CASES);
    char line[512];
    int cases = 0;
    while (fgets(line, sizeof line, f) != NULL) {
        const char *t = trim(line);
        if (t[0] == '\0' || t[0] == '#') {
            continue;
        }
        run_case(line);
        cases++;
    }
    fclose(f);
    TEST_ASSERT_TRUE(cases >= 10);
}

static void test_nothing_is_evaluated_without_config(void) {
    for (int k = 0; k < 30; k++) {
        thr_events_t ev;
        const thr_block_t b = valid(100.0);
        threshold_step(&thr, &b, &ev);
        TEST_ASSERT_EQUAL_UINT32(0, ev.count);
    }
    TEST_ASSERT_EQUAL(THR_NORMAL, thr.state);
    TEST_ASSERT_FALSE(threshold_warning_active(&thr));
}

static void step(thr_block_t b, thr_events_t *ev) {
    threshold_step(&thr, &b, ev);
}

static void test_entered_event_carries_the_evidence(void) {
    thr_config_t c = config(15.0, 14.25, 2000, 2000);
    c.config_version = 7;
    c.severity = SEVERITY_CRITICAL;
    threshold_set_config(&thr, &c);
    thr_events_t ev;
    step(valid(18.0), &ev);
    step(valid(19.5), &ev);
    TEST_ASSERT_EQUAL_UINT32(1, ev.count);
    const event_record_t *e = &ev.ev[0];
    TEST_ASSERT_EQUAL(EVENT_THRESHOLD_ENTERED, e->type);
    TEST_ASSERT_EQUAL(SEVERITY_CRITICAL, e->severity);
    TEST_ASSERT_EQUAL_UINT32(7, e->config_version);
    TEST_ASSERT_TRUE(e->has_measured && e->has_threshold && e->unit_watts);
    TEST_ASSERT_DOUBLE_WITHIN(1e-9, 19.5, e->measured_value);
    TEST_ASSERT_DOUBLE_WITHIN(1e-9, 15.0, e->threshold_value);
    TEST_ASSERT_EQUAL(QUALITY_VALID, e->quality);
    TEST_ASSERT_TRUE(e->local_warning_active);
}

static void test_cleared_event_reports_the_clear_threshold(void) {
    const thr_config_t c = config(15.0, 14.25, 1000, 1000);
    threshold_set_config(&thr, &c);
    thr_events_t ev;
    step(valid(20.0), &ev);
    step(valid(3.0), &ev);
    TEST_ASSERT_EQUAL_UINT32(1, ev.count);
    const event_record_t *e = &ev.ev[0];
    TEST_ASSERT_EQUAL(EVENT_THRESHOLD_CLEARED, e->type);
    TEST_ASSERT_EQUAL(SEVERITY_INFO, e->severity);
    TEST_ASSERT_DOUBLE_WITHIN(1e-9, 3.0, e->measured_value);
    TEST_ASSERT_DOUBLE_WITHIN(1e-9, 14.25, e->threshold_value);
    TEST_ASSERT_FALSE(e->local_warning_active);
}

static void test_invalid_data_is_a_quality_event_not_zero(void) {
    const thr_config_t c = config(15.0, 14.25, 1000, 1000);
    threshold_set_config(&thr, &c);
    thr_events_t ev;
    step(valid(20.0), &ev);        // firing
    for (int k = 0; k < 10; k++) { // invalid for a long time: still firing, never cleared
        step(invalid(), &ev);
        TEST_ASSERT_EQUAL(THR_FIRING, thr.state);
        TEST_ASSERT_TRUE(threshold_warning_active(&thr));
        TEST_ASSERT_EQUAL_UINT32(k == 0 ? 1 : 0, ev.count); // one event per change
    }
    step(invalid(), &ev);
    step(valid(20.0), &ev);
    TEST_ASSERT_EQUAL_UINT32(1, ev.count);
    TEST_ASSERT_EQUAL(EVENT_MEASUREMENT_QUALITY_CHANGED, ev.ev[0].type);
    TEST_ASSERT_EQUAL(QUALITY_VALID, ev.ev[0].quality);
    TEST_ASSERT_EQUAL_STRING("quality_restored", ev.ev[0].reason_code);

    threshold_init(&thr);
    threshold_set_config(&thr, &c);
    step(invalid(), &ev);
    TEST_ASSERT_EQUAL_UINT32(1, ev.count);
    const event_record_t *e = &ev.ev[0];
    TEST_ASSERT_EQUAL(EVENT_MEASUREMENT_QUALITY_CHANGED, e->type);
    TEST_ASSERT_EQUAL(SEVERITY_WARNING, e->severity);
    TEST_ASSERT_EQUAL(QUALITY_INVALID, e->quality);
    TEST_ASSERT_FALSE(e->has_measured); // null, never 0 W
    TEST_ASSERT_FALSE(e->has_threshold);
    TEST_ASSERT_FALSE(e->unit_watts);
    TEST_ASSERT_EQUAL_STRING("sensor_disconnected", e->reason_code);
}

static void test_degraded_block_is_not_evidence(void) {
    const thr_config_t c = config(15.0, 14.25, 2000, 1000);
    threshold_set_config(&thr, &c);
    thr_events_t ev;
    step(valid(20.0), &ev);
    thr_block_t d = valid(20.0);
    d.quality = QUALITY_DEGRADED;
    d.reason = "out_of_range";
    step(d, &ev);
    TEST_ASSERT_EQUAL(THR_NORMAL, thr.state); // pending left; the degraded block did not confirm
    TEST_ASSERT_EQUAL_UINT32(1, ev.count);
    TEST_ASSERT_EQUAL(QUALITY_DEGRADED, ev.ev[0].quality);
}

static void test_local_warning_can_be_disabled(void) {
    thr_config_t c = config(15.0, 14.25, 1000, 1000);
    c.local_warning_enabled = false;
    threshold_set_config(&thr, &c);
    thr_events_t ev;
    step(valid(20.0), &ev);
    TEST_ASSERT_EQUAL(THR_FIRING, thr.state);
    TEST_ASSERT_EQUAL_UINT32(1, ev.count); // the event is still sent
    TEST_ASSERT_FALSE(ev.ev[0].local_warning_active);
    TEST_ASSERT_FALSE(threshold_warning_active(&thr));
}

static void test_new_config_restarts_pending_but_keeps_firing(void) {
    const thr_config_t c = config(15.0, 14.25, 3000, 1000);
    threshold_set_config(&thr, &c);
    thr_events_t ev;
    step(valid(20.0), &ev);
    step(valid(20.0), &ev);
    TEST_ASSERT_EQUAL(THR_PENDING, thr.state);
    thr_config_t c2 = c;
    c2.config_version = 2;
    threshold_set_config(&thr, &c2);
    TEST_ASSERT_EQUAL(THR_NORMAL, thr.state);
    for (int k = 0; k < 3; k++) {
        step(valid(20.0), &ev);
    }
    TEST_ASSERT_EQUAL(THR_FIRING, thr.state);
    thr_config_t c3 = c2;
    c3.config_version = 3;
    c3.limit_w = 25.0;
    c3.clear_below_w = 23.0;
    c3.clear_ms = 2000;
    threshold_set_config(&thr, &c3);
    TEST_ASSERT_EQUAL(THR_FIRING, thr.state); // no silent clear
    step(valid(20.0), &ev);                   // below the new clear threshold
    TEST_ASSERT_EQUAL(THR_CLEARING, thr.state);
}

// ---- block evidence --------------------------------------------------------------

static calibration_t cal;

static metering_block_result_t block(double v, double i, double p) {
    return (metering_block_result_t){
        .pairs = 4000,
        .v_mean_mv = cal.voltage_bias_mv,
        .i_mean_mv = cal.current_zero_mv,
        .v_rms_v = v,
        .i_rms_a = i,
        .active_power_w = p,
        .power_valid = true,
    };
}

static void accepted_calibration(void) {
    calibration_nominal(&cal, &CAL_FRONTEND_NOMINAL);
    cal.frozen = true;
    strcpy(cal.revision, "node-001-nominal-r1");
}

static void test_block_evidence_follows_window_quality_rules(void) {
    accepted_calibration();
    metering_block_result_t b = block(12.6, 1.6, 20.16);
    thr_block_t t = threshold_block_from(true, &b, &cal, 1000);
    TEST_ASSERT_EQUAL(QUALITY_VALID, t.quality);
    TEST_ASSERT_DOUBLE_WITHIN(1e-9, 20.16, t.power_w);

    b = block(12.6, 0.01, 0.05); // bulb off: no load is valid, not out of range
    TEST_ASSERT_EQUAL(QUALITY_VALID, threshold_block_from(true, &b, &cal, 1000).quality);

    b.adc_clipped = true;
    t = threshold_block_from(true, &b, &cal, 1000);
    TEST_ASSERT_EQUAL(QUALITY_INVALID, t.quality);
    TEST_ASSERT_EQUAL_STRING("adc_clipped", t.reason);

    b = block(12.6, 1.6, 20.16);
    b.pairs = 3000; // lost conversions
    TEST_ASSERT_EQUAL(QUALITY_INVALID, threshold_block_from(true, &b, &cal, 1000).quality);

    TEST_ASSERT_EQUAL(QUALITY_INVALID, threshold_block_from(false, &b, &cal, 1000).quality);

    b = block(12.6, 2.5, 31.5); // beyond the calibrated current range
    t = threshold_block_from(true, &b, &cal, 1000);
    TEST_ASSERT_EQUAL(QUALITY_DEGRADED, t.quality);
    TEST_ASSERT_EQUAL_STRING("out_of_range", t.reason);

    calibration_nominal(&cal, &CAL_FRONTEND_NOMINAL); // not frozen: not accepted
    b = block(12.6, 1.6, 20.16);
    t = threshold_block_from(true, &b, &cal, 1000);
    TEST_ASSERT_EQUAL(QUALITY_DEGRADED, t.quality);
    TEST_ASSERT_EQUAL_STRING("calibration_missing", t.reason);
}

int main(void) {
    UNITY_BEGIN();
    RUN_TEST(test_shared_transition_table);
    RUN_TEST(test_nothing_is_evaluated_without_config);
    RUN_TEST(test_entered_event_carries_the_evidence);
    RUN_TEST(test_cleared_event_reports_the_clear_threshold);
    RUN_TEST(test_invalid_data_is_a_quality_event_not_zero);
    RUN_TEST(test_degraded_block_is_not_evidence);
    RUN_TEST(test_local_warning_can_be_disabled);
    RUN_TEST(test_new_config_restarts_pending_but_keeps_firing);
    RUN_TEST(test_block_evidence_follows_window_quality_rules);
    return UNITY_END();
}
