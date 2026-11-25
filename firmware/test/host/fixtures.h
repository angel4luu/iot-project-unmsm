// Waveform fixture loader for host tests (tests/fixtures/waveforms, T033/T096).
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

typedef struct {
    size_t count;   // pairs present (a sample gap removes rows)
    uint32_t *pair; // pair index of each row
    uint16_t *v_mv; // voltage pin, mV
    uint16_t *i_mv; // current pin, mV
} fixture_t;

typedef struct {
    bool valid;
    char flags[64];
    double v_rms_v, i_rms_a, active_power_w, energy_wh; // NAN when not valid
} fixture_expected_t;

typedef struct {
    double rel[4], abs[4]; // order: v_rms_v, i_rms_a, active_power_w, energy_wh
} fixture_tolerance_t;

bool fixture_load(const char *name, fixture_t *out);
void fixture_free(fixture_t *f);
bool fixture_expected(const char *name, fixture_expected_t *out);
bool fixture_tolerance(fixture_tolerance_t *out);
// True when `got` is within the relative or absolute tolerance of `want`.
bool fixture_within(double got, double want, double rel, double abs);
