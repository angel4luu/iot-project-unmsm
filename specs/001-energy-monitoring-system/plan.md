# Implementation Plan: Intelligent Electrical Energy Monitoring System

**Branch**: `001-energy-monitoring-system` | **Date**: 2026-10-14 (hardware amended 2026-11-18) | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/001-energy-monitoring-system/spec.md`

## Summary

Build one safe ESP32-S3 monitoring node (nominal calibration, readings labeled
"not validated") for a 12 V AC extra-low-voltage test loop and one reproducible
LAN server deployment. The node is built mostly from the team's existing kit
(ACS712 current sensor, ESP32-S3 internal ADC) plus one certified, thermally
protected 220 V → 12 V AC plug-in adapter that feeds both the voltage channel and
a 12 V halogen test bulb (plan B, 2026-11-18). It samples the voltage/current
channels alternately at 4,000 pairs/s with a corrected inter-channel delay, calculates RMS
voltage/current and phase-corrected active power, integrates import energy with a
monotonic clock, evaluates local thresholds, shows status on an RGB LED and a
local OLED display, and queues five-second summaries for offline replay. MQTT 5 with mutual TLS and per-node ACLs carries versioned payloads to
an idempotent Python ingestion service. The service persists 30 days of raw time
series in InfluxDB, discrete delivery/alert state in SQLite, and serves a
provisioned Grafana dashboard through LAN-only HTTPS. Automatic cutoff, LoRa,
environmental sensing, and production anomaly/forecast models are not included.

## Technical Context

**Language/Version**: Firmware C/C++17 with ESP-IDF 5.4 LTS; server Python 3.14.8;
Compose YAML; Flux; JSON Schema Draft 2020-12  
**Primary Dependencies**: ESP-IDF ADC continuous/calibration drivers, OLED driver (controller to confirm), ESP-MQTT/Mbed TLS, ESP-IDF NVS/SNTP/Unity;
Paho MQTT, Pydantic and `jsonschema`, InfluxDB Python client, SQLAlchemy/Alembic,
FastAPI health/management endpoint, pytest; Eclipse Mosquitto 2.1.2, InfluxDB OSS
2.9.1, Grafana OSS 13.2.3, Caddy 2  
**Storage**: Device RAM offline queue plus NVS energy checkpoints and encrypted NVS credentials; server InfluxDB `energy_raw`
and `operations` buckets with 30-day retention; SQLite WAL ingestion ledger,
configuration, alert audit, and notification outbox; named container volumes  
**Testing**: firmware logic tested on the development PC (host build with ESP-IDF's
Unity, hardware behind thin interfaces with fakes) against waveform fixtures whose
expected values come from a Python reference calculation; firmware payloads
validated against the JSON Schemas; the same tests later run on the ESP32-S3 as
on-target integration tests; pytest/unit/property/contract
tests; JSON Schema fixtures; Docker Compose integration and fault injection;
12 V loop session with nominal calibration and plausibility check (no reference meter); secret scanning and network
reachability tests  
**Target Platform**: ESP32-S3 DevKitC-1 monitoring node; one x86-64/ARM64 Linux host on the
trusted local LAN; modern browser on the same trusted LAN  
**Project Type**: Embedded firmware plus local services/infrastructure and a
provisioned web dashboard  
**Performance Goals**: 4,000 voltage/current pairs/s (8,000 alternating conversions/s); 1-second local decision
blocks; one summary/5 seconds; 95% dashboard visibility <=10 seconds; local alert
<=2 seconds and healthy-server alert <=10 seconds; drain recovery queue >=2
records/s; recover >=99% of a 10-minute outage within five minutes  
**Constraints**: Controlled educational prototype only; readings (labeled "not validated") limited to
10–16 V RMS, 0.5–2.0 A RMS (ACS712-20A), about 0–25 W on the 12 V AC
test loop (see Hardware); no relay; no mains wiring by the team (only the
certified adapter plugs into 220 V); a qualified safety review is required
before any future mains session; dashboard LAN-only; outbound notifications HTTPS only;
no committed secrets; 16 KiB maximum MQTT payload; at least 256 offline records in RAM  
**Scale/Scope**: One node, one circuit, one operator, about 518,400 five-second
records per 30 days, one Compose host, and one outbound notification destination

Exact application packages and container digests MUST be frozen in lockfiles and
the acceptance Compose manifest. No deployment may use an unqualified `latest`
tag. InfluxDB v2 is deliberately selected and must be referenced by exact tag
because its default/latest image line is not a stable v2 contract.

## Constitution Check

### Pre-research gate

| Principle or gate | Status | Planned evidence/control |
|---|---|---|
| I. Electrical Safety Before Convenience | PASS | Plan B: no mains wiring; only a certified, thermally protected plug-in adapter touches 220 V and everything the team wires is 12 V AC or less; load loop off the breadboard; no relay; de-energized (unplugged) assembly; team low-voltage wiring checklist before plugging in. A future 220 V session requires the 30 mA RCD, the closed ACS712 test box, and a signed qualified review |
| II. Measurement Integrity and Evidence | PASS | Constitution 2.0.0: exact quantities/ranges/units and algorithms; no reference meter, so nominal coefficients with offset zeroing and polarity check, every value labeled "not validated", no accuracy figure claimed, plausibility check against nameplates (research R-004) |
| III. Monitoring MVP Before Optional Complexity | PASS | One-node vertical slice only; LoRa, cutoff, environmental sensing, anomalies, forecasts, and recommendations deferred |
| IV. Security and Secret Hygiene | PASS | Per-principal mTLS/ACLs, encrypted NVS, ignored runtime secrets, private endpoints absent from tracked examples, secret scan gate |
| V. Contract-Tested Boundaries | PASS | ADC fixtures, five JSON Schemas, valid/invalid fixtures, idempotent storage/query and dashboard contract tests |
| VI. Reproducible Experiments and Models | PASS | Versioned calibration evidence and future dataset/experiment manifests; no model influences MVP alerts |
| VII. Resilience and Observability | PASS | RAM offline queue, NVS energy checkpoint with uncertain-interval flag, application ACK, deduplication, clock state, restart/outage tests, stage-specific health metrics |
| Dependencies/config/versioning | PASS | Locked firmware/Python/container dependencies; provisioned dashboards, schemas, infrastructure, and calibration/config revisions |

No constitution exception is requested. The MVP has no mains hardware built by
the team; any future mains hardware without a signed qualified review is a
release blocker, not an accepted planning exception.

### Post-design gate

Phase 1 keeps every pre-research gate at **PASS**:

- [research.md](research.md) records decisions, sources, risks, and rejected
  alternatives for safety-relevant and irreversible choices.
- [data-model.md](data-model.md) defines units, quality, identity, lifecycle, and
  persistence invariants.
- [contracts/](contracts/) defines independently testable firmware/service
  boundaries and valid/invalid fixtures.
- [quickstart.md](quickstart.md) starts with simulation and separates PC-only
  software checks from the 12 V loop session on hardware.
- Analytics collection is designed, but model training/deployment remains a
  separate future specification and cannot block or alter the MVP.

## Project Structure

### Documentation (this feature)

```text
specs/001-energy-monitoring-system/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── README.md
│   ├── measurement.schema.json
│   ├── node-status.schema.json
│   ├── node-event.schema.json
│   ├── threshold-config.schema.json
│   ├── measurement-ack.schema.json
│   └── examples/
│       ├── valid-measurement.json
│       └── invalid-measurement.json
└── tasks.md                 # Created later by $speckit-tasks, not this plan
```

### Source code (repository root, to be created by implementation tasks)

```text
firmware/
├── CMakeLists.txt
├── sdkconfig.defaults
├── main/
├── components/
│   ├── acquisition/
│   ├── calibration/
│   ├── metering/
│   ├── quality/
│   ├── persistence/
│   ├── threshold/
│   ├── telemetry/
│   └── ui/
└── test/
    ├── host/          # Unity tests built for the PC (no board needed)
    └── target/        # same tests and fixture replay on the ESP32-S3 (later, [HW])

