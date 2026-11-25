// JSON serializer for the v1 contracts (T097): the only code that builds payloads.
//
// Output follows specs/001-energy-monitoring-system/contracts/*.schema.json
// (schema_version 1.0.0): timestamps as RFC 3339 UTC with milliseconds, values in
// canonical units, invalid quantities as null (never the last valid value), and
// a non-finite or out-of-wire-bound number written as null rather than as an
// invalid payload. Each function returns the length written (without NUL), or 0
// when the buffer is too small or an input is unusable.
#pragma once

#include <stddef.h>

#include "record.h"

#define SERIALIZE_MEASUREMENT_MAX 1024
#define SERIALIZE_STATUS_MAX 768
#define SERIALIZE_EVENT_MAX 640

size_t serialize_measurement(const node_identity_t *id, const measurement_record_t *m, char *buf,
                             size_t len);
size_t serialize_status(const node_identity_t *id, const status_record_t *s, char *buf, size_t len);
size_t serialize_event(const node_identity_t *id, const event_record_t *e, char *buf, size_t len);
