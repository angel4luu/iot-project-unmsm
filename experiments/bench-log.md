# Bench log (hardware integration)

A dated record of every hardware and integration step, written as it happens. It is
the source for the article's implementation and results sections: the article may
only state what this log (and the preserved evidence it points to) shows.

Rules:

- One entry per session or milestone attempt, newest at the bottom. Record failures
  and fixes too, not only passes.
- Write measured values exactly as read, with units, and mark anything uncertain.
- Values are **not validated** (no reference instrument); never write accuracy
  claims here.
- Never record secrets: no Wi-Fi name or password, no IP addresses, tokens, or ntfy
  topic. Write "phone hotspot" or "lab Wi-Fi" instead.
- Raw captures (CSV dumps, serial logs, photos) go under `experiments/data/bench/`
  (git-ignored); manifests under `experiments/manifests/`. Link them by file name.
- Plan and pass criteria: `hardware/integration-roadmap.md` (M1–M9) and
  `hardware/build-guide.md`.

## Setup (fill in once, update when something changes)

| Item | Value |
|---|---|
| Controller | ESP32-S3 N16R8 dev board (ESP32-S3-WROOM-1-N16R8 module; DevKitC-1-compatible pinout, CH343 bridge, USB-C ports COM and USB) mounted directly on the breadboard (the kit's GPIO extension board is not used); chip ESP32-S3 (QFN56) rev v0.2, 8 MB PSRAM, 16 MB flash (esptool and bootloader report). IO35–37 reserved by the octal PSRAM |
| USB-serial chip | WCH CH343 (`1a86:55d3`, "USB Single Serial"), Linux driver `cdc_acm`, port `/dev/ttyACM0` |
| Breadboard | one standard 830-point |
| Pin change | RGB blue moved from GPIO21 to GPIO15 on 2026-11-26 (right header has no free hole on the breadboard); firmware, plan, build guide and article figure updated |
| PC | Linux, ESP-IDF v5.4.4 |
| Network | phone hotspot (2.4 GHz, "Maximize Compatibility" on); private /28 subnet, address changes between sessions |
| Server stack | Docker Compose from this repository |
| Firmware commit | (record per entry) |
| Operator(s) | (record per entry) |

## Progress

| Milestone | Status | Date | Entry |
|---|---|---|---|
| M1 board alone | PASS | 2026-11-26 | [E-001](#e-001-2026-11-26-m1-first-connection) |
| M2 screen, buzzer, LED | PARTIAL: LED PASS; no OLED; buzzer faulty, pending replacement | 2026-11-27 | [E-002](#e-002-2026-11-27-m2-lite-buzzer-and-led) |
| M3 voltage channel | in progress (M3-lite): circuit OK, board contact intermittent | 2026-11-27 | [E-003](#e-003-2026-11-27-m3-lite-voltage-channel-at-rest) |
| M4 current channel | FAIL (debugging): ACS712 output does not reach GPIO5 | 2026-11-27 | [E-005](#e-005-2026-11-27-m4-current-channel-at-rest) |
| M5 full firmware on bench | PARTIAL (M5-lite): firmware runs as expected; current reading wrong until M4 passes | 2026-11-27 | [E-004](#e-004-2026-11-27-m5-lite-full-firmware-on-the-bench) |
| M6 node to server | not started | | |
| M7 bulb loop check | not started | | |
| M8 calibration, E1, E2 | not started | | |
| M9 E3, E4, final end-to-end | not started | | |

## Entry template

```
### E-NNN YYYY-MM-DD: <milestone> <short title>

- Operator(s):
- Firmware/repo commit:
- What was connected (holes, jumpers, parts):
- Commands run:
- Expected:
- Observed (exact values, messages):
- Result: PASS / FAIL / PARTIAL
- Problems and fixes:
- Evidence files:
- Notes for the article:
```

## Entries

### E-001 2026-11-26: M1 first connection

- Operator(s): (fill in)
- Firmware/repo commit: 54a8c95 plus uncommitted integration-guide changes
- What was connected: dev board on its GPIO extension board, nothing else; USB-C
  cable from the board's UART/COM port to the PC; extension-board DC1 jack empty.
- Commands run: `idf.py -C firmware/bringup/stage1_board -p /dev/ttyUSB0 flash monitor`
- Expected: build, flash, `PASS boot (ESP32-S3, stage 1 bring-up)`.
- Observed:
  1. `zsh: command not found: idf.py`. ESP-IDF had not been loaded in that
     terminal.
  2. The board's red power LED was on, but `ls /dev/ttyUSB* /dev/ttyACM*` printed
     only `no matches found`. In zsh one unmatched pattern aborts the whole command,
     so it never listed the existing port.
  3. The kernel log showed the board: `1a86:55d3` "USB Single Serial" (CH343),
     driver `cdc_acm`, port `/dev/ttyACM0`, not `/dev/ttyUSB0`.
  4. The user account was not in the `dialout` group.
- Result: PASS (M1 complete). Gate 1 PASS: stage 1 flashed and booted, `PASS boot (ESP32-S3,
  stage 1 bring-up)`. The NVS HMAC key was generated and burned into eFuse block 4
  on this first boot (`BURN BLOCK4 - OK`), as planned. Gate 2 PASS: after
  provisioning (`node-001: provisioned (encrypted NVS)`) the node rebooted and
  logged `PASS Wi-Fi joined, IP …` about 1.8 s after boot (WPA2-PSK, 2.4 GHz
  802.11 b/g/n, channel 6, RSSI −35 dBm; distance to the phone not recorded). The
  credentials were read back from encrypted NVS; no provisioning prompt appeared.
  Gate 3 PASS: after unplugging and replugging the USB cable the node rejoined
  Wi-Fi without asking for provisioning (confirmed by the operator).
- Problems and fixes:
  - Load ESP-IDF per terminal: `. $HOME/esp/esp-idf-v5.4.4/export.sh`.
  - Use `-p /dev/ttyACM0` (CH343 board); integration roadmap section 5 updated.
  - `sudo usermod -aG dialout $USER`, then log out and in.
  - Node provisioning manifest created (git-ignored), pointing at the PC's
    current hotspot address.
  - `Path '/dev/ttyACM0' is not readable`: the account had been added to
    `dialout` but the login session predated it; `newgrp dialout` (or log out
    and in) fixes it.
  - Stage 1 build failed: `unknown type name 'esp_mqtt5_connection_property_config_t'`
    in `telemetry_mqtt.c`. Stage 1 links the telemetry component, which uses
    MQTT 5, but `bringup/stage1_board/sdkconfig.defaults` did not enable it. Added
    `CONFIG_MQTT_PROTOCOL_5=y` and TLS 1.2 there, regenerated the app's
    `sdkconfig`. `make firmware-build-bringup` had hidden the failure (its loop
    did not stop on a failed build); it now exits with an error. All three
    bring-up apps build.
  - First provisioning attempt: `node refused set node_id <8 bytes>: err
    unknown_command`. Keys typed in the serial monitor without Enter stayed in
    the node's input line and corrupted the first command (the monitor log shows
    four earlier `PROV err unknown_command` replies). `provision-node.py` now sends
    a newline and `abort` first and waits for `PROV ok` (`sync`, two new unit
    tests).
- Evidence files: none yet.
- Notes for the article: the node's USB-serial bridge is a CH343 (CDC-ACM class),
  which needs no extra driver on Linux. Flashing at 460800 baud took about 11 s
  for the 0.77 MB stage 1 image. The encrypted-NVS key is created on the node at
  first boot (eFuse HMAC), so Wi-Fi credentials are never stored in clear on the
  board.

### E-002 2026-11-27: M2-lite buzzer and LED

- Operator(s): (fill in)
- Firmware/repo commit: 54a8c95 plus uncommitted integration-guide changes
- What was connected: board on the breadboard (left header in row i, row j free);
  rail jumpers j22 → top + (3V3), j1 → top − (GND), j2 → bottom + (5V), GND
  bridge; buzzer stage (1 kΩ d42–d46, 2N2222 b45–b47, buzzer e50/e53, jumper
  j14 → e42); RGB LED b32–b35 with 470 Ω resistors, jumpers j13 → e28,
  j12 → e38, j15 → e39, a33 → bottom −. OLED not fitted (reduced-kit roadmap).
  No AC adapter.
- Commands run: `idf.py -C firmware/bringup/stage2_peripherals -p /dev/ttyACM0
  flash monitor`; later `idf.py -C firmware/bringup/stage1_board … flash monitor`.
- Expected: `FAIL no OLED` (no screen), one 200 ms beep, LED red/green/blue once
  per second.
- Observed:
  1. First flash attempt: `Path '/dev/ttyACM0' is not readable` (new terminal
     without the `dialout` group); `newgrp dialout` fixed it.
  2. Stage 2 flashed and ran: about 4 s of `i2c.master … probe device timeout`
     messages, then `FAIL no OLED at 0x3C/0x3D` (expected with no screen),
     `buzzer beeped 200 ms`, then `LED red/green/blue on` once per second.
  3. No beep was heard and the RGB LED stayed dark in every colour.
  4. Stage 1 (different program, same LED pins) also logged the LED cycle; the LED
     stayed dark, so the firmware is ruled out.
  5. Direct LED test, LED powered from the top rails next to the board's power
     jumpers (no GPIO): dark. Same with the polarity reversed (common-anode test):
     dark.
  6. Stage 1 rejoined the phone hotspot once the hotspot was on (`PASS Wi-Fi
     joined`, WPA2-PSK, 802.11 b/g/n, channel 3, RSSI −17 dBm); earlier runs had
     logged `Wi-Fi disconnected; retrying` while the hotspot was off.
  7. Photos showed the LED body over lines 34–35, so its legs were probably one
     line off (no leg in line 32, where the red resistor ends) and not fully
     pushed in. LED tested alone in an empty area (legs f25–f28, longest in f26;
     470 Ω from j25 to the top + rail; j26 to the top − rail): **red lit**. The LED
     works and is common-cathode, leg order R, common, G, B, as planned.
     Green and blue also lit (resistor moved to j27, j28). The original red-channel
     470 Ω, tested in the same spot, also lit red, so the resistor was fine: the
     fault was the LED's placement on the breadboard.
  8. LED rebuilt in b32–b35 (longest leg b33, legs pushed fully in): red and green
     followed the stage 2 cycle; blue stayed dark until its path (j15 → e39,
     470 Ω c35–c39, blue leg b35) was re-seated. Then all three colours followed
     the `LED <colour> on` lines. LED part of the gate: PASS.
  9. Buzzer: no beep heard in the circuit. Tested alone in the empty top half
     (− f27, + f30, j27 → top − rail, 5V taken straight from the board's 5V pin
     column j2 into j30): silent, and silent again with the legs swapped. Black
     sealed (active-type) buzzer. Conclusion: the buzzer appears faulty. It stays
     fitted in e50/e53 with its transistor stage, ready for a replacement
     (reduced-kit roadmap, add-on C).
     **Not confirmed:** the M3-lite session (E-003) later showed the board's
     GND pin (column 1) contacting only when pressed. The buzzer test took 5V and
     GND from the board's pins in columns 2 and 1, so it must be repeated after
     the board is re-seated before the buzzer is declared faulty.
- Result: PARTIAL. RGB LED PASS (all three colours follow the program). OLED not
  fitted (expected `FAIL no OLED`). Buzzer pending replacement: its result does not
  count until a new buzzer passes add-on C.
- Problems and fixes: LED legs were one line off and not pushed fully in;
  re-seated in b32–b35 (and the blue path re-seated). Buzzer: replace the part.
  Checks used along the way: resistor colour code (470 Ω is
  yellow-violet-brown), LED powered straight from the board's 3V3/GND pin columns
  (j22/j1, rail jumpers removed for the test; h1/h22 are covered by the board) to bypass the rails, board orientation (column 22 pin labelled 3V3),
  part positions, rail gap in the middle of the breadboard.
- Evidence files: none yet.
- Notes for the article: none yet.

### E-003 2026-11-27: M3-lite voltage channel at rest

- Operator(s): (fill in)
- Firmware/repo commit: 54a8c95 plus uncommitted integration-guide changes
- What was connected: voltage channel in the top half, lines 25–40 (3V3 tap j25,
  GND tap j31, 10 kΩ h25–h28 and g28–g31, 10 µF + f28 / − f31, R2 4.7 kΩ
  i28–i34, R1 100 kΩ g34–g40 with its line-40 end unconnected, 22 nF h31–h34,
  jumper j34 → j19). No adapter, no jack jumpers. GPIO5 not connected (M4 not
  built).
- Commands run: `idf.py -C firmware/bringup/stage34_adc_logger -p /dev/ttyACM0
  flash monitor`, later `… monitor`.
- Expected: GPIO4 mean about 1650 mV (1550–1750), min ≈ max.
- Observed:
  1. First 10 s: GPIO4 mean 1587 mV, min 1582, max 1593 mV, 0 overruns, about
     4000 pairs/s. Then the mean drifted to 1324–1489 mV with 100–300 mV spread.
  2. After the parts were pushed in again: GPIO4 3146 mV flat (ADC top), as if
     the divider had lost ground.
  3. Press test on the board's USB end, monitor running: 3146 mV unpressed; about
     0 mV for a few seconds; **1622 mV, min 1613, max 1627 mV, stable** while the
     board was pressed down; drifting 1400–1500 mV after release.
  4. GPIO5 (unconnected) wandered 0–1800 mV, as expected for a floating input.
- Result: PARTIAL. The voltage-channel circuit is correct (1622 mV, flat, when the
  board makes contact). The board's power pins at the USB end (GND, column 1;
  5V, column 2) contact the breadboard only when pressed. Gate not passed until the
  board is re-seated and the reading is stable hands-off; CSV dump not yet saved.
- Problems and fixes: re-seat the board (pending).
- Evidence files: none yet.
- Notes for the article: none yet (bench integration issue, not a result).

### E-004 2026-11-27: M5-lite full firmware on the bench

- Operator(s): (fill in)
- Firmware/repo commit: 54a8c95-dirty (app version in the boot log)
- What was connected: M2-lite, M3-lite and M4 circuits; no OLED, no adapter, no
  jack jumpers; buzzer marked faulty (E-002). USB only.
- Commands run: `make firmware-build`, `idf.py -C firmware -p /dev/ttyACM0 flash
  monitor`, then `… monitor` and `cal status` typed inside the monitor.
- Expected: roadmap (reduced kit) › Test gate M5-lite.
- Observed:
  1. Boot log: `no accepted calibration: windows flagged calibration_missing`,
     `no threshold config yet`, `no OLED at 0x3C/0x3D; LED and buzzer only`.
  2. Wi-Fi joined the phone hotspot (WPA2-PSK, b/g/n, channel 6, RSSI −46 dBm).
  3. MQTT: `Host is unreachable` before Wi-Fi was up, then `Connection reset by
     peer` and `disconnected; queueing` about every 8 s. Expected: the server is
     not opened to the Wi-Fi until M6 (the PC was also on another network, and the
     broker listens only on the PC itself).
  4. `cal status`: `revision=none kind=nominal sign=1 zero_mv=1700.68
     noise_a=0.0500 last_p_w=0.106 last_i_a=0.3094 quality=invalid`.
  5. The USB serial port disappeared several times (kernel: `device descriptor
     read/64, error -71`, `device not accepting address`); it came back after
     re-plugging the cable and taking the weight off the board.
- Result: PARTIAL. Firmware boot, degraded-mode handling, calibration state and
  offline queueing behave as specified. `last_i_a` 0.31 A at no current is far
  above the 0.05 A noise level: traced to M4 (E-005). LED state not yet recorded.
- Problems and fixes: the roadmap's M5-lite gate asked for per-measurement console
  lines the firmware does not print; gate rewritten to use `cal status`. Do not
  press or weigh down the USB connector.
- Evidence files: none (console only).
- Notes for the article: none yet.

### E-005 2026-11-27: M4 current channel at rest

- Operator(s): (fill in)
- Firmware/repo commit: 54a8c95-dirty
- What was connected: ACS712-20A module (VCC → bottom + rail, GND → bottom − rail,
  OUT → e56), R3 4.7 kΩ d56–d60, R4 10 kΩ c60–c63, 22 nF b60–b63, a63 → bottom −
  rail, jumper e60 → j18 (GPIO5). No loop current.
- Commands run: `idf.py -C firmware/bringup/stage34_adc_logger -p /dev/ttyACM0
  flash monitor`.
- Expected: GPIO5 about 1700 mV (ACS712 zero of about 2500 mV × R4/(R3+R4)), small
  spread; GPIO4 about 1650 mV.
- Observed:
  1. Hands-off: GPIO4 mean 1657–1771 mV, drifting; GPIO5 mean 25–255 mV, spread up
     to about 230 mV.
  2. Board pressed down at the USB end: GPIO4 **1627–1636 mV, flat**; GPIO5
     **exactly 0 mV** (min 0, max 0). When contact was lost, both channels read
     3146 mV (ADC top).
  3. GPIO5 never came near 1700 mV in any state.
- Result: FAIL. With a solid ground, GPIO5 is held at 0 by R4, so the ACS712
  output does not reach the divider: either the module has no 5 V (bottom + rail
  fed from the board's 5V pin at line 2; a split rail between line 2 and line 56
  is the main suspect) or the OUT → e56 → R3 path is open.
- Problems and fixes (pending): check the module's power LED; check 5 V at line
  56 (LED + 470 Ω test) and bridge the rail halves if split; then check OUT,
  R3, e60 → j18 and R4. Re-seat the board (also pending from E-003).
- Evidence files: none yet.
- Notes for the article: none yet (bench integration issue, not a result).
