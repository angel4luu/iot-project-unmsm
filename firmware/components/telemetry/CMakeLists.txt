idf_component_register(SRCS "clock.c" "provisioning.c" "provisioning_console.c"
                       INCLUDE_DIRS "include"
                       REQUIRES persistence
                       PRIV_REQUIRES esp_driver_uart vfs)