services/
└── ingestion/
    ├── pyproject.toml
    ├── uv.lock
    ├── Dockerfile
    ├── migrations/
    ├── src/energy_ingestion/
    │   ├── contracts/
    │   ├── mqtt/
    │   ├── persistence/
    │   ├── thresholds/
    │   ├── notifications/
    │   ├── health/
    │   └── cli/
    └── tests/

infrastructure/
├── compose.yaml
├── compose.lock.yaml
├── mosquitto/
├── caddy/
├── influxdb/
├── grafana/
│   └── provisioning/
│       ├── datasources/
│       └── dashboards/
└── secrets/
    └── README.example.md

dashboards/
├── energy-overview.json
└── queries/

config/
└── thresholds.example.yaml

experiments/
├── export/
├── manifests/
└── evaluation/

tests/
├── contract/
├── integration/
├── recovery/
├── security/
├── acceptance/
├── evaluation/
└── fixtures/
    ├── waveforms/     # synthetic CSVs plus expected.json from reference.py
    ├── telemetry/
    └── plausibility/

guides/                      # not docs/: docs/ is git-ignored local lab material
├── architecture/
├── safety/
├── calibration/
├── operations/
└── experiments/
```

**Structure Decision**: Keep hazardous/data-acquisition behavior in `firmware/`,
all server policy in one focused `services/ingestion/` service, deployment state
in `infrastructure/`, and user-visible queries in `dashboards/`. The Phase 1
schemas under this feature directory are the normative contracts; implementation
tests import them rather than maintaining divergent schema copies. `experiments/`
contains dataset export/evaluation tools only, not an MVP analytics service.

Repository setup MUST track `.specify/`, `specs/`, source, infrastructure,
dashboards, example configuration, lockfiles, and procedures. It MUST ignore
`.env*` except `.env.example`, private keys/certificates, local secret directories,
runtime databases/volumes, build outputs, caches, captures containing private
data, and generated experiment data not represented by a checked manifest. The
existing `.gitignore` rule that ignores `.specify` conflicts with repository
instructions and must be corrected in the first repository-baseline task.

## Component and Deployment Design

This figure replaces the conflicting LoRa diagram. Solid arrows are runtime data
or control; dotted arrows are offline evidence. Trust and deployment boundaries
are explicit.

```mermaid
flowchart LR
    subgraph ELEC[Electrical setup, plan B]
        OUTLET[220 V wall outlet]
        ADP[Certified, thermally protected<br/>220 V to 12 V AC adapter<br/>isolation barrier]
        LOOP[12 V AC loop:<br/>ACS712 IP+/IP- and halogen bulb]
        VS[Voltage channel:<br/>adapter output via jack]
        CS[ACS712 Hall current sensor<br/>output 5 V, GND, OUT]
        OUTLET --> ADP --> LOOP
        ADP --> VS
        LOOP --> CS
    end

    subgraph NODE[Low-voltage monitoring node]
        AFE[Dividers, bias, RC filters<br/>ESP32-S3 ADC1, alternating 4,000 pairs/s]
        MCU[ESP32-S3<br/>RMS, active W, import Wh, quality]
        BUF[RAM offline queue<br/>NVS energy checkpoints]
        RULE[1 s local threshold state]
        WARN[Buzzer only<br/>no relay]
        UI[RGB status LED<br/>OLED local display]
        AFE --> MCU --> BUF
        MCU --> RULE --> WARN
        MCU --> UI
    end

    VS --> AFE
    CS --> AFE

    subgraph LAN[Trusted local LAN]
        subgraph HOST[One version-pinned Compose host]
            BROKER[Mosquitto<br/>MQTT 5 mTLS :8883]
            INGEST[Python ingestion<br/>schema, identity, ledger, alerts]
            LEDGER[(SQLite WAL<br/>ledger, config, alert audit, outbox)]
            TS[(InfluxDB v2<br/>raw and operations, 30 d)]
            GRAF[Grafana<br/>provisioned dashboards]
            PROXY[Caddy<br/>authenticated HTTPS :443]
            BROKER --> INGEST
            INGEST --> LEDGER
            INGEST --> TS
            TS --> GRAF --> PROXY
        end
        USER[Operator browser]
        USER -->|HTTPS, authenticated| PROXY
    end

    BUF -->|measurements, events, status<br/>QoS 1 + application ACK| BROKER
    INGEST -->|retained threshold config<br/>and durable ACK| BROKER
    INGEST -->|outbound HTTPS only| NOTIFY[Remote notification provider]
    NOTIFY --> USER
