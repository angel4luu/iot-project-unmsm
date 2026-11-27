# Integration roadmap, reduced kit: no OLED, no AC-AC adapter (from M2)

Use this version while the **OLED screen** and the **12 V AC-AC adapter** have not
arrived. It replaces M2–M6 of the full roadmap
([`integration-roadmap.md`](integration-roadmap.md)) with versions that test every
part you **do** have, and the whole data path on the real node. The parts you lack
are mocked only on the server side, with the existing simulator; the firmware is
not changed.

When a missing part arrives, follow its add-on ([A: OLED](#add-on-a-the-oled),
[B: adapter](#add-on-b-the-ac-ac-adapter),
[C: replacement buzzer](#add-on-c-the-replacement-buzzer)), pass its small gate, and
then finish with the [final real end-to-end test](#final-real-end-to-end-test).

> **Buzzer status (2026-11-27):** the kit's buzzer appears faulty. It stayed
> silent when wired alone straight to the board's 5V and GND, in both
> orientations (bench log E-002). That test took 5V and GND from the board's
> pins in columns 2 and 1, which later proved to contact only when the board was
> pressed (E-003), so **repeat the buzzer-alone test after re-seating the board**
> before buying a new one. It stays wired in its place (e50/e53, with its
> transistor stage) so a new one drops into the same holes. Until it is replaced,
> **no buzzer result counts**: every buzzer check below is marked *pending
> add-on C* and is skipped, not failed.

- Sections 1–5 and M1 of the full roadmap still apply: safety rules, parts, the
  breadboard naming (row **j** at the top, row **a** at the bottom, column 1 on the
  left), the board seating, and the software.
- **Every hole is the same as in the full layout** (Figure 2 of the full roadmap).
  The holes for the missing parts stay **empty and reserved**, so adding a part
  later means plugging it in, never moving other wires.
- All readings are **not validated**. Everything done without the adapter is a
  **rehearsal**: it proves the wiring, firmware and data path, but it is not
  article evidence (the article only uses runs with the bulb loop, M8–M9).

## Contents

1. [What works without the two parts](#what-works-without-the-two-parts)
2. [Reserved holes (leave them empty)](#reserved-holes-leave-them-empty)
3. [M2-lite: buzzer and LED](#m2-lite-buzzer-and-led-stage-2-t028)
4. [M3-lite: voltage channel without the adapter](#m3-lite-voltage-channel-without-the-adapter-stage-3-t029)
5. [M4: current channel](#m4-current-channel-unchanged)
6. [M5-lite: full firmware on the bench](#m5-lite-full-firmware-on-the-bench)
7. [M6-lite: the real node talks to the server](#m6-lite-the-real-node-talks-to-the-server-t062)
8. [Hybrid end-to-end rehearsal](#hybrid-end-to-end-rehearsal-real-node--simulated-node)
9. [Add-on A: the OLED](#add-on-a-the-oled)
10. [Add-on B: the AC-AC adapter](#add-on-b-the-ac-ac-adapter)
11. [Add-on C: the replacement buzzer](#add-on-c-the-replacement-buzzer)
12. [Final real end-to-end test](#final-real-end-to-end-test)
13. [Progress checklist](#progress-checklist-reduced-kit)

---

## What works without the two parts

| Part of the system | Without OLED and adapter | How it is tested here |
|---|---|---|
| RGB LED | Fully | M2-lite (real) |
| Buzzer | Wired, but the part appears faulty: pending replacement | Add-on C (real) |
| Voltage channel circuit | Built and checked at rest (1.65 V bias, no wave) | M3-lite (real) |
| Current channel (ACS712) | Fully at zero current (its normal state until M8) | M4 (real) |
| Main firmware | Runs; logs `OLED not found; LED and buzzer only`; reads about 0 V and 0 A | M5-lite (real) |
| Wi-Fi, MQTT/mTLS, ingestion, databases, Grafana | Fully | M6-lite (real node) |
| Outage recovery (node side and server side) | Fully | M6-lite (real node) |
| Threshold config delivered to the node | Fully (the node accepts and keeps it) | M6-lite (real node) |
| Threshold **excess**, local LED alarm (buzzer after add-on C), remote alert, ntfy | The real node never exceeds a limit (no power) | Hybrid rehearsal: simulated node |
| Power, energy, history on the dashboard | Real node sends 0 W | Hybrid rehearsal: simulated node |
| Calibration, E1–E4 | Need the bulb loop | After add-on B (M7–M9) |

The firmware is **not** changed to fake a waveform: a fake signal on the real node
could end up mistaken for a measurement. The only mock is the existing server-side
simulator, which publishes as a different node (`sim-e2e`), so its data can never
mix with `node-001`.

## Reserved holes (leave them empty)

| Part (missing) | Reserved holes | Filled in |
|---|---|---|
| OLED module | **h45, h46, h47, h48** (and the rest of columns 45–48, rows f–j) | Add-on A |
| OLED jumpers | **j45** (− rail), **j46** (+ rail, 3V3), **j8 → j47** (SCL), **j11 → j48** (SDA) | Add-on A |
| Adapter jumpers on the jack screws | **j28** (screw 2, Vb) and **j40** (screw 1, AC) | Add-on B |
| Bulb loop | nothing on the breadboard (wires go jack → ACS712 IP+/IP− → bulb) | Add-on B, M7 |
| Buzzer (faulty, still fitted) | **e50** (−) and **e53** (+): swap the new buzzer into the same holes | Add-on C |

Holes **j8** and **j11** are the free holes of GPIO9 and GPIO8. Nothing else uses
them, so the OLED's two signal jumpers can go in later without touching anything.

---

## M2-lite: buzzer and LED (stage 2, T028)

**Goal:** the local warning parts you have work. Unplug USB before every change.
The buzzer stage is built now (step 2.2) even though the buzzer appears faulty: the
replacement then only needs swapping in ([add-on C](#add-on-c-the-replacement-buzzer)).

1. **Step 2.0, board and rails:** exactly as in the full roadmap,
   [M2 step 2.0](integration-roadmap.md#step-20-board-and-rails).
2. **Skip step 2.1 (OLED).** Leave its reserved holes empty.
3. **Step 2.2, buzzer:** exactly as in the full roadmap,
   [step 2.2](integration-roadmap.md#step-22-buzzer-through-the-transistor-gpio16-bottom-half-columns-4253).
4. **Step 2.3, RGB LED:** exactly as in the full roadmap,
   [step 2.3](integration-roadmap.md#step-23-rgb-led-gpio17--18--15-bottom-half-columns-2839)
   (blue on **j15**, GPIO15).

### Flash and test

```
. $HOME/esp/esp-idf-v5.4.4/export.sh
idf.py -C firmware/bringup/stage2_peripherals -p /dev/ttyACM0 flash monitor
```

If the LED stays dark or the buzzer is silent, test the part **alone, without the
ESP32 program**, in the empty top half (USB unplugged for every change; rows f
next to the centre gap and j next to the top rails are easy to find):

- **LED:** legs in **f25–f28**, longest leg in **f26**; a 470 Ω from **j25** to
  the top + rail; a jumper from **j26** to the top − rail. Red should light; move
  the resistor's end to j27 (green) and j28 (blue).
- **Buzzer:** − leg in **f27**, + leg in **f30**; a jumper from **j27** to the
  top − rail; move the **rail end** of the 5V jumper (j2) into **j30**. An active
  buzzer gives a continuous tone. Silent both ways round: the buzzer is faulty.
- If the part works alone, the fault was its position in the circuit: one line
  off, or legs not pushed fully in (the cause of the LED fault on 2026-11-27).
- Also check the resistor bands (470 Ω = yellow, violet, brown) and that the pin in
  column 22 is labelled 3V3. Put every borrowed jumper back afterwards.

### Test gate M2-lite

- [ ] The monitor prints about 4 s of `i2c.master … probe device timeout` errors,
      then `FAIL no OLED at 0x3C/0x3D …`. **Both are expected** with no screen
      (the program is searching for it); it carries on.
- [ ] The log lines `buzzer beeped` and `LED … on` only show the program **sent**
      the signals. The gate is what you **hear and see** on the breadboard.
- [ ] *Pending add-on C (buzzer faulty):* the buzzer beeps once for 200 ms and is
      silent otherwise. Skip this box until the buzzer is replaced.
- [ ] The LED shows red, green, blue one at a time, matching the
      `LED <colour> on` lines. If nothing lights, your LED may be common anode:
      stop and tell the team.
- [ ] Write the result in `experiments/bench-log.md` (new entry; say "OLED not
      fitted, buzzer pending replacement").

M2-lite counts as passed when the LED box passes; the buzzer box moves to add-on C.

---

## M3-lite: voltage channel without the adapter (stage 3, T029)

**Goal:** the whole voltage-channel circuit is built and GPIO4 sits at the 1.65 V
middle point. With no adapter there is no wave: that is exactly the first check of
the full M3 gate.

### Steps

Do steps 1–6 of the full roadmap's
[M3 steps](integration-roadmap.md#steps-adapter-unplugged-from-the-wall-the-whole-time):
taps, Vb divider, 10 µF (stripe on the column 31 side), R2, R1, 22 nF, and the
jumper **j34 → j19** (A to GPIO4).

- **Skip step 7** (jumpers to the jack screws). Leave **j28** and **j40** empty.
  If you already have the jack, you may screw it to nothing yet; it does not
  matter.
- R1's free end in **g40** is not connected to anything for now. That is safe:
  point A still sits at Vb through R2.
- Do the power-on check (full roadmap, section 4).

### Flash and test

```
idf.py -C firmware/bringup/stage34_adc_logger -p /dev/ttyACM0 flash monitor
```

It prints the mean, minimum and maximum (mV) of GPIO4 (V) and GPIO5 (I) every
second.

### Test gate M3-lite

- [ ] GPIO4 mean ≈ **1650 mV** (between about 1550 and 1750 mV) and min ≈ max
      (no wave). Write the value down.
- [ ] Optional cross-check with a multimeter (DC volts, black on the − rail): column
      28 (Vb) and column 34 (A) both read about 1.65 V.
- [ ] Type `d` + Enter: a one-second CSV dump appears. Save it under
      `experiments/data/bench/` (git-ignored) as `m3lite-YYYYMMDD.csv`.

If GPIO4 reads near 0 mV, the 3V3 tap (j25) or the divider is missing; near
3300 mV, the GND tap (j31) is missing.

---

## M4: current channel (unchanged)

Do the full roadmap's
[M4](integration-roadmap.md#m4-current-channel-with-no-current-stage-4-t029)
exactly as written: it never needed the adapter. The logger from M3-lite stays on
the board.

### Test gate M4 (reduced kit)

- [ ] GPIO5 mean ≈ **1700 mV** and stable. Write it down (first look at the
      sensor's zero offset).
- [ ] GPIO4 still reads ≈ 1650 mV, flat, as in M3-lite.

---

## M5-lite: full firmware on the bench

**Goal:** the real measuring firmware runs on the real circuit, without screen and
without adapter.

```
make firmware-build
idf.py -C firmware -p /dev/ttyACM0 flash monitor
```

### Test gate M5-lite

- [ ] Early in the log: `OLED not found; LED and buzzer only`. Expected.
- [ ] `no accepted calibration: windows flagged calibration_missing` and
      `no threshold config yet` in the log.
- [ ] MQTT errors (`Host is unreachable`, `Connection reset by peer`,
      `disconnected; queueing`) repeat every few seconds. **Expected:** the server
      is not open to the Wi-Fi until M6, so summaries wait in the queue.
- [ ] The firmware does **not** print each measurement on the console (summaries
      go over MQTT only). After at least 10 s, type `cal status` + Enter. It must
      answer `CAL revision=none kind=nominal … last_p_w=… last_i_a=… quality=…`
      with `last_i_a` close to 0 and `quality` **not** `none` (`none` means no
      5 s summary has been made yet). The flag list (`out_of_range`,
      `calibration_missing`, and the absence of `sensor_disconnected`) is only
      visible on the server side, so it is checked in M6-lite.
- [ ] The RGB LED shows the degraded/offline state (the server is not reachable
      yet). Write down exactly what it shows.

Do **not** run `cal offset`, `cal sign` or `cal freeze` now: calibration belongs
to the bulb session (M8), after the adapter arrives.

---

## M6-lite: the real node talks to the server (T062)

T062 is defined with the bulb loop **not** connected, so this milestone can be done
in full now. Follow the full roadmap's
[M6](integration-roadmap.md#m6-the-real-node-talks-to-the-server-integration-2-t062):
open the server to the Wi-Fi (use **your** current addresses from `ip -4 addr`;
the phone hotspot changes them between sessions), register `node-001`, and watch it
with the viewers.

### Test gate M6-lite

- [ ] **Readings flow:** status `online`, a measurement every 5 s, each
      acknowledged; `counts` shows only `stored`; Grafana shows V and I near 0,
      labelled not validated, with the `out_of_range` quality visible.
- [ ] **Threshold delivered:** publish `config/thresholds.example.yaml`
      (`docker cp` + `energyctl threshold publish … --by <you>`). The serial log
      shows `threshold config v1: accepted`; after unplugging and replugging the
      board it is still there. (No excess can happen: power is about 0 W.)
- [ ] **Node-side outage:** switch the hotspot off for 2–3 minutes, then on. The
      queued readings arrive, in order, with no duplicates.
- [ ] **Server-side outage:** `docker stop unmsm-energy-ingestion-1`, wait 2
      minutes, `docker start unmsm-energy-ingestion-1`. No gap.
- [ ] **Offline display:** unplug the board. Grafana shows STALE, then OFFLINE,
      empty (never zero).
- [ ] Record the run in `experiments/manifests/bench-YYYYMMDD.json` (T062) and in
      the bench log. Mark it "no adapter: transport and recovery only".

---

## Hybrid end-to-end rehearsal (real node + simulated node)

**Goal:** every part of the end-to-end path is exercised once before the missing
parts arrive. The real `node-001` keeps running (transport, quality, recovery); the
simulated node `sim-e2e` plays the parts that need power: excesses, alerts, ntfy and
history.

1. Leave `node-001` powered and online (from M6-lite).
2. Follow the walkthrough [`guides/operations/e2e-walkthrough.md`](../guides/operations/e2e-walkthrough.md)
   from **case 5** to **case 14**, with `make simulate-e2e SCENARIO=…` as written
   there. Both nodes show in Grafana; pick each one in turn.

| Check | Played by | Walkthrough case |
|---|---|---|
| Brief surges do not alert | `sim-e2e` | 6 |
| Sustained excess: event, alert, ntfy on the phone | `sim-e2e` | 7 |
| Acknowledging alerts | `sim-e2e` | 8 |
| Invalid readings, malformed messages | `sim-e2e` | 9 |
| Duplicates, out-of-order | `sim-e2e` | 10 |
| Node-side and server-side outage | `node-001` (done in M6-lite) and `sim-e2e` | 11, 12 |
| Clock holdover | `sim-e2e` | 13 |
| A week of history, hourly/daily/weekly energy, busiest hour | `sim-e2e` | 14 |
| Local LED (and buzzer, after add-on C) react to a state | `node-001` (offline/degraded states seen in M5-lite and M6-lite); the excess alarm waits for add-on B | — |

### Test gate: hybrid rehearsal

- [ ] Cases 5–14 pass as described in the walkthrough.
- [ ] While `sim-e2e` runs, `node-001`'s data is unchanged (no mixing, still
      `stored` only).
- [ ] Write one bench-log entry: "hybrid rehearsal, simulated power; not
      evidence".

---

## Add-on A: the OLED

Low risk: the screen only uses 3V3, GND and two signal pins. Unplug USB first.

1. Screen's 4 header pins into **h45, h46, h47, h48**, screen facing you. Read the
   labels on the screen; the figure assumes GND, VCC, SCL, SDA from left to right.
   If yours differ, follow **your** labels.
2. Four male-male jumpers:

| Screen pin | From | Into hole |
|---|---|---|
| GND | top − rail | j45 |
| VCC | top + rail (**3V3**, never 5V) | j46 |
| SCL | **j8** (GPIO9) | j47 |
| SDA | **j11** (GPIO8) | j48 |

   A 7-pin screen is SPI, not I²C: stop and tell the team.
3. Power-on check (full roadmap, section 4).

### Test gate A

- [ ] Flash `stage2_peripherals` again: `I2C device at 0x3C` (or 0x3D) and
      `PASS OLED text written`; the text is readable. An offset or garbled image
      suggests an SH1106: set `OLED_COLUMN_OFFSET` to 2 (BG §6).
- [ ] Flash the main firmware again (`idf.py -C firmware -p /dev/ttyACM0 flash
      monitor`; the credentials are kept). The `OLED not found` line is gone and the
      screen shows V, I and "NO VALIDADO".
- [ ] Bench-log entry: "OLED fitted".

Nothing else changes: the main firmware already contains the screen driver.

---

## Add-on B: the AC-AC adapter

This is the step that brings real power into the system, so it follows the full
roadmap's safety rules exactly. The adapter is a closed 12 V AC wall unit: **you
never open it or touch its mains side**, and it **never** connects to the ESP32
board's power. If anyone on the team is unsure, stop and ask the qualified person.

1. **Jack jumpers:** adapter unplugged from the wall, barrel plug in the jack. Do
   full-roadmap M3
   [step 7](integration-roadmap.md#steps-adapter-unplugged-from-the-wall-the-whole-time):
   screw 2 → **j28** (Vb), screw 1 → **j40** (AC); tug-test both.
2. **AC gate:** full-roadmap [Test gate M3](integration-roadmap.md#test-gate-m3),
   second and third boxes (adapter into the wall: GPIO4 mean ≈ 1650 mV, min ≈ 890,
   max ≈ 2410 mV; save a CSV dump). Clipping near 0 or 3300 mV: unplug and stop.
3. **Full M5 gate:** full-roadmap [Test gate M5](integration-roadmap.md#test-gate-m5):
   about 12 V, about 0 A, and V drops to about 0 when the adapter is unplugged.
4. **Bulb loop:** full-roadmap
   [M7](integration-roadmap.md#m7-build-and-check-the-bulb-loop-stage-5-t063),
   with the adapter unplugged. Two team members check and sign (T063).
   **No signature, no M8.**
5. **Bulb session:** full-roadmap
   [M8](integration-roadmap.md#m8-bulb-session-calibration-e1-and-e2-stage-6-t064-t087):
   calibration, E1 plausibility and E2 alerts, now with the **real** node exceeding
   the limit (local LED and buzzer, remote alert, ntfy). Add-on C must have passed
   first, so the buzzer is part of this test.

### Test gate B

- [ ] The AC gate (step 2) and the full M5 gate (step 3) pass.
- [ ] The M7 checklist is signed.
- [ ] The M8 gate passes (calibration revision registered under the same name, E1,
      E2, ntfy received).

## Add-on C: the replacement buzzer

The buzzer stage (1 kΩ, transistor, jumpers) is already built and stays as it is;
only the buzzer itself changes. Buy the same type: an **active** 5 V buzzer
(sealed black bottom, "+" mark; a passive one with a visible green board needs a
firmware change).

1. **Test the new buzzer alone first** (USB unplugged): − in **f27**, + in **f30**,
   jumper **j27** → top − rail, and the 5V jumper's rail end moved from the bottom
   + rail into **j30**. Plug in USB: a continuous tone. Unplug, then put the 5V
   jumper back (**j2 → bottom + rail**) and remove the j27 jumper.
2. **Swap it in** (USB unplugged): take the faulty buzzer out of **e50/e53**; put
   the new one in with **−** in **e50** and **+** in **e53**. Push it down firmly.
   Check that **a47 → a50** and **a53 → bottom + rail** are in place.

### Test gate C

- [ ] Flash `stage2_peripherals`: one 200 ms beep about 4 s after start (press
      **RST** to hear it again), silent otherwise. This closes the pending buzzer
      box of M2-lite.
- [ ] Bench-log entry: "buzzer replaced".

If the new buzzer sounds alone but not in the circuit, check the transistor stage:
move the GPIO16 jumper's board end from **j14** to the top + rail; a continuous tone
means the stage works and the jumper belongs exactly in **j14**. Silent: check the
transistor's leg order (E, B, C), the 1 kΩ in lines 42–46, and **a45 → bottom −
rail**.

## Recommended order

Add each part **as it arrives** and pass its own gate before going on: a fault then
points to the one part you just added.

1. Whatever arrives first: **A** (OLED) and **C** (buzzer) can be done at any time
   after M2-lite; **B** (adapter) at any time after M6-lite, and C must pass before
   M8 (the alert test needs the buzzer).
2. If both arrive together, do **A first** (minutes, low risk), then **B**.
3. Run the final real end-to-end test **once**, when both are in and M8 passed.

---

## Final real end-to-end test

With both parts fitted, do the full roadmap's
[M9](integration-roadmap.md#m9-performance-runs-and-the-final-end-to-end-t104-t105-t065):
E3 latency (T104), E4 outage (T105), the tables (T065, T091), and its
[final end-to-end checklist](integration-roadmap.md#the-final-end-to-end-test-project-done).
Every box there must be ticked with the **real** node and the bulb loop; the
hybrid rehearsal does not count for any of them.

---

## Progress checklist (reduced kit)

| # | Milestone | Gate passed (date, who) | Evidence |
|---|---|---|---|
| M2-lite | LED (no OLED; buzzer pending) | | monitor log, bench log |
| M3-lite | Voltage channel at rest | | value + CSV dump |
| M4 | Current channel | | values |
| M5-lite | Full firmware, no screen, no adapter | | monitor log, `cal status` |
| M6-lite | Real node to the server (T062) | | `bench-YYYYMMDD.json` |
| Hybrid | Walkthrough cases 5–14 beside the real node | | bench log (rehearsal) |
| A | OLED fitted | | photo of the screen |
| B | Adapter, AC gate, M7, M8 | | CSV dump, signed checklist, manifests |
| C | Replacement buzzer | | monitor log, bench log |
| Final | M9 and the final end-to-end | | manifests, article tables |

When this table is complete, also tick M2–M9 in the full roadmap's
[progress checklist](integration-roadmap.md#progress-checklist).
