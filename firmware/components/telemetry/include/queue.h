// RAM offline queue (T048; plan › Telemetry, Delivery, and Clock Design).
//
// A summary is written here before it is published and removed only when the
// server answers `accepted` or `duplicate`. A terminal `rejected` moves its
// identity to a small diagnostics ring (and out of the queue) so the node never
// retries a contract violation forever. Records are sent oldest first, with at
// most QUEUE_MAX_IN_FLIGHT unacknowledged. 256 records hold more than 21 minutes
// of 5 s summaries, enough for the specified 10-minute outage; when full, the
// oldest record is dropped and counted (the server sees a sequence gap).
// The queue lives in RAM: a power loss or reboot loses it (reported as a gap).
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "record.h"

#define QUEUE_CAPACITY 256u
#define QUEUE_MAX_IN_FLIGHT 10u
#define QUEUE_DIAG_CAPACITY 8u
#define QUEUE_REASON_MAX 64

typedef enum {
    ACK_ACCEPTED = 0,
    ACK_DUPLICATE,
    ACK_REJECTED,
} ack_status_t;

typedef struct {
    measurement_record_t rec;
    bool used;
    bool in_flight;
    int64_t sent_us;
} queue_slot_t;

typedef struct {
    char message_id[REC_UUID_LEN + 1];
    char reason[QUEUE_REASON_MAX + 1];
} queue_diag_t;

typedef struct {
    queue_slot_t slots[QUEUE_CAPACITY];
    uint32_t head;  // oldest slot (ring index)
    uint32_t span;  // slots from head to the newest, including removed holes
    uint32_t count; // used slots
    uint32_t in_flight;
    uint32_t dropped;  // overwritten because the queue was full
    uint32_t rejected; // terminal rejections moved to diagnostics
    queue_diag_t diag[QUEUE_DIAG_CAPACITY];
    uint32_t diag_next;
} telemetry_queue_t;

void queue_init(telemetry_queue_t *q);
// Returns false when the oldest record had to be dropped to make room.
bool queue_push(telemetry_queue_t *q, const measurement_record_t *rec);
// Oldest record that is not in flight, if fewer than QUEUE_MAX_IN_FLIGHT are; marks it
// in flight. NULL when nothing may be sent now.
const measurement_record_t *queue_next(telemetry_queue_t *q, int64_t now_us);
// Applies an application ACK; false when the message is not in the queue (already
// removed, or dropped) - harmless.
bool queue_ack(telemetry_queue_t *q, const char *message_id, ack_status_t status,
               const char *reason);
// After a reconnect, or when in-flight records got no ACK within `timeout_us`,
// make them sendable again (the server deduplicates).
void queue_requeue_all(telemetry_queue_t *q);
void queue_requeue_stale(telemetry_queue_t *q, int64_t now_us, int64_t timeout_us);
uint32_t queue_pending(const telemetry_queue_t *q);
// Age of the oldest queued record from its uptime stamp, in seconds (0 when empty).
int64_t queue_oldest_age_s(const telemetry_queue_t *q, uint64_t now_uptime_ms);

// ---- drain (T069; plan: oldest first, >= 2 records/s, <= 10 in flight) -------------

typedef enum {
    QUEUE_SEND_OK = 0,     // handed to the transport; now waits for the ACK
    QUEUE_SEND_FAILED,     // transport down: stop and resend everything later
    QUEUE_SEND_UNSENDABLE, // cannot be serialized: to diagnostics, never retried
} queue_send_result_t;

typedef struct {
    void (*lock)(void *ctx);   // may be NULL (single-threaded host tests)
    void (*unlock)(void *ctx); // released around every send, so producers never wait
    queue_send_result_t (*send)(void *ctx, const measurement_record_t *rec);
    void *ctx;
} queue_drain_ops_t;

// One pump step: returns in-flight records whose ACK is older than `ack_timeout_us`
// to the queue, then sends the oldest sendable records until QUEUE_MAX_IN_FLIGHT are
// unacknowledged. Called every ~100 ms, so the drain rate is bounded by the ACK
// round trip (10 per round trip; >= 2 records/s while it is <= 5 s), not by a timer.
// Returns the number of records sent.
uint32_t queue_drain(telemetry_queue_t *q, int64_t now_us, int64_t ack_timeout_us,
                     const queue_drain_ops_t *ops);

// Parses the server's measurement ACK (contracts/measurement-ack.schema.json):
// message_id, status, and reason_code (empty when null). False on anything else.
bool queue_parse_ack(const char *json, size_t len, char message_id[REC_UUID_LEN + 1],
                     ack_status_t *status, char reason[QUEUE_REASON_MAX + 1]);
