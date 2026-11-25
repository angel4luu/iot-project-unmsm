idf_component_register(SRCS "main.c"
                       INCLUDE_DIRS "../../../main"
                       REQUIRES persistence telemetry esp_wifi esp_netif esp_event esp_driver_gpio)