```

### Physical deployment

The component diagram above shows what runs where; this one shows the physical
devices, the links between them, and the protocol and port on each link.

```mermaid
flowchart LR
    subgraph BENCH[Bench]
        OUT[220 V outlet] --> ADP[12 V AC adapter,<br/>thermally protected]
        ADP --> LOOP[12 V loop:<br/>ACS712 + bulb]
        CHG[Certified 5 V<br/>USB charger]
    end
    subgraph DEV[Device: ESP32-S3 DevKitC-1 on breadboard]
        FW[Firmware: acquisition, metering,<br/>quality, queue, threshold, UI, MQTT client]
    end
    ADP -->|GPIO4, divider| DEV
    LOOP -->|GPIO5, divider| DEV
    CHG -->|USB 5 V| DEV
    DEV -->|Wi-Fi WPA2| AP[Device: Wi-Fi router<br/>trusted local LAN]
    subgraph PC[Device: team computer, Docker Compose]
        MOS[Container: Mosquitto :8883]
        ING[Container: ingestion]
        SQL[(Volume: SQLite)]
        INF[Container: InfluxDB]
        GRA[Container: Grafana]
        CAD[Container: Caddy :443]
        MOS --> ING --> SQL
        ING --> INF --> GRA --> CAD
    end
    AP -->|MQTT 5, mutual TLS, :8883| MOS
    BR[Device: operator browser<br/>on the LAN] -->|HTTPS :443, login| CAD
    ING -->|HTTPS outbound only| EXT[External: notification provider]
