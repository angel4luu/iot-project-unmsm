// Local active-power threshold (T082; plan › Threshold and alert lifecycle).
//
// Evaluated once per 1 s metering block, only on `valid` blocks:
//
//   normal   --power > limit-------------------------> pending
//   pending  --above for confirm_ms------------------> firing     (threshold_entered)
//   pending  --power <= limit, or a non-valid block--> normal
//   firing   --power < clear_below_W-----------------> clearing
//   clearing --below for clear_ms--------------------> resolved -> normal (threshold_cleared)
//   clearing --power >= clear_below_W----------------> firing
//
// A block that is not `valid` (invalid or degraded: gap, clipping, disconnected
// sensor, out of range, no accepted calibration) is never read as zero or as safe:
// it never confirms and never clears. It returns `pending` to `normal`, pauses
// `firing`/`clearing` as they are, and a change of block quality raises a separate
// `measurement_quality_changed` event. The clock is not part of block validity, so
// the local warning works without SNTP and without the server (SC-004).
//
// Overload exception (FR-012, clarified 2026-11-25): a block that is degraded only
// because its current is above the calibrated range (`over_range_high`), with power
// above the limit, counts as above the limit. It can confirm and sustain `firing`,
// never clear; its quality event is still raised, and `threshold_entered` then
// carries quality `degraded`.
//
// The red LED and the buzzer are on only in `firing` and `clearing` (when the
// configuration enables the local warning). There is no relay and no cutoff
// (FR-016). Without an accepted configuration nothing is evaluated.
#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "calibration.h"
#include "metering.h"
#include "quality.h"
#include "record.h"

typedef enum {
    THR_NORMAL = 0,
    THR_PENDING,
    THR_FIRING,
    THR_CLEARING,
} thr_state_t;

typedef struct {
    uint32_t config_version;
    double limit_w;            // > 0 and <= 25 (plan B MVP range)
    double clear_below_w;      // >= 0 and < limit_w
    uint32_t confirm_ms;       // 1,000-300,000 (default 10,000)
    uint32_t clear_ms;         // 1,000-300,000
    event_severity_t severity; // warning or critical
    bool local_warning_enabled;
} thr_config_t;

// One 1 s block as threshold evidence.
typedef struct {
    quality_state_t quality; // only `valid` is electrical evidence
    double power_w;
    uint32_t duration_ms; // monotonic block length (about 1,000)
    const char *reason;   // schema flag name when not valid (static string)
    bool over_range_high; // degraded only by a current above the calibrated range
} thr_block_t;

#define THR_MAX_EVENTS 2

// Events of one step. The caller fills event_id, sequence, and observed_at_ms.
typedef struct {
    uint32_t count;
    event_record_t ev[THR_MAX_EVENTS];
} thr_events_t;

typedef struct {
    bool configured;
    thr_config_t cfg;
    thr_state_t state;
    uint32_t elapsed_ms;          // time above (pending) or below (clearing)
    quality_state_t last_quality; // of the previous block (starts `valid`)
    double last_valid_w;          // latest valid block power (local display)
} threshold_t;

void threshold_init(threshold_t *t);
// Applies an accepted configuration. `pending` restarts from `normal`; `firing`
// and `clearing` keep their state and use the new limits from the next block.
void threshold_set_config(threshold_t *t, const thr_config_t *cfg);
void threshold_step(threshold_t *t, const thr_block_t *b, thr_events_t *out);
bool threshold_warning_active(const threshold_t *t);
const char *threshold_state_name(thr_state_t s);

// Block evidence from a finished metering block, classified with the same rules as
// a 5 s window (quality.h) except the clock. `finished` is metering_block_finish's
// result; an empty block is a sample gap.
thr_block_t threshold_block_from(bool finished, const metering_block_result_t *br,
                                 const calibration_t *cal, uint32_t duration_ms);
