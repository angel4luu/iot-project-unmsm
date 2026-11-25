# Host (PC) test build of the hardware-free firmware logic (T032, plan › Test Strategy).
# Unity comes from ESP-IDF; hardware sits behind components/*/include/*_port.h with
# fakes in fakes/. AddressSanitizer and UndefinedBehaviorSanitizer are always on.
cmake_minimum_required(VERSION 3.16)
project(energy_node_host_tests C)

set(CMAKE_C_STANDARD 17)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_C_EXTENSIONS ON)

if(NOT DEFINED ENV{IDF_PATH})
  message(FATAL_ERROR "IDF_PATH is not set (ESP-IDF 5.4 provides Unity); see Makefile")
endif()
set(UNITY_DIR "$ENV{IDF_PATH}/components/unity/unity/src")
if(NOT EXISTS "${UNITY_DIR}/unity.c")
  message(FATAL_ERROR "Unity not found in ${UNITY_DIR}")
endif()

get_filename_component(FW_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../.." ABSOLUTE)
get_filename_component(REPO_DIR "${FW_DIR}/.." ABSOLUTE)
set(COMPONENTS "${FW_DIR}/components")

set(SANITIZE -fsanitize=address,undefined -fno-sanitize-recover=all -fno-omit-frame-pointer)
add_compile_options(-Wall -Wextra -Werror -Wshadow -Wconversion -Wno-sign-conversion -g -O1
                    ${SANITIZE})
add_link_options(${SANITIZE})

add_library(unity STATIC "${UNITY_DIR}/unity.c")
target_include_directories(unity PUBLIC "${UNITY_DIR}")
target_compile_definitions(unity PUBLIC UNITY_INCLUDE_DOUBLE UNITY_SUPPORT_64)
target_compile_options(unity PRIVATE -Wno-conversion -Wno-shadow)

# Hardware-free firmware sources compiled exactly as on the target.
add_library(firmware_logic STATIC
  "${COMPONENTS}/telemetry/clock.c"
  "${COMPONENTS}/telemetry/provisioning.c"
  "${COMPONENTS}/calibration/calibration.c"
  "${COMPONENTS}/metering/metering.c"
  "${COMPONENTS}/quality/quality.c"
  "${COMPONENTS}/acquisition/acquisition.c"
  "${COMPONENTS}/persistence/checkpoint.c"
  "${COMPONENTS}/telemetry/serialize.c"
  "${COMPONENTS}/telemetry/queue.c"
  "${COMPONENTS}/ui/ui_state.c"
)
target_include_directories(firmware_logic PUBLIC
  "${COMPONENTS}/acquisition/include"
  "${COMPONENTS}/calibration/include"
  "${COMPONENTS}/metering/include"
  "${COMPONENTS}/quality/include"
  "${COMPONENTS}/persistence/include"
  "${COMPONENTS}/telemetry/include"
  "${COMPONENTS}/ui/include"
  "${FW_DIR}/main"
)

add_library(host_support STATIC fakes/fake_nvs.c fakes/fake_adc.c fixtures.c)
target_include_directories(host_support PUBLIC "${CMAKE_CURRENT_SOURCE_DIR}" fakes)
target_link_libraries(host_support PUBLIC firmware_logic unity m)
target_link_libraries(firmware_logic PUBLIC m)
target_compile_definitions(host_support PRIVATE
  FIXTURES_DIR="${REPO_DIR}/tests/fixtures/waveforms")

enable_testing()
foreach(t test_clock test_provisioning test_fixtures test_board test_metering
          test_quality test_energy test_calibration test_acquisition test_serialize
          test_queue test_queue_drain test_ui_state)
  add_executable(${t} ${t}.c)
  target_link_libraries(${t} PRIVATE host_support)
  add_test(NAME ${t} COMMAND ${t})
endforeach()

target_compile_definitions(test_serialize PRIVATE
  TELEMETRY_OUT="${REPO_DIR}/tests/fixtures/telemetry")
