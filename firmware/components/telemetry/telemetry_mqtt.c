#include "telemetry_mqtt.h"

#include <stdatomic.h>
#include <stdio.h>
#include <string.h>

#include "esp_log.h"
#include "mqtt_client.h"
#include "serialize.h"

#define TOPIC_PREFIX "unmsm/energy/v1/nodes/"
#define TOPIC_MAX 96

static const char *TAG = "mqtt";

static esp_mqtt_client_handle_t s_client;
static telemetry_mqtt_cfg_t s_cfg;
static atomic_bool s_connected;
static atomic_bool s_connected_edge;
static char s_uri[PROV_HOST_MAX + 32];
static char s_topic_meas[TOPIC_MAX], s_topic_status[TOPIC_MAX], s_topic_acks[TOPIC_MAX];
static char s_topic_events[TOPIC_MAX], s_topic_config[TOPIC_MAX];
static char s_payload[SERIALIZE_MEASUREMENT_MAX];
static char s_event_payload[SERIALIZE_EVENT_MAX];

static void lock(void) {
    xSemaphoreTake(s_cfg.queue_lock, portMAX_DELAY);
}

static void unlock(void) {
    xSemaphoreGive(s_cfg.queue_lock);
}

static void on_ack(const char *data, int len) {
    char id[REC_UUID_LEN + 1], reason[QUEUE_REASON_MAX + 1];
    ack_status_t st;
    if (len <= 0 || !queue_parse_ack(data, (size_t)len, id, &st, reason)) {
        ESP_LOGW(TAG, "unreadable ACK ignored");
        return;
    }
    lock();
    queue_ack(s_cfg.queue, id, st, reason);
    unlock();
    if (st == ACK_REJECTED) {
        ESP_LOGW(TAG, "measurement rejected by server: %s", reason);
    }
}

static bool topic_is(esp_mqtt_event_handle_t e, const char *topic) {
    return e->topic_len == (int)strlen(topic) &&
           strncmp(e->topic, topic, (size_t)e->topic_len) == 0;
}

static void on_event(void *arg, esp_event_base_t base, int32_t id, void *data) {
    (void)arg;
    (void)base;
    esp_mqtt_event_handle_t e = data;
    switch ((esp_mqtt_event_id_t)id) {
    case MQTT_EVENT_CONNECTED:
        esp_mqtt_client_subscribe(s_client, s_topic_acks, 1);
        esp_mqtt_client_subscribe(s_client, s_topic_config, 1); // retained: delivered at once
        atomic_store(&s_connected, true);
        atomic_store(&s_connected_edge, true);
        lock();
        queue_requeue_all(s_cfg.queue); // resend what had no ACK yet (dedup on server)
        if (s_cfg.events != NULL) {
            evq_requeue_all(s_cfg.events); // events without PUBACK (dedup on event_id)
        }
        unlock();
        ESP_LOGI(TAG, "connected (session present: %d)", e->session_present);
        break;
    case MQTT_EVENT_DISCONNECTED:
        atomic_store(&s_connected, false);
        ESP_LOGW(TAG, "disconnected; queueing");
        break;
    case MQTT_EVENT_PUBLISHED:
        if (s_cfg.events != NULL) {
            lock();
            evq_puback(s_cfg.events, e->msg_id);
            unlock();
        }
        break;
    case MQTT_EVENT_DATA:
        // ACKs and the config are small; a fragmented message is neither.
        if (e->current_data_offset != 0 || e->data_len != e->total_data_len) {
            break;
        }
        if (topic_is(e, s_topic_acks)) {
            on_ack(e->data, e->data_len);
        } else if (topic_is(e, s_topic_config) && s_cfg.on_config != NULL && e->data_len > 0) {
            s_cfg.on_config(e->data, (size_t)e->data_len);
        }
        break;
    case MQTT_EVENT_ERROR:
        ESP_LOGW(TAG, "MQTT error");
        break;
    default:
        break;
    }
}

