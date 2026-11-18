# Prototype Build Guide

## 1. Purpose and status

This guide describes a staged educational prototype for one ESP32-S3 node
monitoring one single-phase laboratory load.

| Item | Prototype target |
|---|---|
| Supply under observation | Nominal 220 V AC, 60 Hz |
| Voltage sensing | Certified isolated 220 V AC to 9–15 V AC plug-in adapter |
| Current sensing | ACS712ELCTR-20A module, confirmed 100 mV/A variant |
| Proposed measurement range | 180–250 V RMS, 55–65 Hz, 0.5–5.0 A RMS |
| Approximate active-power range | 0–1,100 W, only after calibration |
| Controller | ESP32-S3 DevKitC-1, internal ADC1 |
| Network path | Wi-Fi to MQTT over TLS/mTLS, configured separately |

Component values and pin assignments below are nominal proposals from the project
plan. Verify them at the low-voltage bench stage and confirm the schematic before
assembly is treated as final. This guide is not an installation approval, a
certification, a billing instrument procedure, or permission to connect a load.

The prototype is for a supervised academic demonstration. It must not be used as
a protective device or represented as suitable for permanent installation.

## 2. Safety rules — read before handling parts

1. The ACS712 is the only prototype part whose terminals carry mains current.
   Place it in its own compartment inside a closed, touch-safe,
   flame-retardant enclosure. Only its low-voltage header may leave that
   compartment.
2. Never place the ACS712 mains path on a breadboard or use exposed flying mains
   leads. Use rated terminals and conductors, covered terminals, strain relief,
   and the reviewed enclosure arrangement.
3. Never handle, wire, adjust, or probe the ACS712 or its mains path while
   energized. De-energize and verify the setup before any physical change.
4. The test setup requires upstream 30 mA RCD/GFCI protection and two-pole 10 A
   overcurrent protection. Their ratings and installation must be reviewed.
5. A qualified person must review the schematic, component ratings, isolation,
   creepage and clearance, conductor sizing, enclosure, protection, and test
   setup, and sign the review record before any mains connection.
6. Do not connect USB to a mains-earthed PC while the prototype is energized
   unless the qualified reviewer explicitly approves that exact arrangement.
   Use the certified USB-C charger for node power as the default.
7. The AC-AC adapter is an AC-output sensing adapter. Never plug it into any DC
   power jack, including the Arduino Uno R4 DC jack. Connect its output only to
   the female barrel socket and low-voltage voltage-sensing network described
   here.
8. Stages 1–4 are de-energized or low-voltage bench work. Stage 6 is permitted
   only after the signed review, in the controlled supervised setup. Never work
   live or expose energized terminals.
9. Stop immediately if a part, conductor, enclosure, isolation boundary, or
   protection rating is unknown or damaged. Record it as unresolved and have
   the qualified reviewer determine the next safe action.

## 3. Parts checklist and tools

### Parts

The checklist follows the project plan. “To buy,” “borrow,” and “to confirm” are
status notes, not authorization to substitute unreviewed parts.

