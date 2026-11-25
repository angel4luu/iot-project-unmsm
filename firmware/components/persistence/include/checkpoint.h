// Energy checkpoint in NVS (T047; research R-003, amended 2026-11-18).
//
// The imported-energy total is checkpointed every 60 s and on orderly shutdown as
// double-buffered records (two keys, written alternately) with a sequence number
// and CRC, so a power loss during a write leaves the other record intact.
//
// On boot:
// - a valid record marked clean (orderly shutdown) resumes the counter with no flag;
// - a valid record not marked clean (crash, power loss, watchdog) resumes the
//   counter from the last checkpoint and the first summary after boot carries
//   `energy_continuity_uncertain` (energy since that checkpoint, at most 60 s,
//   is lost, so the total may step back by that amount on a flagged window);
// - no valid record: continuity cannot be established, so a new `counter_id`
//   starts at 0 Wh.
// After restoring, the record is rewritten as not clean, so a later crash is seen.
#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "metering.h"
#include "nvs_port.h"

#define CHECKPOINT_INTERVAL_US (60LL * 1000000LL)

typedef enum {
    CHECKPOINT_RESUMED_CLEAN = 0,
    CHECKPOINT_RESUMED_UNCLEAN,
    CHECKPOINT_NEW_COUNTER,
} checkpoint_restore_t;

typedef struct {
    uint32_t next_seq; // sequence of the next record to write
    int64_t last_save_us;
} checkpoint_state_t;

// Writes a random UUID v4 string (36 chars + NUL). esp_random() on the target.
typedef void (*checkpoint_uuid_fn)(char out[METERING_UUID_LEN + 1], void *ctx);

checkpoint_restore_t checkpoint_restore(const nvs_port_t *nvs, checkpoint_state_t *st,
                                        energy_counter_t *out, checkpoint_uuid_fn uuid,
                                        void *uuid_ctx, int64_t now_us);
// Saves when 60 s have passed since the last save (or when `force`); `clean` marks an
// orderly shutdown. Returns false only on an NVS error.
bool checkpoint_save(const nvs_port_t *nvs, checkpoint_state_t *st, const energy_counter_t *e,
                     bool clean, bool force, int64_t now_us);
