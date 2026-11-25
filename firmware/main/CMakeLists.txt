idf_component_register(SRCS "main.c"
                       INCLUDE_DIRS "."
                       REQUIRES persistence telemetry acquisition calibration metering quality ui
                                esp_wifi esp_netif esp_timer esp_event esp_driver_uart vfs)