| Function | Part and nominal detail | Spanish search term | Qty | Status / source |
|---|---|---|---:|---|
| Controller and ADC | Espressif ESP32-S3 DevKitC-1, internal ADC1 | `ESP32-S3 DevKitC-1` | 1 | Kit; available |
| Current sensor | Allegro ACS712ELCTR-20A module, 100 mV/A | `módulo sensor de corriente ACS712 20A` | 1 | Kit; available |
| Voltage sensor | Certified isolated 220 V AC to 9–15 V AC plug-in adapter | `adaptador transformador 220V a 12V AC (salida alterna ~)` | 1 | Buy |
| Adapter connection | Female DC barrel socket, 5.5 × 2.1 mm, screw terminals | `jack DC hembra 5.5x2.1 con bornera` | 1 | Buy; low cost |
| Divider / bias resistors | 1/4 W: 100 kΩ, 4.7 kΩ ×2, 10 kΩ ×4; one 10 kΩ may be DHT22 pull-up unless module has one | `resistencias 1/4 W 100k, 10k, 4.7k` | 1 set | Buy; low cost |
| Bias and filter capacitors | 10 µF ×1 and 22 nF ×2 | `condensador electrolítico 10uF 25V`; `condensador cerámico 22nF` | 1 set | Buy; low cost |
| Local alert | Active 5 V buzzer | `buzzer activo 5V` | 1 | Kit; available |
| Status light | RGB LED, assumed common cathode, plus 3 × 470 Ω | `LED RGB cátodo común 5 mm` | 1 | Kit; confirm LED type |
| Local display | 0.96-inch OLED, assumed 4-pin SSD1306 I²C | `pantalla OLED 0.96 I2C SSD1306` | 1 | Kit; confirm interface |
| Buzzer driver | NPN 2N2222 or PN2222A and 1 kΩ base resistor | `transistor 2N2222`; `resistencia 1k 1/4 W` | 1 each | Buy; low cost |
| Temperature log | DHT22 / AM2302, mounted inside enclosure near ACS712 | `sensor DHT22 / AM2302` | 1 | Kit; available |
| Node power | Certified USB-C 5 V, 2 A charger and cable | `cargador USB-C 5V 2A certificado` | 1 | Kit; available |
| Reference instrument | True-RMS multimeter, CAT III ≥ 300 V, documented AC accuracy ≤ 2% | `multímetro True RMS CAT III` | 1 | Not owned; borrow from a lab |
| Enclosure / protection | Closed flame-retardant enclosure with ACS712 compartment; 30 mA RCD/GFCI; two-pole 10 A protection; rated terminals and cable | `caja de paso plástica / caja estanca`; `interruptor diferencial 30 mA`; `llave termomagnética bipolar 10 A` | 1 set | Lab / qualified-person review |
| Calibration loads | Stable resistive loads about 100 W, 500 W, 1 kW; one stable inductive or nonlinear load | `foco incandescente/halógeno 100 W`; `hervidor o calefactor` | 3–4 | Select through lab |

Do not use the kit relay, Arduino Uno R4, motors, servos, or unrelated sensors in
this measurement build. The Arduino Uno R4 DC jack is specifically not an AC
adapter input. No custom bare mains-voltage sensor board is part of this design.

### Tools and records

- ESP-IDF 5.4 LTS toolchain and the project firmware build/flash instructions.
- Insulated hand tools appropriate to the low-voltage assembly work.
- A multimeter for the DC bench checks (bias and offset voltages). The team
  does not own one: use the borrowed lab meter, which must also be a true-RMS
  CAT III instrument for the supervised calibration.
- No oscilloscope is assumed: capture waveforms with the ESP32-S3's own ADC
  (raw-sample logging over USB on the bench, before any mains stage). Use a lab
  oscilloscope only if one is available.
- A current-limited low-voltage DC source (about 1 A) for the Stage 4 polarity
  check, for example a lab bench supply with a suitable power resistor (to
  define with the lab).
- Breadboard and jumper wires for low-voltage peripheral experiments only.
- Soldering and enclosure tools as approved by the lab; no mains work on a
  breadboard or with exposed leads.
- Build log: date, operator, board and sensor identities, wiring revision,
  firmware revision, instrument identity, measurements, temperature, and issues.

## 4. Stage 1 — ESP32-S3 alone

Keep the board disconnected from all sensor and mains-related hardware.

1. Install or activate the project’s ESP-IDF 5.4 LTS environment.
2. Build and flash the firmware using the project instructions. Use only the
   development configuration and non-secret placeholders where configuration is
   required.
3. Power the board from a certified USB-C charger. Do not use a mains-earthed PC
   USB link during any later energized setup unless the reviewer approves it.
4. Confirm the board boots and that serial diagnostics identify the expected
   ESP32-S3 target and firmware build.
5. Configure Wi-Fi using local credentials through the approved provisioning
   path. Never write credentials into this guide, source control, logs, or
   screenshots.
