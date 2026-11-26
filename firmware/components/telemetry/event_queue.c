#include "event_queue.h"

#include <string.h>

static evq_slot_t *at(event_queue_t *q, uint32_t k) {
    return &q->slots[(q->head + k) % EVQ_CAPACITY];
}

static void forget_early(event_queue_t *q) {
    for (uint32_t k = 0; k < EVQ_EARLY_ACKS; k++) {
        q->early[k] = -1;
    }
}

void evq_init(event_queue_t *q) {
    memset(q, 0, sizeof(*q));
    forget_early(q);
}

// Drops removed slots from the front, so `head` is always the oldest live event.
static void trim(event_queue_t *q) {
    while (q->count > 0 && !q->slots[q->head].used) {
        q->head = (q->head + 1u) % EVQ_CAPACITY;
        q->count--;
    }
}

bool evq_push(event_queue_t *q, const event_record_t *e) {
    bool kept_all = true;
    if (q->count == EVQ_CAPACITY) {
        q->slots[q->head].used = false;
        trim(q);
        q->dropped++;
        kept_all = false;
    }
    evq_slot_t *s = at(q, q->count);
    memset(s, 0, sizeof(*s));
    s->rec = *e;
    s->has_reason = e->reason_code != NULL;
    if (s->has_reason) {
        strncpy(s->reason, e->reason_code, EVQ_REASON_MAX);
    }
    s->rec.reason_code = NULL; // resolved from `reason` on send
    s->used = true;
    s->msg_id = -1;
    q->count++;
    return kept_all;
}

int evq_next(event_queue_t *q, int64_t now_us, event_record_t *out,
             char reason_buf[EVQ_REASON_MAX + 1]) {
    for (uint32_t k = 0; k < q->count; k++) {
        evq_slot_t *s = at(q, k);
        if (s->used && !s->in_flight) {
            s->in_flight = true;
            s->msg_id = -1;
            s->sent_us = now_us;
            *out = s->rec;
            memcpy(reason_buf, s->reason, EVQ_REASON_MAX + 1);
            out->reason_code = s->has_reason ? reason_buf : NULL;
            return (int)((q->head + k) % EVQ_CAPACITY);
        }
    }
    return -1;
}

static void remove_slot(event_queue_t *q, evq_slot_t *s) {
    s->used = false;
    s->in_flight = false;
    trim(q);
}

void evq_sent(event_queue_t *q, int idx, int msg_id) {
    if (idx < 0 || (uint32_t)idx >= EVQ_CAPACITY) {
        return;
    }
    evq_slot_t *s = &q->slots[idx];
    if (!s->used || !s->in_flight) {
        return; // dropped meanwhile
    }
    if (msg_id < 0) {
        s->in_flight = false;
        return;
    }
    for (uint32_t k = 0; k < EVQ_EARLY_ACKS; k++) {
        if (q->early[k] == msg_id) { // the PUBACK came first
            q->early[k] = -1;
            remove_slot(q, s);
            return;
        }
    }
    s->msg_id = msg_id;
}

void evq_discard(event_queue_t *q, int idx) {
    if (idx >= 0 && (uint32_t)idx < EVQ_CAPACITY && q->slots[idx].used) {
        remove_slot(q, &q->slots[idx]);
    }
}

bool evq_puback(event_queue_t *q, int msg_id) {
    bool send_unrecorded = false;
    for (uint32_t k = 0; k < q->count; k++) {
        evq_slot_t *s = at(q, k);
        if (s->used && s->in_flight && s->msg_id == msg_id && msg_id >= 0) {
            remove_slot(q, s);
            return true;
        }
        send_unrecorded = send_unrecorded || (s->used && s->in_flight && s->msg_id < 0);
    }
    if (send_unrecorded && msg_id >= 0) { // may be ours; other PUBACKs (measurements) are not kept
        q->early[q->early_next++ % EVQ_EARLY_ACKS] = msg_id;
    }
    return false;
}

void evq_requeue_all(event_queue_t *q) {
    for (uint32_t k = 0; k < q->count; k++) {
        at(q, k)->in_flight = false;
    }
    forget_early(q);
}

void evq_requeue_stale(event_queue_t *q, int64_t now_us, int64_t timeout_us) {
    for (uint32_t k = 0; k < q->count; k++) {
        evq_slot_t *s = at(q, k);
        if (s->used && s->in_flight && now_us - s->sent_us >= timeout_us) {
            s->in_flight = false;
        }
    }
}

uint32_t evq_pending(const event_queue_t *q) {
    uint32_t n = 0;
    for (uint32_t k = 0; k < q->count; k++) {
        if (q->slots[(q->head + k) % EVQ_CAPACITY].used) {
            n++;
        }
    }
    return n;
}
