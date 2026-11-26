idf_component_register(SRCS "threshold.c" "config.c"
                       INCLUDE_DIRS "include"
                       REQUIRES telemetry persistence calibration metering quality)