6. Confirm association to the intended lab Wi-Fi and record a redacted status
   result. Real SSIDs, broker names, addresses, certificates, and keys do not
   belong in this document.
7. Blink the RGB LED if the LED is already safely connected through the specified
   series resistors. If it is not connected, defer the LED check to Stage 2.

**Pass:** board boots reliably, firmware target is correct, Wi-Fi association is
reported without exposing credentials, and an LED blink is visible when the LED
is connected. Resolve boot or provisioning problems before adding peripherals.

## 5. Stage 2 — low-voltage peripherals, one at a time

Use the ESP32-S3, certified USB-C charger, and a common low-voltage ground. Add
one peripheral, test it, then power down before changing wiring. Stage 2 contains
no mains connection and no ACS712 mains conductor.

### OLED: GPIO8 / GPIO9

1. Confirm the module is the assumed 4-pin I²C SSD1306 type. A 7-pin SPI OLED
   does not match this allocation; stop and resolve the pin plan before wiring.
2. Connect SDA to GPIO8, SCL to GPIO9, VCC to 3V3, and GND to common GND.
3. The plan assumes the module has its own I²C pull-ups. Do not add unplanned
   pull-ups without checking the module and schematic.
4. Run the display check and show a simple status screen with units or a test
   label. Verify the screen updates repeatedly.

**Pass:** the expected I²C display is found and renders stable, readable text.

### DHT22: GPIO15

1. Connect DHT22 VCC to 3V3, GND to common GND, and DATA to GPIO15.
2. Fit a 10 kΩ pull-up from DATA to 3V3 unless the DHT22 module already includes
   one. The checklist’s 10 kΩ resistor may serve this purpose.
3. Read temperature and humidity repeatedly. Place the sensor in the intended
   enclosure location near the ACS712 for later temperature metadata; do not use
   these readings as electrical measurement evidence.

**Pass:** readings arrive repeatedly without sensor errors and are plausible for
the room. Record the sensor/module type and placement.

### Active buzzer: GPIO16 through 2N2222

1. Do not drive the 5 V buzzer directly from an ESP32 GPIO.
2. Connect GPIO16 through a 1 kΩ resistor to the 2N2222 base. Connect the
   emitter to common GND and the buzzer between 5 V and the collector, as in the
   reviewed low-voltage schematic.
3. Confirm the actual transistor pinout from its part documentation before
   wiring. The pinout is not universal across packages.
4. Exercise the buzzer briefly from firmware and confirm it is switched by the
   transistor. Power down before rewiring.

**Pass:** buzzer sounds on command, remains off otherwise, and the GPIO is only
connected through the base resistor.

### RGB LED: GPIO17 / GPIO18 / GPIO21

1. Confirm the LED is common cathode (assumed). Connect its common cathode to
   GND.
2. Connect red to GPIO17, green to GPIO18, and blue to GPIO21, each through its
   own 470 Ω series resistor.
3. Test each color individually, then test the normal, warning, invalid,
   offline, and insufficient-data indications from the local state mapping.

**Pass:** each channel lights independently, mixed colors are distinguishable,
and no LED channel is connected without its 470 Ω series resistor.

Record each peripheral’s result before continuing. If a check fails, remove that
peripheral and return the board to its last known-good configuration.

## 6. Stage 3 — voltage channel on the low-voltage bench

This stage uses only the certified isolated AC-AC adapter output. The adapter is
not connected to any DC power jack. Do not connect a load conductor or mains
through the ACS712 in this stage.

### Nominal network

- Plug the adapter’s 5.5 × 2.1 mm output into the female barrel socket with screw
  terminals. Keep the adapter unplugged from its protected outlet while wiring.
- Build the 1.65 V bias node (Vb): two equal 10 kΩ resistors in series between
  3V3 and GND, with 10 µF from Vb to GND.
- Connect one adapter output wire directly to Vb. The adapter output is
  isolated (floating), so this simply references the AC signal to 1.65 V. There
  is no series coupling capacitor in this design.