```

Only ports 8883 and 443 are published on the team computer; InfluxDB, Grafana,
SQLite, and the ingestion health API stay on the Compose network.

### Deployment boundaries

- **Electrical boundary**: mains terminates inside the certified, thermally
  protected AC-AC adapter. Everything after it (12 V AC loop, ACS712, breadboard,
  ESP32, USB, network) is extra-low voltage; mains never reaches the team's
  wiring.
- **Node boundary**: acquisition, calibration, five-second aggregation, energy
  continuity, quality state, local threshold evaluation, clock management, and
  offline queue continue without server availability.
- **Broker boundary**: authenticates identities and enforces topics; it does not
  validate electrical semantics or prove database storage.
- **Ingestion boundary**: validates contract and identity, deduplicates, persists,
  evaluates/audits server alert state, emits notifications, and ACKs durable
  outcomes.
- **Storage/presentation boundary**: InfluxDB contains time series; SQLite contains
  discrete state. Grafana is read-only and receives a least-privilege Influx token.
- **Network boundary**: host publishes only 8883 and 443 to allowlisted lab
  subnets. Broker is restricted to device/host subnets. Databases, service health,
  and native Grafana ports stay on the Compose network. No public inbound route.

## Hardware and Measurement Design

*Amended 2026-11-18: adapted to the team's available kit for an educational
demonstration, with minimal purchases. Rationale and safety conditions are in
[research.md](research.md) R-001, R-002, R-004, and R-005.*

### Hardware list

| Function | Part (model) | Cómo pedirlo (Spanish search term, Peru) | Qty | Source | Status |
|---|---|---|---|---|---|
| Node microcontroller and ADC | Espressif ESP32-S3 DevKitC-1 (internal ADC1) | "ESP32-S3 DevKitC-1" | 1 | Kit | Available |
| Current sensor | Allegro ACS712ELCTR-20A module (100 mV/A, confirmed) | "módulo sensor de corriente ACS712 20A" | 1 | Kit | Available |
| Voltage sensor and loop supply | Certified, **thermally protected**, iron-core plug-in adapter, 220 V AC to 12 V **AC**, rated ≥ 2 A (plan B, 2026-11-18). Feeds both the voltage channel and the 12 V test loop | "adaptador transformador 220V a 12V AC 2A con protección térmica (salida alterna ~)" | 1 | Buy | To buy |
| Adapter connector | Female DC barrel jack with screw terminals, matching the adapter's plug (usually 5.5 × 2.1 mm; **check the plug**). Its two terminals feed the voltage jumpers to the breadboard and the load-loop cable; label it "AC" | "jack DC hembra con bornera 5.5x2.1" | 1 | Buy | To buy (low cost) |
| Low-voltage assembly | Solderless 830-point breadboard; about 20 male-to-male jumpers; 3–7 male-to-female jumpers (ACS712 VCC/OUT/GND, and the OLED or any ESP32 pin left without a free breadboard hole) | "protoboard 830 puntos"; "cables jumper macho-macho"; "cables jumper macho-hembra" | 1 set | Kit | Available (confirm male-to-female count) |
| Signal conditioning | Resistors 1/4 W: 100 kΩ ×1 (R1), 4.7 kΩ ×2 (R2, R3), 10 kΩ ×3 (bias ×2, R4); capacitors 10 µF ≥ 25 V electrolytic ×1 (bias), 22 nF ceramic ×2 (anti-alias) | "resistencias 1/4 W 100k, 10k, 4.7k"; "condensador electrolítico 10uF 25V"; "condensador cerámico 22nF" | 6 R + 3 C | Buy | To buy (low cost; one or two spares per value) |
| Local alert | Active 5 V buzzer | "buzzer activo 5V" | 1 | Kit | Available |
| Status light | Kit RGB LED (assumed common cathode, **to confirm**) with 3 × 470 Ω 1/4 W series resistors | "LED RGB cátodo común 5 mm"; "resistencia 470 ohm" | 1 LED + 3 R | Kit | Available (buy resistors only if missing) |
| Local display | OLED 0.96" module, assumed 4-pin SSD1306 on I²C (**to confirm**; a 7-pin SPI module changes the pin table) | "pantalla OLED 0.96 I2C SSD1306" | 1 | Kit | Available |
| Buzzer driver | NPN transistor 2N2222 (or PN2222A, TO-92) + 1 kΩ 1/4 W base resistor | "transistor 2N2222", "resistencia 1k 1/4 W" | 1 + 1 R | Buy transistor; resistor from kit | To buy (low cost) |
| Node power | Certified 5 V 2 A charger and a cable matching the board's connector (USB-C or micro-USB, depending on board revision) | "cargador USB-C 5V 2A certificado" | 1 | Kit | Available |
| Test load | One 12 V halogen bulb: G4 12 V 20 W (or a 12 V car bulb, about 21 W); stable resistive load of about 1.7 A | "foco halógeno G4 12V 20W" | 1 | Team or buy | To buy (low cost) |
| Load-loop wiring | Household copper cable ≥ 0.75 mm² (18 AWG), e.g. lamp cord, two pieces of about 30 cm, from old stock; 2 short alligator-clip leads from the kit; a terminal strip (2 positions used) only if no alligator leads are available. Carries the bulb current from the jack terminals through the ACS712 to the bulb, never through the breadboard | "regleta de bornes 12 polos" (only if no alligator leads) | 1 set | Team or buy | Available (check clips) |

Minimal MVP build, plan B (2026-11-18): only parts needed for measurement, local
indication, safety, and calibration are listed. No laboratory and no electrician
are available, so the MVP monitors a 12 V AC loop: the certified, thermally
protected adapter plugs into an ordinary wall outlet and is the only part at
220 V. Loop: jack terminal 1 → cable → ACS712 IP+ → IP− → 12 V bulb (alligator
leads or terminal strip) → cable → jack terminal 2. No fuse, RCD, test box, or
qualified review is needed for this loop: the adapter's thermal protection
limits a short circuit, and nothing the team touches exceeds 12 V AC. All low-voltage circuitry (bias and divider networks, filters, buzzer driver,
RGB LED, OLED, ESP32-S3) is assembled on a solderless breadboard with jumper
wires, so no soldering is required; the adapter plugs into a female barrel jack
with screw terminals whose two jumpers go to the breadboard (2026-11-18). The
load loop (about 1.7 A) never goes through the breadboard or jumper wires: it
runs on household cable and clips to the ACS712 screw terminals, and only the
ACS712's low-voltage header (5 V, GND, OUT) is jumpered to the breadboard. Not used in the
minimal build: DHT22 (temperature logging), bench DC polarity source, and a
dedicated DIN protection panel, and a reference multimeter (none is affordable;
constitution 2.0.0 allows a demonstration build labeled "not validated").

Not used: ADS131M02, SCT-013-020, ZMPT101B, MB85RC256V FRAM, DS3231 RTC (kept
as the documented upgrade path), and the kit's relay, Arduino Uno R4, motors,
servos, and unrelated sensors. Alert-accuracy step tests use the simulated node
instead of a relay bench.

### Front end and pin allocation

- **Voltage**: one wire of the floating AC-AC adapter output is tied to a
  mid-supply bias (two equal resistors of about 10 kΩ and a 10 µF capacitor);
  the other goes through a divider of about 1/22 back to that bias, then an RC
  anti-alias filter into an ADC1 input. No series coupling capacitor is used.
- **Current**: the ACS712 is powered from 5 V; its output (VCC/2 at zero current)
  goes through a divider with at least 4.7 kΩ total load into the 3.3 V-safe
  range, then an RC filter into an ADC1 input. The output is ratiometric to its
  5 V supply, so supply variation is part of the uncertainty budget and the node
  uses a stable certified charger.
- **Nominal design values (to verify at the bench stage)**: voltage divider
  R1 = 100 kΩ, R2 = 4.7 kΩ referenced to a 1.65 V bias (2 × 10 kΩ from 3.3 V,
  10 µF), giving about ±1.1 V peak for an unloaded 15 V adapter (about 18 V RMS);
  current divider R3 = 4.7 kΩ, R4 = 10 kΩ (14.7 kΩ load, above the ACS712's
  4.7 kΩ minimum), mapping 2.5 V ± 0.71 V at 5 A RMS to about 1.70 V ± 0.48 V
  (on the plan B loop, about 1.7 A RMS gives about ±0.16 V peak at GPIO5, and
  12 V RMS gives about ±0.76 V peak at GPIO4);
  22 nF from each ADC input to ground (anti-alias corner about 1.6–2.3 kHz;
  the small phase shift is absorbed by the phase correction); the ACS712 module
  already carries its supply decoupling capacitor. Proposed ADC pins: GPIO4 (ADC1_CH3) voltage, GPIO5
  (ADC1_CH4) current.
- **Sampling**: ESP-IDF ADC continuous (DMA) mode, alternating V/I pattern at
  8,000 conversions/s, Espressif calibration scheme, then per-device offset, gain,
  and fractional phase correction. DMA overrun or a missing conversion marks a
  sample gap and invalidates the affected window.
- **Pin allocation** (proposed; confirmed at the schematic review). Only ADC1
  is used for analog inputs (ADC2 is unusable with Wi-Fi); strapping pins
  (GPIO0, 3, 45, 46), USB pins (GPIO19, 20), and the octal-PSRAM pins of some
  modules (GPIO35–37) are avoided.

  | ESP32-S3 pin | Connected to | Notes |
  |---|---|---|
  | GPIO4 (ADC1_CH3) | Voltage channel (R1/R2 junction) | 22 nF to GND |
  | GPIO5 (ADC1_CH4) | Current channel (R3/R4 junction) | 22 nF to GND |
  | GPIO8 | OLED SDA (I²C) | Module has its own pull-ups |
  | GPIO9 | OLED SCL (I²C) | |
  | GPIO16 | Buzzer driver (1 kΩ to 2N2222 base) | Active 5 V buzzer between 5 V and collector |
  | GPIO17 / GPIO18 / GPIO21 | RGB LED red / green / blue | 470 Ω in series each; common cathode to GND |
  | 3V3 | Bias divider, OLED VCC | |
  | 5V | ACS712 VCC (module has its own decoupling), buzzer | From the USB-C supply |
  | GND | Common ground of all low-voltage parts | |
  | USB | Certified 5 V charger | A PC USB link is acceptable in plan B (everything is extra-low voltage) |

- **Mains safety (plan B)**: the team does no mains wiring; the ACS712 carries
  only the 12 V loop current. Rewire only with the adapter unplugged, keep the
  loop off the breadboard, and never open or modify the adapter. A future 220 V
  session would put the ACS712 alone in a closed test box with an RCD and a
  signed qualified review (research R-001).

### Local indication

| Node state (FR-015) | RGB status LED | OLED |
|---|---|---|
| Normal | Green | V, A, W, Wh with units, quality, clock and link state |
| Warning (threshold pending/firing/clearing) | Red (buzzer while firing/clearing) | Alert banner with value and limit |
| Invalid measurement or unsynchronized clock | Yellow | Value fields replaced by the quality reason |
| Offline (queueing for replay) | Blue | Link state and number of queued records |
| Insufficient data (warm-up, no accepted calibration) | White | Reason |

The OLED shows only node-local values with their units and quality; a value that
is not `valid` is never shown as a plain reading (SC-006). The display and LED
keep working with the network down.

### Quantities and aggregation

| Field | Exact meaning | Wire unit | Valid calibrated range |
|---|---|---|---|
| `voltage_rms` | Square root of mean squared calibrated instantaneous voltage across a 5 s window | V | 10–16 V RMS (12 V AC loop) |
| `current_rms` | Square root of mean squared calibrated instantaneous current across the same paired window | A | 0.5–2.0 A RMS (ACS712-20A, 12 V loop) |
| `active_power` | Mean instantaneous `v*i` after offset, gain, and phase correction; not `Vrms*Irms` | W | 0–25 W (not validated); signed diagnostic value |
| `active_energy_import_total` | Monotonic sum of `max(active_power,0)*monotonic_dt/3600` for one counter continuity ID | Wh | No accuracy claim; labeled "not validated" (nominal calibration) |

The firmware maintains 1-second calculation/quality blocks and combines five
blocks into one summary. A nominal summary has 20,000 paired samples. It reports
min/max and internal diagnostic counts locally, but the v1 wire contract carries
the contractually required values, sample count, valid ratio, calibration
revision, and flags. Schema 1.0.0 limits (for example the 2,500 W threshold
maximum) are wire bounds; the node and `energyctl` reject thresholds above the
plan B range maximum (25 W). No field claims apparent power, reactive power, power factor,
or billing accuracy.

### Calibration and plausibility procedure

No reference meter is used (constitution 2.0.0, research R-004).

1. Complete the team's low-voltage wiring checklist with the adapter unplugged
   (loop off the breadboard, tight ACS712 and jack terminals, no bare crossing
   conductors, adapter certified and unmodified).
2. Bench stage without mains: verify the voltage channel with the AC-AC adapter
   output only, recorded waveforms, and the ACS712 zero-current offset, using the
   ESP32-S3's own ADC logs.
3. Record build revision, firmware commit, ADC settings, sensors and ACS712
   variant, wiring, operator, load identities and nameplate ratings, and the
   statement that no reference instrument is used.
4. Load nominal coefficients: voltage gain from R1/R2 only (the node measures
   the 12 V adapter output directly),
   current gain from 100 mV/A and R3/R4, phase correction from the known
   one-conversion offset between channels.
5. Warm up at least ten minutes; capture 60 seconds at zero current and store the
   ACS712 offset.
6. Switch on a resistive load: active power must be positive (current polarity);
   if it is negative, correct the sign in the coefficients instead of rewiring.
   Freeze the result as a `nominal` calibration revision.
7. Plausibility check (SC-001) on the 12 V halogen bulb (about 20 W): V_RMS in
   10-16 V, P positive and within ±20% of the nameplate rating; with the bulb
   off, current within the absolute noise limit. Capture >=5 minutes on and
   >=1 minute off. Windows flagged only `calibration_missing` are admissible.
8. Every displayed and published value carries the "not validated" label derived
   from the calibration kind. Below-range/no-load current uses an absolute noise
   limit.
9. Hash and preserve raw waveform excerpts, summaries, scripts, environment,
   coefficients, and the plausibility table. Outside-range data is flagged.

### Experiment runs

Adopted 2026-11-25 from the team's Methodology revision (article AD-16) so the
specs and the article agree. The experimental unit is a run, not a 5 s summary.

| Test | Runs on | Runs and episodes | Evidence task |
|---|---|---|---|
| E1 plausibility (SC-001) | 12 V loop, bulb | 3 pilot runs on different days; final n is the smallest n ≤ 10 with n ≥ (t₀.₉₇₅,ₙ₋₁ · s / e)², s = standard deviation of d_P across runs, e = 5 percentage points | T064, T065 |
| E2 alerts (SC-004) | Simulator and 12 V loop | 60 simulator episodes (20 sustained, 20 brief surges shorter than `confirm_ms`, 20 below the limit) and 10 bulb episodes of 60 s (5 on, 5 off); each episode classified once as TP, FN, FP, or TN | T080, T087 |
| E3 latency (SC-002) | Real node, bulb on | 3 runs of 1 h; dashboard probe every 1 s, NTP-synchronized clocks | T104, T091 |
| E4 recovery (SC-003) | Real node | 3 runs with port 8883 blocked 10 min, plus 1 run with a reboot during the outage (marked gap expected) | T105, T091 |
| E5 busiest hour (SC-005) | Simulator dataset | 1 seven-day dataset; timed operator check | T074, T075 |

## Telemetry, Delivery, and Clock Design

The normative topics, fields, units, compatibility rules, and schemas are in
[contracts/README.md](contracts/README.md). MQTT 5 runs on TLS port 8883 with QoS
1. The node uses Clean Start false, 24-hour session expiry, 15-second keepalive,
retained offline last will, and stable client ID equal to node identity. The
ingestor uses a stable persistent session. Measurements/events/ACKs have a 24-hour
message expiry; status/config are retained.

The node writes a compact record to its RAM queue before publication and removes
it only after application `accepted` or `duplicate`. The queue survives network
and server outages, not node power loss; a reboot during an outage appears on the
server as a new `boot_id` and a reported data gap. The server records payload hash and
identity in SQLite, performs an idempotent Influx point write using observation
time, marks the ledger stored, then publishes the application ACK. Thus MQTT is
explicitly at least once while the accepted data has an exactly-once storage
effect. A reused ID with different bytes is rejected/quarantined as a conflict.
After reconnect, drain oldest first at >=2 records/s with <=10 in flight while
continuing to enqueue current observations.

SNTP UTC is authoritative; there is no RTC. `holdover` covers SNTP loss after a
sync in the same boot; after a cold restart, observations are `unsynchronized`
until the first sync. Window `end`
is the observation timestamp. Server adds receive/store times and calculates lag.
Energy uses monotonic time, so SNTP adjustment cannot add/subtract Wh. Queries sort
on observation time, then boot/sequence; they do not mistake arrival order for
physical order. Unsynchronized observations remain diagnostic and cannot be
`valid` evidence.

## Security Design

- Private lab CA with unique node and service leaf certificates. TLS 1.2 minimum;
  validate chain and server name. Disable anonymous MQTT and map certificate
  identity to ACL principal.
- Device ACL: publish only its own measurement/event/status; subscribe only to its
  own config/ACK. Ingestion has the inverse minimum permissions; admin identity is
  separate.
- Wired/trusted provisioning reads an ignored per-device manifest and writes
  credentials into encrypted NVS. Public CA certificates and redacted examples
  may be tracked; private CA key and leaf keys may not.
- Compose secrets mount credentials read-only at runtime. Grafana read,
  ingestion write, and setup/admin Influx tokens are separate. Logs and reject
  records contain hashes/reason codes rather than secret-bearing payload dumps.
- Caddy is the only dashboard ingress. Dashboard has one authenticated operator,
  no anonymous access/self-registration, and no direct browser MQTT connection.
  Host firewall restricts 443/8883 to configured trusted subnets; no public port
  forwarding or UPnP.
- Outbound notifications use HTTPS, a runtime-only token, stable `alert_id` for
  idempotency, bounded retries, and redacted error logs. Provider failure never
  blocks local warning or measurement storage.
- Local release gates (no CI service; run with `make` before merging and before
  each hardware session) include secret scanning, dependency and container-image
  scanning, certificate/ACL negative tests, and an external LAN port scan.

## Storage, Dashboard, Alerts, and Health

### Storage and retention

- `energy_raw`: one `electrical_measurement` point/5 seconds, 30-day retention.
  Tags: node, circuit, quality, calibration revision. UUID, boot, sequence, values,
  clock data, flags, and receive lag remain fields to avoid cardinality growth.
- `operations`: status, rejects, duplicate/conflict counts, queue/replay, stage
  health, notification delivery, and latency; 30-day retention.
- Optional reproducible hourly/daily rollups may retain one year. They record
  source interval/query revision and never replace raw records inside 30 days.
- SQLite WAL is backed up with the deployment volumes. Ledger and alert audit
  retain at least one year for the prototype; explicit maintenance handles later
  pruning. Destructive volume/retention commands are separate from normal stop.

### Dashboard panels

1. Identity/quality banner: node, circuit, online/stale/offline, calibration
   (with a permanent "not validated" label for `nominal` calibration), clock,
   last valid update and age.
2. Current cards: V RMS, A RMS, active W, import Wh/kWh, each with unit,
   timestamp, and quality.
3. Active-power time series with alert and data-gap annotations.
4. Voltage/current time series with calibrated-range bands.
5. Hourly energy bars and daily/weekly totals calculated from valid counter
   differences, never by summing cumulative totals.
6. Measurement quality: invalid/degraded windows, flags, clock state, gaps and
   calibration changes.
7. Alert table/history: evidence, severity, open/acknowledged/resolved state,
   notification state, and transition times.
8. Pipeline health: node heartbeat/queue, MQTT session, accept/reject/duplicate,
   ingest and storage latency/errors, datasource/query health, and dashboard age.

Grafana dashboards/datasources are file-provisioned and read-only. Stale and
offline states replace the current-value presentation; a previous measurement is
never displayed as if live.

### Threshold and alert lifecycle

Thresholds are changed by the authenticated local `energyctl` management command,
which validates a versioned YAML input, stores/audits it, and publishes the latest
retained config. A browser-based configuration editor is not part of the MVP.

Firmware evaluates only valid 1-second blocks:
`normal -> pending -> firing -> clearing -> resolved/normal`. Default confirmation
is ten seconds; clear threshold defaults to 95% of the limit and must remain below
the limit; clear duration prevents flapping. LED/buzzer is active during firing
and clearing. Invalid data pauses electrical confirmation and raises a distinct
quality event—it is not interpreted as zero or safe.

Ingestion turns immutable node events into an audited server alert:
`open -> acknowledged -> resolved`; open may resolve without acknowledgment.
Acknowledgment records operator receipt and does not clear the physical state.
The transactional outbox records notification delivery independently. The server
checks event config/value against stored configuration and nearby measurement;
disagreement becomes a health alert rather than silently changing the result.

### Health observability

- Node: ADC/DMA/sample-gap status, calibration, clock, energy continuity, Wi-Fi/MQTT,
  queue depth/oldest record, last ACK, firmware/build, restart reason.
- Broker: authenticated connections, queued/dropped messages, persistence state.
- Ingestion: received/accepted/rejected/duplicate/conflict, ledger states,
  validation reason, Influx/SQLite latency/error, notification backlog.
- Storage/dashboard: health/readiness, query/write errors, last successful point,
  datasource health, dashboard age.
- Logs are structured UTC JSON with component/event/node/message identity,
  result/reason and latency; never secrets. Internal liveness/readiness endpoints
  are container-only. Status heartbeat is 30 seconds; measurement stale at 15
  seconds; node offline at 30 seconds or authenticated last will.

## Future Dataset and Evaluation Design

The MVP does not train or serve models. Before the raw 30-day expiry, an export
job creates immutable daily Parquet snapshots from accepted measurements and a
manifest with exact query, UTC interval, schema/calibration/firmware revisions,
quality exclusions, controlled-load labels, file hashes, code commit,
and environment-lock hash. Raw snapshot, curated dataset, labels, and split
manifest remain separate; reruns create new versions.

Anomaly experiments split chronologically by complete days/load sessions and
compare against threshold and rolling robust baselines. Held-out metrics are
precision, recall, F1, false alerts/day, and detection delay, stratified by load
and quality. Forecast experiments use rolling-origin evaluation and compare with
last-value and seasonal-naive baselines using MAE, RMSE, WAPE and, if applicable,
prediction-interval coverage. Invalid, clock-uncertain, calibration-change, and
outage-replay intervals follow documented inclusion rules. Insufficient history
produces `insufficient data`, not a model result. A future specification must set
horizons and promotion thresholds before any result affects users.

## Test Strategy

No hardware is available yet, so firmware is tested on the development PC first
and on the board later. There is no CI service; every gate is a `make` target run
locally (decided 2026-11-25).

| Layer | What it covers | Runs on | Command |
|---|---|---|---|
| Firmware host unit tests | Metering, quality, energy, calibration math, clock states, threshold machine, config, queue, UI state, acquisition frame parsing (fake DMA frames), JSON serializer | PC (host build, Unity, AddressSanitizer and UndefinedBehaviorSanitizer) | `make firmware-test` |
| Reference calculation | `tests/fixtures/waveforms/reference.py` computes expected V RMS, I RMS, P (mean of v·i), and Wh for every fixture into `expected.json`; firmware host tests must match within stated tolerances | PC | part of `make firmware-test` |
| Firmware payload contract | Host-built serializer writes sample payloads; pytest validates them against `contracts/*.schema.json` | PC | `make contracts-test` |
| Server unit and property tests | Ledger, alerts, outbox, node status, `energyctl`, health API; Hypothesis properties (ledger idempotency, energy never decreasing, counter resets) | PC | `make server-test` |
| Migrations | Alembic upgrade and downgrade on an empty database | PC | `make server-test` |
| Contracts | Schemas, fixtures, topics, simulator output | PC | `make contracts-test` |
| Integration, recovery, security, acceptance | Compose stack with the simulator | PC (Docker) | `make test-integration`, `test-recovery`, `test-security`, `acceptance-simulated` |
| Evaluation scripts | `plausibility.py`, `performance.py`, export reproduction from a manifest, on fixtures with known answers | PC | `make test` |
| Static checks and hygiene | ruff, mypy, clang-format, gitleaks, `pip-audit`, container-image scan, coverage report (no threshold), pre-commit hooks | PC | `make lint`, `make deps-scan`, `make coverage` |
| On-target integration (later) | Same Unity tests and fixture replay on the ESP32-S3; bring-up apps; bench integration; 12 V loop session | Board ([HW]) | `make firmware-flash-test-fixtures` and build guide stages |

`make test` runs every fast PC gate (lint, firmware host tests, contracts,
server, evaluation). Pytest markers separate `unit`, `integration`, and `hw`.

## Requirement Traceability and Verification

| Requirement/outcome | Design element | Minimum verification evidence |
|---|---|---|
| FR-001–005, SC-001 | Alternating ADC with delay correction, formulas, quality, NVS checkpoint, calibration | Host waveform unit tests against reference values (including delay correction); sample-gap/restart injection; plausibility report (no reference meter) |
| FR-006, SC-002–003 | MQTT QoS 1, durable queue, ledger, app ACK | Duplicate/conflict tests; broker/ingestion/storage stops; timed 10-minute recovery report |
| FR-007 | mTLS, ACL, encrypted provisioning, LAN-only ingress | Anonymous/untrusted/wrong-topic negatives, secret scan, LAN port scan |
| FR-008 | Influx 30-day bucket | Provisioning assertion and retention API test |
| FR-009–010, FR-018, SC-005–006 | Eight dashboard groups and query rules; node OLED and status LED | Provisioning smoke test, golden queries, timed operator acceptance |
| FR-011–016, SC-004 | Versioned config, local state engine, event/alert/outbox | State transition tests, brief/sustained load tests, server-down local-warning test |
| FR-017 | Stage-specific status/logs/metrics | Fault injected at each stage and correctly identified on health view |
| Future analytics readiness | Immutable exports/manifests/splits/baselines | Reproduction test from manifest; no runtime model in MVP |

The implementation sequence should keep each vertical milestone independently
verifiable: contracts/simulator; server storage/dashboard; firmware calculations;
calibration; end-to-end recovery/security; then thresholds/alerts. Task generation
must preserve that dependency order and place the 12 V loop session after all
simulation and bench gates.

## Complexity Tracking

No constitution violations require justification. The second persistence engine
is not a waiver: InfluxDB stores high-volume time series, while embedded SQLite
provides the unique idempotency ledger and transactional alert/outbox state needed
for FR-006 and FR-014. Both remain on one host and behind one ingestion service.
