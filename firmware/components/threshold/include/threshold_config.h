// Retained threshold configuration (T081; contracts/threshold-config.schema.json).
//
// The server publishes the newest configuration retained, QoS 1, on
// `unmsm/energy/v1/nodes/<node>/config`. The node parses it (flat JSON, no escapes),
// checks it against its own identity and the MVP bounds, and accepts it only when
// `config_version` is greater than the last accepted one, which it keeps in NVS so
// a reboot does not lose it and an old retained message cannot roll it back. The
// broker re-sends the retained message on every reconnect: the same version with the
// same content is `unchanged`, not an error.
#pragma once

#include <stdbool.h>
#include <stddef.h>

#include "nvs_port.h"
#include "threshold.h"

#define THR_LIMIT_MAX_W 25.0 // plan B MVP bound (the wire schema allows 2,500)
#define THR_MS_MIN 1000u
#define THR_MS_MAX 300000u
#define THR_CONFIRM_MS_DEFAULT 10000u
#define THR_CONFIG_LAYOUT_VERSION 1u

typedef enum {
    THR_CFG_OK = 0,
    THR_CFG_BAD_JSON,     // missing or malformed member
    THR_CFG_BAD_SCHEMA,   // schema_version is not 1.0.0
    THR_CFG_WRONG_TARGET, // node_id or circuit_id is not ours
    THR_CFG_OUT_OF_BOUNDS,
} thr_cfg_parse_t;

typedef enum {
    THR_CFG_ACCEPTED = 0,
    THR_CFG_UNCHANGED, // same version and content as the stored one (retained resend)
    THR_CFG_ROLLBACK,  // version not greater than the stored one: rejected
    THR_CFG_INVALID,   // fails the bounds
    THR_CFG_NVS_ERROR, // not stored, so not applied
} thr_cfg_accept_t;

// Bounds check (data-model › ThresholdConfiguration).
bool threshold_config_valid(const thr_config_t *c);
// Parses and checks one config payload for this node and circuit. `confirm_ms` falls
// back to the 10,000 ms default when absent.
thr_cfg_parse_t threshold_config_parse(const char *json, size_t len, const char *node_id,
                                       const char *circuit_id, thr_config_t *out);
// Stores `c` as the accepted config when it is valid and newer than the stored one.
thr_cfg_accept_t threshold_config_accept(const nvs_port_t *nvs, const thr_config_t *c);
// Field-by-field comparison (padding is not compared).
bool threshold_config_equal(const thr_config_t *a, const thr_config_t *b);
// Last accepted config; false when none (or corrupt): nothing is evaluated.
bool threshold_config_load(const nvs_port_t *nvs, thr_config_t *out);
const char *threshold_config_result_name(thr_cfg_accept_t r);