- Connect the other adapter wire through R1 = 100 kΩ to the junction A, and
  R2 = 4.7 kΩ from A back to Vb. A therefore sits at Vb + v_adapter × 4.7/104.7
  (a divider of about 1/22).
- Connect A to GPIO4 (ADC1_CH3) and place 22 nF from A to GND as the anti-alias
  capacitor. This matches Fig. 2 of the article and plan.md › Front end.
- Join the low-voltage grounds as shown in the reviewed schematic. Keep adapter
  output and ESP32 circuitry on the isolated low-voltage side only.

### Checks

1. With the adapter unplugged and the board powered from its certified USB-C
   supply, measure the bias junction with the multimeter. It should be near
   1.65 V. Record the actual value; investigate a missing divider, reversed
   ground/3V3 connection, or incorrect capacitor wiring before proceeding.
2. Confirm GPIO4 is within the ADC-safe range and centered near the measured bias
   when the adapter is unplugged. Do not connect the network to a GPIO until the
   wiring has been inspected for shorts and out-of-range voltages.
3. Plug the certified adapter into a protected outlet only after the low-voltage
   wiring is checked. Capture the GPIO4 waveform and confirm a centered AC swing.
4. For an unloaded 9–15 V AC adapter, the plan estimates about ±1.1 V peak at
   GPIO4 for the upper 15 V adapter case (about 18 V RMS unloaded). Treat this
   only as an expected approximate swing; verify the actual adapter and ADC
   waveform at the bench.
5. Confirm the waveform remains within the ADC linear range and does not clip.
   If it does, stop and revise the divider only through a documented schematic
   change and review. Do not improvise component values.

**Pass:** bias is near 1.65 V with the adapter unplugged, the adapter produces a
centered periodic waveform at GPIO4, and no clipping or unsafe voltage is seen.
Record adapter identity, output behavior, waveform, and measured bias.

## 7. Stage 4 — current channel without mains

This stage checks only the low-voltage output of the ACS712. No mains conductor
passes through IP+/IP−. Use a low-voltage, current-limited DC source and keep
current within the limits of the source, sensor, and wiring. The supply and
measurement arrangement must be reviewed before use.

### Nominal network and checks

1. Power the ACS712 module from 5 V from the certified USB-C supply. The module
   has its own supply decoupling capacitor. Connect its low-voltage ground to
   common GND.
2. Route the module OUT signal through R3 = 4.7 kΩ and R4 = 10 kΩ as the proposed
   divider. The total load is 14.7 kΩ, above the ACS712 4.7 kΩ minimum. The
   divider maps the sensor’s output into a 3.3 V-safe ADC range.
3. Place 22 nF from GPIO5 (ADC1_CH4) to GND. Keep the output junction and ground
   wiring short and check the schematic before power-up.
4. With zero current through the sensor, read the divided output at GPIO5. The
   expected nominal value is about 1.70 V, reflecting the ACS712’s approximately
   2.5 V output midpoint divided into the ESP32-safe range. Record the measured
   offset; it is not a substitute for the later 60-second session zero capture.
5. With the setup de-energized before wiring, route a low-voltage DC current
   through the sensor’s IP+ and IP− current path in the documented direction.
   Do not use a mains source or the laboratory load for this polarity check.
6. Observe that GPIO5 moves from the zero-current offset consistently with
   current magnitude and direction. Reverse the low-voltage current direction
   only while the source is off and the setup is safe to change.
7. Record the polarity convention and waveform/ADC values. Stop if GPIO5 leaves
   the ADC-safe range or the result is unstable.

**Pass:** zero-current GPIO5 is near 1.70 V, low-voltage DC current produces a
repeatable signed change around that offset, and the ADC input stays in range.
No mains connection is involved in this stage.

## 8. Stage 5 — enclosure and qualified safety review

Do not proceed to any mains connection until the complete schematic and physical
assembly have been inspected de-energized and the reviewer has signed below.

The qualified reviewer checks and records at least:

- ACS712 identity/variant, module terminal construction, creepage and clearance,
  conductor rating, polarity, and suitability for the proposed path.
