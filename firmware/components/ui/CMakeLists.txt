idf_component_register(SRCS "ui_state.c" "ui.c" "font5x7.c"
                       INCLUDE_DIRS "include"
                       REQUIRES telemetry quality
                       PRIV_REQUIRES esp_driver_gpio esp_driver_i2c)
