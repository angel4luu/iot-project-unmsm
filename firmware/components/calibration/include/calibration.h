// Calibration coefficients (T044; plan › Calibration and plausibility procedure).
//
// The MVP uses `nominal` coefficients only: voltage gain from R1/R2, current gain
// from the ACS712 sensitivity (100 mV/A) and R3/R4, and a phase correction of
// one conversion (half a pair period). No reference meter is used, so every value
// computed with these coefficients is "not validated" (constitution 2.0.0).
//
// On the node, a calibration is "accepted" once it is frozen into an append-only
// NVS revision after the bench procedure (offset capture, sign check). Until then
// windows carry `calibration_missing`.
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "nvs_port.h"

#define CAL_REVISION_MAX 64
#define CAL_NODE_ID_MAX 32
#define CAL_LAYOUT_VERSION 1u
#define CAL_MAX_REVISIONS 99u

typedef enum {
    CAL_KIND_NOMINAL = 0,
    CAL_KIND_REFERENCE = 1, // future: needs a true-RMS reference meter
} cal_kind_t;

// Nominal front end (tests/fixtures/waveforms/frontend.json; plan › Front end).
typedef struct {
    double r1_ohm, r2_ohm;            // voltage divider
    double r3_ohm, r4_ohm;            // ACS712 output divider
    double sensitivity_mv_per_a;      // ACS712-20A: 100 mV/A
    double acs_zero_mv;               // ACS712 output at zero current (VCC/2)
    double bias_mv;                   // voltage channel mid-supply bias
    double current_delay_conversions; // current converted one slot after voltage
    double zero_noise_current_a;      // absolute noise limit (no-load current)
} cal_frontend_t;

extern const cal_frontend_t CAL_FRONTEND_NOMINAL;

typedef struct {
    uint32_t layout;                     // CAL_LAYOUT_VERSION
    uint32_t revision_number;            // 1, 2, ... (append-only)
    char revision[CAL_REVISION_MAX + 1]; // "<node>-nominal-r<n>"; empty until frozen
    cal_kind_t kind;
    double voltage_gain;           // V at the load per V at the pin
    double current_gain;           // A in the loop per V at the pin
    double phase_correction_pairs; // current lag in pair periods (0.5 nominal)
    int32_t current_sign;          // +1 or -1 (sign correction, plan step 6)
    double current_zero_mv;        // ACS712 zero at the pin (captured, plan step 5)
    double voltage_bias_mv;        // expected voltage channel bias at the pin
    double zero_noise_current_a;   // no-load current limit
    bool frozen;                   // accepted on the node (stored revision)
    uint32_t crc;                  // over everything above; checked on load
} calibration_t;

// Nominal coefficients from the front end, not yet frozen (no revision).
void calibration_nominal(calibration_t *c, const cal_frontend_t *fe);
bool calibration_accepted(const calibration_t *c);

// ---- 60 s zero-current offset capture (bulb off) ---------------------------------

#define CAL_OFFSET_CAPTURE_S 60u
#define CAL_OFFSET_MAX_SHIFT_MV 200.0 // farther from nominal zero: sensor disconnected

typedef struct {
    uint64_t n;
    double sum, sumsq;
} cal_offset_capture_t;

typedef enum {
    CAL_OFFSET_OK = 0,
    CAL_OFFSET_TOO_SHORT,    // fewer than 99 % of the pairs of 60 s
    CAL_OFFSET_DISCONNECTED, // mean too far from the nominal zero
} cal_offset_result_t;

void cal_offset_begin(cal_offset_capture_t *cap);
void cal_offset_add(cal_offset_capture_t *cap, uint16_t i_mv);
// Stores the mean as `current_zero_mv` and widens the noise limit to 3 sigma when
// the measured noise is larger than the nominal limit.
cal_offset_result_t cal_offset_finish(const cal_offset_capture_t *cap, uint32_t pairs_per_s,
                                      calibration_t *c);

// ---- sign correction (bulb on, resistive load) --------------------------------------

// Flips `current_sign` when a resistive load shows negative power beyond
// `min_power_w`; returns true when it flipped. Refused once frozen.
bool cal_correct_sign(calibration_t *c, double measured_power_w, double min_power_w);

// ---- append-only revisions in NVS ----------------------------------------------------

typedef enum {
    CAL_STORE_OK = 0,
    CAL_STORE_FROZEN,   // the calibration given is already a stored revision
    CAL_STORE_BAD_NODE, // node_id missing or too long
    CAL_STORE_FULL,     // CAL_MAX_REVISIONS reached
    CAL_STORE_EXISTS,   // the next key already exists: never overwritten
    CAL_STORE_NVS_ERROR,
} cal_store_result_t;

// Freezes `c` as the next revision "<node>-nominal-r<n>" and stores it under a new
// key; earlier revisions are never modified.
cal_store_result_t calibration_freeze(const nvs_port_t *nvs, const char *node_id, calibration_t *c);
// Latest stored revision; false when none (or corrupt): the node runs nominal
// coefficients with `calibration_missing`.
bool calibration_load_latest(const nvs_port_t *nvs, calibration_t *out);
bool calibration_load(const nvs_port_t *nvs, uint32_t revision_number, calibration_t *out);
uint32_t calibration_revision_count(const nvs_port_t *nvs);

// CRC-32 (IEEE) shared by the persistence records.
uint32_t cal_crc32(const void *data, size_t len);