- The ACS712 is the only part carrying mains and is inside its own compartment
  in a closed, touch-safe, flame-retardant enclosure.
- Only the low-voltage ACS712 header leaves that compartment; mains terminals
  are covered and inaccessible during normal use.
- Cable entry, conductor sizing, terminations, strain relief, mechanical support,
  spacing, and enclosure integrity are suitable for the reviewed setup.
- Certified isolation and suitability of the AC-AC adapter, including its AC
  output connection to the barrel socket and voltage divider.
- RCD/GFCI is 30 mA and upstream; overcurrent protection is two-pole 10 A.
- Node power comes from the certified low-voltage USB-C charger.
- No mains wiring is present on breadboards, loose jumpers, or flying leads.
- The controlled test setup, load connection, earthing/isolation conditions,
  polarity, protective-earth checks where applicable, and meter category/rating.
- USB connection policy: no mains-earthed PC link while energized unless the
  reviewer approves the specific arrangement.
- De-energized visual, protection, polarity, enclosure, strain-relief, and
  conductor checks can be completed before supervised energization.
- All outstanding assumptions and component ratings are resolved or explicitly
  recorded with a safe disposition.

### Required sign-off record

| Record field | Entry |
|---|---|
| Schematic / wiring revision | To complete |
| Enclosure and protection identifiers | To complete |
| ACS712 variant and review notes | To complete |
| Reviewer name and qualification | To complete |
| Review date | To complete |
| Conditions / unresolved items | To complete |
| Reviewer signature | Required before any mains connection |
| Build operator | To complete |
| Authorization for supervised test setup | Reviewer to record |

An unsigned, incomplete, or conditional review is not authorization to connect
mains. Resolve every condition with the qualified reviewer first.

## 9. Stage 6 — supervised connection and calibration

This stage is performed only after Stage 5 is complete and signed. The qualified
person supervises the controlled setup. Do not open the enclosure, touch wiring,
or make adjustments while energized. If a change is needed, de-energize and have
the qualified person verify the safe state before work.

1. Record the build revision, firmware commit, ADC settings, voltage adapter,
   ACS712 model/variant, wiring, operator, enclosure temperature from the DHT22,
   load identities, and reference meter identity and AC uncertainty.
2. Confirm the upstream 30 mA RCD/GFCI and two-pole 10 A protection are in place
   and that the reviewed closed enclosure and controlled test connections are
   being used.
3. Warm up the system for at least 10 minutes under the approved procedure.
4. At no load, capture 60 seconds of zero-current data and store the ACS712
   offset. Repeat auto-zero before each calibration session.
5. Use the identified true-RMS reference meter to calculate voltage and current
   gains on stable resistive loads. With one meter, take voltage and current
   readings alternately while the load remains stable.
6. On a stable resistive load, adjust fractional-sample phase correction until
   measured active power agrees with `P = V_RMS * I_RMS` (unity power factor).
   This relationship is for the resistive calibration point; active power in
   operation is calculated from paired instantaneous `v*i` samples.
7. Write coefficients as a new immutable calibration artifact/NVS revision and
   freeze them before acceptance validation. Do not tune coefficients using the
   validation dataset.
8. Validate on at least three separate stable resistive loads spread across the
   calibrated range, approximately 100 W, 500 W, and 1 kW for this configuration.
   Record at least 5 minutes per power point and at least 15 minutes for energy.
   Compare power with `P_ref = V_ref * I_ref` and energy with `Wh_ref = P_ref * t`.
9. Record one stable inductive or nonlinear load for voltage and current
   validation. Its W/Wh are observations only, without an accuracy claim, unless
   a suitable power reference with documented uncertainty is available.
10. Require every required V, A, W, and Wh point to meet `|error| ≤ 5%` when
    reference meter uncertainty is at most 1%. If uncertainty is above 1% and
    at most 2%, apply the guard-banded limit `|error| ≤ 5% − u_ref`. A meter
    above 2% uncertainty or without true-RMS capability cannot support the claim.
    Below-range/no-load current uses an absolute noise limit, not percentage
    error.
