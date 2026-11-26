idf_component_register(SRCS "clock.c" "provisioning.c" "provisioning_console.c"
                            "serialize.c" "queue.c" "json_scan.c" "event_queue.c" "telemetry_mqtt.c"
                       INCLUDE_DIRS "include"
                       REQUIRES persistence quality freertos
                       PRIV_REQUIRES esp_driver_uart vfs mqtt)
