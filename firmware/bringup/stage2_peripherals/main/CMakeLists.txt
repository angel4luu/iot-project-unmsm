idf_component_register(SRCS "main.c" "font5x7.c"
                       INCLUDE_DIRS "../../../main" "."
                       REQUIRES esp_driver_i2c esp_driver_gpio)
