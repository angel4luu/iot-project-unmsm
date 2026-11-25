// MQTT 5 over mutual TLS (T049; plan › Telemetry, Delivery, and Clock Design).
//
// Client ID = node ID, Clean Start false, 24 h session expiry, 15 s keepalive,
// retained `offline` status as last will. Measurements go out QoS 1 with a 24 h
// message expiry, oldest first, at most 10 in flight (queue.h); the record is
// removed only when the server's application ACK says accepted or duplicate.
// Status is retained and published on connect and every 30 s. All payloads are
// built by serialize.c.
//
// The broker certificate is verified against the provisioned CA with the expected
// name "mosquitto" (its SAN), so the node may reach the broker by LAN address.
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "provisioning.h"
#include "queue.h"
#include "record.h"

#define TELEMETRY_BROKER_NAME "mosquitto"
#define TELEMETRY_KEEPALIVE_S 15
#define TELEMETRY_SESSION_EXPIRY_S (24 * 3600)
#define TELEMETRY_MESSAGE_EXPIRY_S (24 * 3600)
#define TELEMETRY_STATUS_EVERY_US (30LL * 1000000LL)
#define TELEMETRY_ACK_TIMEOUT_US (30LL * 1000000LL)

typedef struct {
    const prov_config_t *prov;
    const node_identity_t *id;
    telemetry_queue_t *queue;
    SemaphoreHandle_t queue_lock;
    const char *last_will_json; // serialized offline status (retained)
} telemetry_mqtt_cfg_t;

bool telemetry_mqtt_start(const telemetry_mqtt_cfg_t *cfg);
bool telemetry_mqtt_connected(void);
// Publishes what the queue allows now; call every ~100 ms from the telemetry task.
void telemetry_mqtt_pump(int64_t now_us);
// Retained status; false when not connected or the publish failed.
bool telemetry_mqtt_publish_status(const char *json, size_t len);
// Set when a connect happened since the last call (to publish status at once).
bool telemetry_mqtt_take_connected_edge(void);
