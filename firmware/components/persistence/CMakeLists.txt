idf_component_register(SRCS "nvs_port_esp.c" "checkpoint.c"
                       INCLUDE_DIRS "include"
                       REQUIRES nvs_flash nvs_sec_provider metering
                       PRIV_REQUIRES calibration)
