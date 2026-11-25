// Target glue: runs the provisioning protocol (provisioning.h) on the USB console.
#pragma once

#include "nvs_port.h"

// Blocks reading command lines from the console until a successful commit.
void provisioning_console_run(const nvs_port_t *nvs);
