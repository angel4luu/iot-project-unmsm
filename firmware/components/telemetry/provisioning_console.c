#include "provisioning_console.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "driver/uart.h"
#include "driver/uart_vfs.h"
#include "esp_log.h"
#include "provisioning.h"

static const char *TAG = "provisioning";
// One `set` line carries at most a hex-encoded PEM: 2 * 4096 + key and command.
#define PROV_LINE_MAX (2 * PROV_PEM_MAX + 32)

void provisioning_console_run(const nvs_port_t *nvs) {
    // Blocking stdin on the UART console (the DevKitC-1 USB-to-UART port).
    ESP_ERROR_CHECK(
        uart_driver_install(CONFIG_ESP_CONSOLE_UART_NUM, 2 * PROV_LINE_MAX, 0, 0, NULL, 0));
    uart_vfs_dev_use_driver(CONFIG_ESP_CONSOLE_UART_NUM);
    setvbuf(stdin, NULL, _IONBF, 0);

    prov_session_t *session = calloc(1, sizeof *session);
    char *line = malloc(PROV_LINE_MAX + 2);
    if (session == NULL || line == NULL) {
        ESP_LOGE(TAG, "out of memory");
        abort();
    }
    prov_session_init(session, nvs);
    ESP_LOGW(TAG, "not provisioned; waiting for scripts/provision-node.py");
    char reply[PROV_REPLY_MAX];
    bool done = false;
    while (!done) {
        if (fgets(line, PROV_LINE_MAX + 2, stdin) == NULL) {
            continue;
        }
        line[strcspn(line, "\r\n")] = '\0';
        prov_handle_line(session, line, reply, sizeof reply);
        printf("PROV %s\n", reply); // prefix lets the script ignore log lines
        fflush(stdout);
        done = strcmp(line, "commit") == 0 && strcmp(reply, "ok") == 0;
    }
    memset(line, 0, PROV_LINE_MAX + 2);
    free(line);
    prov_session_wipe(session);
    free(session);
    uart_vfs_dev_use_nonblocking(CONFIG_ESP_CONSOLE_UART_NUM);
    uart_driver_delete(CONFIG_ESP_CONSOLE_UART_NUM);
}
