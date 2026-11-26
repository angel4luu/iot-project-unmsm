#include "queue.h"

#include <string.h>

#include "json_scan.h"

static queue_slot_t *slot(telemetry_queue_t *q, uint32_t k) {
    return &q->slots[(q->head + k) % QUEUE_CAPACITY];
}

static void trim_head(telemetry_queue_t *q) {
    while (q->span > 0 && !q->slots[q->head].used) {
        q->head = (q->head + 1u) % QUEUE_CAPACITY;
        q->span--;
    }
}

static void remove_slot(telemetry_queue_t *q, queue_slot_t *s) {
    if (s->in_flight) {
        q->in_flight--;
    }
    s->used = false;
    s->in_flight = false;
    q->count--;
    trim_head(q);
}

void queue_init(telemetry_queue_t *q) {
    memset(q, 0, sizeof(*q));
}

bool queue_push(telemetry_queue_t *q, const measurement_record_t *rec) {
    bool kept_all = true;
    if (q->span == QUEUE_CAPACITY) {
        // Full: drop the oldest record; its ACK, if one comes, finds nothing.
        queue_slot_t *oldest = &q->slots[q->head];
        if (oldest->used) {
            remove_slot(q, oldest);
            q->dropped++;
            kept_all = false;
        }
        trim_head(q);
    }
    queue_slot_t *s = slot(q, q->span);
    s->rec = *rec;
    s->used = true;
    s->in_flight = false;
    s->sent_us = 0;
    q->span++;
    q->count++;
    return kept_all;
}

const measurement_record_t *queue_next(telemetry_queue_t *q, int64_t now_us) {
    if (q->in_flight >= QUEUE_MAX_IN_FLIGHT) {
        return NULL;
    }
    for (uint32_t k = 0; k < q->span; k++) {
        queue_slot_t *s = slot(q, k);
        if (s->used && !s->in_flight) {
            s->in_flight = true;
            s->sent_us = now_us;
            q->in_flight++;
            return &s->rec;
        }
    }
    return NULL;
}

bool queue_ack(telemetry_queue_t *q, const char *message_id, ack_status_t status,
               const char *reason) {
    for (uint32_t k = 0; k < q->span; k++) {
        queue_slot_t *s = slot(q, k);
        if (!s->used || strncmp(s->rec.message_id, message_id, REC_UUID_LEN + 1) != 0) {
            continue;
        }
        if (status == ACK_REJECTED) {
            queue_diag_t *d = &q->diag[q->diag_next % QUEUE_DIAG_CAPACITY];
            memset(d, 0, sizeof(*d));
            memcpy(d->message_id, s->rec.message_id, REC_UUID_LEN);
            if (reason != NULL) {
                strncpy(d->reason, reason, QUEUE_REASON_MAX);
            }
            q->diag_next++;
            q->rejected++;
        }
        remove_slot(q, s); // accepted, duplicate, or terminal rejection
        return true;
    }
    return false;
}

void queue_requeue_all(telemetry_queue_t *q) {
    for (uint32_t k = 0; k < q->span; k++) {
        slot(q, k)->in_flight = false;
    }
    q->in_flight = 0;
}

void queue_requeue_stale(telemetry_queue_t *q, int64_t now_us, int64_t timeout_us) {
    for (uint32_t k = 0; k < q->span; k++) {
        queue_slot_t *s = slot(q, k);
        if (s->used && s->in_flight && now_us - s->sent_us >= timeout_us) {
            s->in_flight = false;
            q->in_flight--;
        }
    }
}

uint32_t queue_pending(const telemetry_queue_t *q) {
    return q->count;
}

int64_t queue_oldest_age_s(const telemetry_queue_t *q, uint64_t now_uptime_ms) {
    for (uint32_t k = 0; k < q->span; k++) {
        const queue_slot_t *s = &q->slots[(q->head + k) % QUEUE_CAPACITY];
        if (s->used) {
            return now_uptime_ms > s->rec.uptime_ms
                       ? (int64_t)((now_uptime_ms - s->rec.uptime_ms) / 1000u)
                       : 0;
        }
    }
    return 0;
}

// ---- drain -------------------------------------------------------------------------

uint32_t queue_drain(telemetry_queue_t *q, int64_t now_us, int64_t ack_timeout_us,
                     const queue_drain_ops_t *ops) {
    uint32_t sent = 0;
    for (;;) {
        if (ops->lock != NULL) {
            ops->lock(ops->ctx);
        }
        queue_requeue_stale(q, now_us, ack_timeout_us);
        const measurement_record_t *next = queue_next(q, now_us);
        // Copy out, so the send runs without the lock while producers keep pushing.
        measurement_record_t rec;
        if (next != NULL) {
            rec = *next;
        }
        if (ops->unlock != NULL) {
            ops->unlock(ops->ctx);
        }
        if (next == NULL) {
            return sent;
        }
        const queue_send_result_t r = ops->send(ops->ctx, &rec);
        if (r == QUEUE_SEND_OK) {
            sent++;
            continue;
        }
        if (ops->lock != NULL) {
            ops->lock(ops->ctx);
        }
        if (r == QUEUE_SEND_UNSENDABLE) {
            queue_ack(q, rec.message_id, ACK_REJECTED, "serialize_failed");
        } else {
            queue_requeue_all(q);
        }
        if (ops->unlock != NULL) {
            ops->unlock(ops->ctx);
        }
        if (r == QUEUE_SEND_FAILED) {
            return sent;
        }
    }
}

// ---- ACK parsing -------------------------------------------------------------------

bool queue_parse_ack(const char *json, size_t len, char message_id[REC_UUID_LEN + 1],
                     ack_status_t *status, char reason[QUEUE_REASON_MAX + 1]) {
    char st[16];
    bool reason_null = false;
    if (!json_string_of(json, len, "message_id", message_id, REC_UUID_LEN + 1, NULL) ||
        strlen(message_id) != REC_UUID_LEN ||
        !json_string_of(json, len, "status", st, sizeof st, NULL)) {
        return false;
    }
    if (strcmp(st, "accepted") == 0) {
        *status = ACK_ACCEPTED;
    } else if (strcmp(st, "duplicate") == 0) {
        *status = ACK_DUPLICATE;
    } else if (strcmp(st, "rejected") == 0) {
        *status = ACK_REJECTED;
    } else {
        return false;
    }
    if (!json_string_of(json, len, "reason_code", reason, QUEUE_REASON_MAX + 1, &reason_null)) {
        reason[0] = '\0';
    }
    return true;
}