11. Preserve raw waveform excerpts, summaries, reference readings, temperatures,
    scripts, environment, coefficients, firmware and wiring revisions, hashes,
    and pass/fail output. Flag outside-range data; it cannot support the claim.

Acceptance supports only the tested educational prototype configuration and
stated calibrated ranges. It does not approve permanent installation, billing,
or safety-device use.

## 10. Troubleshooting

| Symptom | Likely cause | Check |
|---|---|---|
| ESP32-S3 does not boot | Wrong target/build, power, or flash procedure | Check board identity, USB-C charger/cable, firmware build output, and boot log |
| Wi-Fi does not associate | Local credentials or lab network configuration | Verify provisioning locally; never copy secrets into logs or this guide |
| OLED is blank | SPI module, wrong SDA/SCL, supply, or address/config mismatch | Confirm 4-pin I²C assumption; recheck GPIO8/9, 3V3, GND, and firmware config |
| DHT22 read errors | Missing pull-up, wiring, or module fault | Check GPIO15, 10 kΩ pull-up unless onboard, 3V3, GND, and sensor identity |
| Buzzer silent or always on | Transistor pinout, base resistor, or wiring error | Power down; verify 2N2222 pinout, GPIO16-to-1 kΩ-to-base, emitter GND, buzzer/collector path |
| RGB color missing | LED type/pin order or absent series resistor | Confirm common cathode assumption and GPIO17/18/21 mapping; verify each 470 Ω resistor |
| GPIO4 bias not near 1.65 V | Bias divider, ground, or 10 µF connection error | Adapter unplugged: measure the bias junction and inspect equal 10 kΩ divider wiring |
| GPIO4 waveform clips | Divider or adapter output differs from nominal | Stop; record waveform and adapter; revise only through schematic review |
| GPIO4 has no AC swing | Adapter not connected, barrel socket mismatch, or R1/R2/Vb wiring error | Confirm adapter is AC output, connected via barrel socket, and inspect reviewed low-voltage schematic |
| GPIO5 offset far from ~1.70 V | ACS712 supply, divider, ground, or sensor variant issue | Verify 5 V, common GND, R3=4.7 kΩ, R4=10 kΩ, and confirmed 20A module |
| GPIO5 polarity seems reversed | IP+/IP− direction or software sign convention | Repeat only the low-voltage DC check with source off during rewiring; record direction |
| ADC values jump or drop samples | Wiring noise, ADC configuration, DMA overrun, or missing conversion | Inspect low-voltage grounds/filter and firmware diagnostics; affected windows are invalid |
| Calibration drifts | Warm-up, supply variation, temperature, load instability, or reference uncertainty | Repeat recorded warm-up/zero and use stable loads and identified meter |
| Reviewer finds an unresolved safety item | Rating, enclosure, protection, or wiring is not established | Stop; resolve and obtain reviewer sign-off before any mains connection |

## 11. Open items and assumptions

- OLED is assumed to be a 4-pin I²C SSD1306 module. Confirm the actual module;
  a 7-pin SPI display changes the pin allocation and requires a reviewed update.
- RGB LED is assumed common cathode. Confirm the actual LED pinout and type
  before connecting GPIO17/18/21.
- The team does not own the required true-RMS CAT III reference multimeter.
  Borrow a suitable instrument from a university lab and record its identity and
  documented AC uncertainty before calibration.
- The certified AC-AC adapter and female barrel socket are marked to buy. Verify
  certification, output rating, connector polarity/continuity, and suitability
  at the bench before use.
- Final component layout (perfboard or enclosure mounting) is to define and
  review. Preserve the plan’s divider, bias, and filter values; do not
  substitute unlisted values.
- Bench equipment to borrow: a multimeter (also the calibration reference) and
  a current-limited DC source for the Stage 4 polarity check.
- The proposed ADC pins, ADC attenuation/configuration, and exact firmware
  calibration settings are to confirm during schematic and bench review.
- Reviewer identity, signed safety record, load identities, calibration results,
  and acceptance report are to complete before any measurement claim is made.

