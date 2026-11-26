// RAM queue of node events (T082): threshold_entered/cleared and quality changes.
//
// Events have no application ACK in the v1 contracts (measurements do), so an event
// leaves this queue on the broker's QoS 1 PUBACK: from then on the broker holds it
// for the ingestion service's persistent session, and the server deduplicates on
// `event_id`. Until the PUBACK, an event is resent after a reconnect or after
// `timeout_us`. It is kept apart from the measurement queue so a long outage of
// 5 s summaries cannot push an alert event out; when this queue is full the oldest
// event is dropped and counted. Like the measurement queue it lives in RAM.
//
// The PUBACK may be reported (MQTT task) before the publisher has recorded the
// message id of its send; such early PUBACKs are kept briefly and matched later.
#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "record.h"

#define EVQ_CAPACITY 32u
#define EVQ_EARLY_ACKS 4u
#define EVQ_REASON_MAX 32

typedef struct {
    event_record_t rec;
    char reason[EVQ_REASON_MAX + 1]; // owned copy of rec.reason_code
    bool has_reason;
    bool used;
    bool in_flight;
    int msg_id; // MQTT message id of the last send; -1 before it is known
    int64_t sent_us;
} evq_slot_t;

typedef struct {
    evq_slot_t slots[EVQ_CAPACITY];
    uint32_t head, count;
    uint32_t dropped;
    int early[EVQ_EARLY_ACKS];
    uint32_t early_next;
} event_queue_t;

void evq_init(event_queue_t *q);
// Copies the event (and its reason). False when the oldest event had to be dropped.
bool evq_push(event_queue_t *q, const event_record_t *e);
// Oldest event that is not in flight; marks it in flight. Returns its slot index, or
// -1 when nothing may be sent now. `out` receives a copy whose reason_code points
// into `reason_buf`.
int evq_next(event_queue_t *q, int64_t now_us, event_record_t *out,
             char reason_buf[EVQ_REASON_MAX + 1]);
// The send of slot `idx` got MQTT message id `msg_id` (< 0: the send failed, so the
// event becomes sendable again).
void evq_sent(event_queue_t *q, int idx, int msg_id);
// Drops slot `idx` (it cannot be serialized; never retried).
void evq_discard(event_queue_t *q, int idx);
// Broker PUBACK for `msg_id`: removes the matching in-flight event. False when none
// matched (kept as an early PUBACK).
bool evq_puback(event_queue_t *q, int msg_id);
void evq_requeue_all(event_queue_t *q);
void evq_requeue_stale(event_queue_t *q, int64_t now_us, int64_t timeout_us);
uint32_t evq_pending(const event_queue_t *q);