bool telemetry_mqtt_start(const telemetry_mqtt_cfg_t *cfg) {
    s_cfg = *cfg;
    const char *node = cfg->prov->node_id;
    snprintf(s_topic_meas, sizeof s_topic_meas, TOPIC_PREFIX "%s/measurements", node);
    snprintf(s_topic_status, sizeof s_topic_status, TOPIC_PREFIX "%s/status", node);
    snprintf(s_topic_acks, sizeof s_topic_acks, TOPIC_PREFIX "%s/acks/measurements", node);
    snprintf(s_topic_events, sizeof s_topic_events, TOPIC_PREFIX "%s/events", node);
    snprintf(s_topic_config, sizeof s_topic_config, TOPIC_PREFIX "%s/config", node);
    snprintf(s_uri, sizeof s_uri, "mqtts://%s:%s", cfg->prov->mqtt_host, cfg->prov->mqtt_port);

    esp_mqtt_client_config_t mc = {
        .broker.address.uri = s_uri,
        .broker.verification.certificate = cfg->prov->ca_cert,
        .broker.verification.common_name = TELEMETRY_BROKER_NAME,
        .credentials.client_id = node,
        .credentials.authentication.certificate = cfg->prov->node_cert,
        .credentials.authentication.key = cfg->prov->node_key,
        .session.protocol_ver = MQTT_PROTOCOL_V_5,
        .session.keepalive = TELEMETRY_KEEPALIVE_S,
        .session.disable_clean_session = true,
        .session.last_will.topic = s_topic_status,
        .session.last_will.msg = cfg->last_will_json,
        .session.last_will.msg_len = (int)strlen(cfg->last_will_json),
        .session.last_will.qos = 1,
        .session.last_will.retain = 1,
        .network.reconnect_timeout_ms = 5000,
    };
    s_client = esp_mqtt_client_init(&mc);
    if (s_client == NULL) {
        return false;
    }
    esp_mqtt5_connection_property_config_t cp = {
        .session_expiry_interval = TELEMETRY_SESSION_EXPIRY_S,
    };
    esp_mqtt5_client_set_connect_property(s_client, &cp);
    esp_mqtt_client_register_event(s_client, ESP_EVENT_ANY_ID, on_event, NULL);
    return esp_mqtt_client_start(s_client) == ESP_OK;
}

bool telemetry_mqtt_connected(void) {
    return atomic_load(&s_connected);
}

bool telemetry_mqtt_take_connected_edge(void) {
    return atomic_exchange(&s_connected_edge, false);
}

static int publish(const char *topic, const char *payload, size_t len, bool retain, bool expiry) {
    if (expiry) {
        esp_mqtt5_publish_property_config_t pp = {
            .message_expiry_interval = TELEMETRY_MESSAGE_EXPIRY_S,
        };
        esp_mqtt5_client_set_publish_property(s_client, &pp);
    }
    return esp_mqtt_client_publish(s_client, topic, payload, (int)len, 1, retain ? 1 : 0);
}

static void drain_lock(void *ctx) {
    (void)ctx;
    lock();
}

static void drain_unlock(void *ctx) {
    (void)ctx;
    unlock();
}

static queue_send_result_t drain_send(void *ctx, const measurement_record_t *rec) {
    (void)ctx;
    const size_t n = serialize_measurement(s_cfg.id, rec, s_payload, sizeof s_payload);
    if (n == 0) {
        return QUEUE_SEND_UNSENDABLE;
    }
    return publish(s_topic_meas, s_payload, n, false, true) < 0 ? QUEUE_SEND_FAILED : QUEUE_SEND_OK;
}

// Sends every event not yet in flight. The lock is never held across a publish: the
// MQTT task takes it in its PUBLISHED handler while holding the client lock.
static void pump_events(int64_t now_us) {
    if (s_cfg.events == NULL) {
        return;
    }
    for (;;) {
        event_record_t ev;
        char reason[EVQ_REASON_MAX + 1];
        lock();
        evq_requeue_stale(s_cfg.events, now_us, TELEMETRY_ACK_TIMEOUT_US);
        const int idx = evq_next(s_cfg.events, now_us, &ev, reason);
        unlock();
        if (idx < 0) {
            return;
        }
        const size_t n = serialize_event(s_cfg.id, &ev, s_event_payload, sizeof s_event_payload);
        if (n == 0) {
            lock();
            evq_discard(s_cfg.events, idx);
            unlock();
            ESP_LOGE(TAG, "event does not serialize; dropped");
            continue;
        }
        const int msg_id = publish(s_topic_events, s_event_payload, n, false, true);
        lock();
        evq_sent(s_cfg.events, idx, msg_id);
        unlock();
        if (msg_id < 0) {
            return; // transport down: resend later
        }
    }
}

void telemetry_mqtt_pump(int64_t now_us) {
    if (!telemetry_mqtt_connected()) {
        return;
    }
    static const queue_drain_ops_t ops = {
        .lock = drain_lock, .unlock = drain_unlock, .send = drain_send, .ctx = NULL};
    pump_events(now_us); // first: an alert event never waits behind a measurement backlog
    queue_drain(s_cfg.queue, now_us, TELEMETRY_ACK_TIMEOUT_US, &ops);
}

bool telemetry_mqtt_publish_status(const char *json, size_t len) {
    return telemetry_mqtt_connected() && publish(s_topic_status, json, len, true, false) >= 0;
}
