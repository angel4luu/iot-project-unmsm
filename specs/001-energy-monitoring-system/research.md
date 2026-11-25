# Phase 0 Research: Energy Monitoring System

**Feature**: `001-energy-monitoring-system`  
**Date**: 2026-10-14 (hardware amended 2026-11-18)  
**Status**: Complete for planning

This record resolves the technical unknowns in the feature specification. It is
not an electrical installation approval. The prototype remains a controlled,
single-phase laboratory instrument whose mains-facing design and assembly require
review by a qualified person before energization.

## R-001 Measurement range and sensing architecture

**Amended 2026-11-18 (plan B, 12 V AC MVP; supersedes the mains test path below
for the MVP).** No electrician or qualified reviewer is available, so the MVP
monitors an extra-low-voltage loop instead of a 220 V load. A certified,
thermally protected plug-in 220 V → 12 V AC adapter (iron-core, rated ≥ 2 A)
feeds one 12 V halogen bulb (G4 12 V 20 W or a 12 V car bulb) in series with
the ACS712 IP+/IP− terminals, using household cable and the kit's alligator
leads (or a small terminal strip). The same adapter output feeds the voltage
channel, so the node measures the loop's own voltage directly (no 220/12 ratio).
Proposed range: `10–16 V RMS`, `55–65 Hz`, `0.5–2.0 A RMS`, and about
`0–25 W`. Only the certified adapter touches the 220 V outlet, so the MVP has no
mains wiring, no RCD, no test box, no fuse (the adapter's thermal protection
limits a short), and no qualified-person review. The mains decision and safety
conditions below are kept for the future 220 V session and apply in full if it
is ever done.

**Amended 2026-11-18** (hardware adapted to the team's available kit; supersedes
the 2026-10-14 SCT-013-020/ZMPT101B decision).

**Mains decision (kept for the future 220 V session; the MVP uses the plan B
ranges above)**: Current is sensed with the team's `ACS712` Hall-effect module (the
load conductor passes through the module). Voltage is sensed with a certified,
isolated 220 V-to-9–12 V **AC-AC** plug-in adapter (AC output, not a DC charger);
it is the only sensing part bought. Bare or exposed ZMPT101B modules remain
rejected. The calibrated claim is narrowed to `180–250 V RMS`, `55–65 Hz`, and a
current range set by the ACS712 variant. The team's module is the
**`ACS712ELCTR-20A`** (confirmed 2026-11-18), so the claim is `0.5–5.0 A RMS`
and about `0–1,100 W`; the other rows are kept for reference:

| ACS712 variant | Sensitivity | Calibrated current | Calibrated power (approx.) |
|---|---|---|---|
| `ACS712ELCTR-05B` | 185 mV/A | `0.25–3.0 A RMS` (±5 A peak limit) | `0–650 W` |
| `ACS712ELCTR-20A` | 100 mV/A | `0.5–5.0 A RMS` | `0–1,100 W` |
| `ACS712ELCTR-30A` | 66 mV/A | `0.5–5.0 A RMS` | `0–1,100 W` |

The test path stays protected at 10 A. Values outside the calibrated range may be
observed but MUST carry `out_of_range` and are outside the plausibility
range (R-004). Peaks beyond
the sensor or ADC span (for example high-crest-factor nonlinear loads) MUST raise
`clipping`.

**Rationale**: The project is an educational demonstration and the team already
owns an ACS712 and two ESP32-S3 boards. A comparable ACS712 + microcontroller-ADC
design is reported in the literature with sub-5% RMS error under controlled
conditions, so the design is reasonable when the range is narrowed to the
sensor's useful resolution (this project itself claims no accuracy; R-004). A certified plug-in AC-AC adapter keeps all custom voltage
sensing on the low-voltage side and is cheaper and safer than a custom ZMPT board.

**Safety conditions for the ACS712 on mains (future 220 V session only;
non-negotiable then)**: the ACS712 is the only
part whose terminals carry mains, so the module sits alone in a closed,
touch-safe, flame-retardant test box (a measuring extension cord, amended
2026-11-18) with strain relief and covered terminals; only its low-voltage
header leaves that box. It is never
mounted on a solderless breadboard and never handled while energized. The
low-voltage conditioning and peripherals, by contrast, may be assembled on a
solderless breadboard (amended 2026-11-18), since they are separated from mains
by the certified adapter and the ACS712 isolation barrier. The
qualified reviewer MUST check the specific module's creepage/clearance between
the mains terminal and the low-voltage pins, the conductor rating, and the
enclosure before energization. While energized, the ESP32-S3 is powered from a
certified charger and data leaves only over Wi-Fi; a USB connection to a
mains-earthed computer is not used unless the reviewer approves it.

**Alternatives rejected**:

- `SCT-013-020` + `ADS131M02` (previous decision): better metrology and a
  clamp-on, non-invasive current path, but both are purchases and the external ADC
  adds board work; not justified for the educational scope. Retained as the
  documented upgrade path.
- Bare/generic `ZMPT101B` module: component ratings, layout, creepage, and output
  compatibility are not sufficiently controlled.
- `PZEM-004T` metering module: hides the sampling and active-power algorithm the
  project must demonstrate (FR-003).

**Sources**: [Peru supply description](https://www.gob.pe/que/29306-informacion-general-sobre-lima),
[ACS712 datasheet](https://www.allegromicro.com/-/media/files/datasheets/acs712-datasheet.ashx),
[RMS benchmark with ACS712 (Marin et al., 2026)](https://doi.org/10.3390/electricity7030077).

## R-002 Isolation, protection, and analog conditioning

**Amended 2026-11-18.**

**Decision**: Use the ESP32-S3's internal ADC1 (ADC2 conflicts with Wi-Fi) in
continuous DMA mode with an alternating two-channel pattern at 8,000 conversions/s,
giving 4,000 voltage/current pairs/s. The fixed inter-channel delay (one
conversion, 125 µs, about 2.7° at 60 Hz) is removed by the fractional-sample
phase correction. Without a reference meter (R-004) the adapter's and sensor's
own phase shift stays uncorrected; on resistive loads its effect on active power
is small (cos 3° ≈ 0.999), and on other loads P is only observed. Apply
Espressif's ADC calibration scheme, then per-device offset and gain calibration;
keep both signals inside the ADC's linear mid-range at the chosen attenuation.

Conditioning (final values set at the bench and in the schematic review):

- **Voltage**: the floating adapter output is referenced to a mid-supply bias
  (two equal resistors of about 10 kΩ plus a 10 µF capacitor) and divided by
  about 1/22 (100 kΩ / 4.7 kΩ) → small RC anti-alias filter → ADC1.
- **Current**: ACS712 output (centred at VCC/2, powered from 5 V) → resistor
  divider into the 3.3 V-safe range with total load of at least 4.7 kΩ (ACS712
  minimum load) → RC filter → ADC1.
- The team's 470 Ω and 1 kΩ resistors are too low for these networks; a low-cost
  resistor assortment (10 kΩ–100 kΩ) and a few 10 µF capacitors are bought.

*Amended 2026-11-18 (plan B)*: the MVP has no mains wiring (R-001), so the
requirements in the next sentence apply only to a future 220 V session. On the
12 V loop the conditioning network is unchanged (the 12 V adapter output is
what R1/R2 were sized for); only the firmware voltage gain changes, and the
load loop (about 1.7 A) runs through cable and clips, never through the
breadboard. *Amended 2026-11-18 (minimal MVP, no laboratory available)*: an
energized mains prototype requires a 30 mA RCD/GFCI protecting the test outlet (the device already in the building's
electrical panel if present, otherwise a certified plug-in portable RCD) and the
outlet's existing branch-circuit breaker as overcurrent protection, accepted
only if the qualified reviewer confirms that the test cable, terminals, and
ACS712 module are rated for that breaker, the certified isolated adapter for voltage, a certified
low-voltage supply for the node, the enclosure conditions in R-001, and no mains
wiring on breadboards or flying leads. A qualified person MUST review the
schematic, parts' ratings, creepage/clearance, conductor sizing, enclosure, and
test setup before energization.

**Rationale**: Alternating sampling with a known, constant delay is a documented
phase-correction method, so FR-003 (active power as mean of v·i from synchronized
observations) is still met. The internal ADC is the main accuracy risk; it is
handled by calibration, by narrowing the range (R-001), and by averaging 20,000
pairs per summary.

**Alternative rejected**: External simultaneous ADC (`ADS131M02`): removes
multiplexing skew and offers CRC-checked SPI, but is a purchase and extra board
work; retained as the upgrade path. The contract flag `adc_crc_error` stays in
schema 1.0.0 for compatibility but is not emitted by the internal ADC.

**Sources**: [ESP32-S3 ADC continuous mode](https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/api-reference/peripherals/adc_continuous.html),
[ESP32-S3 ADC calibration](https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/api-reference/peripherals/adc_calibration.html),
[ACS712 datasheet](https://www.allegromicro.com/-/media/files/datasheets/acs712-datasheet.ashx).

## R-003 Sampling, quantities, and energy continuity

**Decision**: Acquire synchronized voltage/current pairs continuously at 4 kS/s.
Remove offset and apply calibrated gain and fractional phase correction. Calculate
1-second internal blocks for quality and local-alert evaluation; publish a
5-second summary accumulated from all valid sample pairs.

For calibrated instantaneous values `v[n]` and `i[n]`:

```text
voltage_rms_V = sqrt(sum(v[n]^2) / N)
current_rms_A = sqrt(sum(i[n]^2) / N)
active_power_W = sum(v[n] * i[n]) / N
delta_energy_Wh = active_power_W * monotonic_elapsed_seconds / 3600
active_energy_import_Wh += max(active_power_W, 0) * dt / 3600
```

Active power is signed internally to detect reversed sensor polarity. Sustained
negative power raises `polarity_reversed`; it is not silently converted into
consumption. Energy integration uses monotonic time and is never adjusted by a
wall-clock correction.

*Amended 2026-11-18 (no FRAM)*: the energy total is checkpointed to NVS (internal
flash) every 60 seconds as double-buffered records with sequence number and CRC,
and on orderly shutdown. After an unexpected restart the counter resumes from the
last checkpoint and the gap since that checkpoint is reported as an uncertain
interval (FR-005). Pending telemetry is held in a RAM ring buffer of at least 256
compact summaries (more than 21 minutes), sufficient for the specified 10-minute
communications outage. A power loss or reboot during an outage loses the unsent
summaries; the server sees the new `boot_id` and sequence gap and reports it as a
data gap, never as zero consumption.

**Rationale**: High-rate paired samples are necessary to distinguish active power
from apparent power. One-second blocks meet local warning latency while 5-second
messages limit network and storage load. A 60-second NVS checkpoint keeps flash
wear acceptable for a prototype campaign without extra hardware.

**Alternative rejected**: `Vrms * Irms` is apparent power and MUST NOT be labeled
active power. Wall-clock differences are unsafe for integration because SNTP
corrections can jump.

**Sources**: [ESP-IDF NVS](https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/api-reference/storage/nvs_flash.html),
[ESP-IDF system time](https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-reference/system/system_time.html).

## R-004 Calibration and measurement evidence

**Amended 2026-11-18 (constitution 2.0.0): no reference meter.** Supersedes the
earlier true-RMS reference, guard-band, and series-connection decisions.

**Decision**: The demonstration build runs on **nominal coefficients** and makes
no accuracy claim. Voltage gain comes from the adapter's rated ratio and the
R1/R2 divider; current gain from the ACS712-20A datasheet sensitivity
(100 mV/A) and the R3/R4 divider (plan B: the voltage gain uses only R1/R2,
because the node measures the 12 V adapter output itself); the phase correction from the known sampling
offset between the two channels (one conversion period, 125 µs at 8,000
conversions/s).
Procedure: warm up for 10 minutes; at no load, measure zero for 60 seconds and
store the ACS712 offset (repeated before every session); switch on a resistive
load and confirm that active power is positive (otherwise correct the sign in the
coefficients); freeze the nominal calibration revision. Record hardware/firmware/
calibration revisions, operator, date, wiring, sensor identity and variant, ADC
configuration, load identity and nameplate rating, and the statement that no
reference instrument was used.

Plausibility evaluation (SC-001, amended for plan B) uses one stable resistive
12 V halogen bulb (about 20 W): the RMS voltage must lie in 10–16 V, active
power must be positive, and active power must fall within ±20% of the nameplate
rating; with the bulb off, current must fall to the absolute noise limit. The
±20% band is a working allowance for the nominal error of the chain plus the
spread between the nameplate and the actual draw; it is wider than the earlier
mains band (±15%) because a plug-in adapter's loaded voltage is often 5–10%
above 12 V and halogen power rises faster than voltage. It is a plausibility
band, not an accuracy limit. No inductive load is used in the MVP. During the
plausibility session, windows whose only quality flag is `calibration_missing`
(the server has not yet registered the nominal revision) are admissible
evidence; any other flag makes the window inadmissible. Collect at least five
minutes per point. No-load behavior uses an absolute noise threshold. Every
displayed and published value carries the "not validated" label, which the
server derives from the calibration artifact's kind (`nominal`). Preserve raw
waveform excerpts, calculated blocks, summaries, coefficients, scripts, and
hashes.

**Rationale**: Without a reference instrument, the honest outcome is a working,
reproducible demonstration whose readings are plausible but not validated
(constitution II). Nominal coefficients plus offset zeroing and the polarity check
need no extra hardware. A nameplate is not a reference (it varies with the actual
wall voltage and manufacturing spread), so it supports only a plausibility check.
A team that later obtains a true-RMS meter can add a `reference` calibration
revision and the original 5% acceptance without changing the hardware.

**Sources**: [ADE7953 calibration guidance](https://www.analog.com/cn/resources/app-notes/an-1118.html),
[ACS712 datasheet](https://www.allegromicro.com/-/media/files/datasheets/acs712-datasheet.ashx).

## R-005 Clock and timestamp model

**Amended 2026-11-18** (no external RTC).

**Decision**: SNTP UTC is authoritative. There is no battery-backed RTC:
`holdover` now means that after a successful SNTP sync in the current boot, the
system clock keeps running on the internal oscillator while SNTP is unreachable,
with the last-sync age reported. After a cold restart, observations are
`unsynchronized` (diagnostic only, never `valid` evidence) until the first SNTP
sync. Every measurement states `sntp`, `holdover`, or `unsynchronized`, plus the
last synchronization age. The observation timestamp is the end of the measurement
window in RFC 3339 UTC with milliseconds. The server adds `received_at` and
`stored_at`; ordering and deduplication use observation time together with
`boot_id`, `sequence`, and immutable `message_id`. The contract enum is unchanged.

**Rationale**: The three timestamps separate physical observation, network delay,
and persistence delay. Explicit clock quality prevents an unsynchronized value
from appearing trustworthy. The node starts on the lab Wi-Fi, so the unsynchronized
period after boot is normally a few seconds; an RTC is the upgrade path if it is not.

**Sources**: [RFC 3339](https://www.rfc-editor.org/info/rfc3339/),
[ESP-IDF system time](https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-reference/system/system_time.html).

## R-006 Telemetry protocol and recovery

**Decision**: Use MQTT 5 over TLS on port 8883. Topics are:

```text
unmsm/energy/v1/nodes/{node_id}/measurements
unmsm/energy/v1/nodes/{node_id}/events
unmsm/energy/v1/nodes/{node_id}/status
unmsm/energy/v1/nodes/{node_id}/config
unmsm/energy/v1/nodes/{node_id}/acks/measurements
```

All messages use QoS 1. Retain only status and config; never retain measurements
or events. The node uses stable client identity, Clean Start false, 24-hour
session expiry, 15-second keepalive, retained offline last will, and 24-hour
message expiry. JSON payloads follow the versioned Draft 2020-12 contracts under
`contracts/` and stay below 16 KiB.

The node persists a record before publish and deletes it only after an application
ACK (`accepted`, `duplicate`, or terminal `rejected`) received after storage. The
server enforces unique `message_id`; reconnect drains oldest first at at least two
records/s with at most ten in flight. This gives at-least-once transport and an
exactly-once storage effect. A rejected record is retained in a bounded local
diagnostic/dead-letter area and raises health state rather than retrying forever.

**Rationale**: MQTT QoS 1 alone can duplicate delivery and its broker ACK does not
mean the database committed. The explicit application ACK makes the recovery
criterion observable and testable.

**Alternatives rejected**:

- QoS 0: cannot support recoverable delivery.
- QoS 2 alone: still does not prove application persistence and adds protocol
  complexity.
- Retained telemetry: makes stale data look current and is unnecessary with
  storage.

**Sources**: [MQTT 5.0 standard](https://docs.oasis-open.org/mqtt/mqtt/v5.0/mqtt-v5.0.html),
[ESP-MQTT documentation](https://docs.espressif.com/projects/esp-idf/en/v5.4/esp32/api-reference/protocols/mqtt.html),
[JSON](https://www.rfc-editor.org/info/rfc8259/),
[JSON Schema Draft 2020-12](https://json-schema.org/draft/2020-12).

## R-007 Authentication, secrets, and network exposure

**Decision**: Operate a private laboratory CA. Give each node and service its own
certificate and key. Mosquitto requires client certificates, maps certificate
identity to the MQTT username, disables anonymous access, applies per-topic ACLs,
and accepts TLS 1.2 or newer. Devices may write only their own measurements,
events, and status and read only their own config and ACK topic.

Provision node credentials through a trusted wired flashing workflow from an
ignored per-device manifest. Store them in encrypted NVS; commit only the public
CA certificate and placeholder examples. Inject server secrets at runtime from
ignored files with restrictive permissions. Logs redact credentials and tokens.

Bind MQTT only to the device/laboratory LAN and firewall it to the device subnet.
Keep ingestion and databases on an internal container network. Expose only the
dashboard HTTPS endpoint on the trusted LAN, with one authenticated operator
account. Do not use public port forwarding, UPnP, public DNS, or browser-to-MQTT.
The notification worker may make outbound HTTPS requests only.

**Rationale**: Per-principal credentials and network segmentation limit the effect
of one compromise. Runtime injection satisfies the constitution's no-secret rule.

**Sources**: [Mosquitto configuration](https://www.mosquitto.org/man/mosquitto-conf-5.html),
[ESP-IDF security overview](https://docs.espressif.com/projects/esp-idf/en/stable/esp32/security/security.html),
[ESP-IDF flash encryption](https://docs.espressif.com/projects/esp-idf/en/stable/esp32/security/flash-encryption.html).

## R-008 Server platform, storage, and deployment

**Decision**: Run a reproducible Docker Compose deployment on one Linux host:
Mosquitto 2.1.2, a Python 3.14.8 ingestion/alert worker, InfluxDB OSS 2.9.1 for measurements, SQLite WAL
for the ingestion ledger/configuration/alert audit/outbox, Grafana for read-only
views (Grafana OSS 13.2.3), and Caddy for authenticated LAN-only HTTPS. Pin image digests or exact
versions and Python dependencies.

The worker validates JSON Schema, checks identity/topic agreement, applies an
idempotent persistence state machine, writes time-series data, evaluates remote
threshold state, creates notification outbox rows, and sends the application ACK.
SQLite is authoritative for discrete lifecycle state; InfluxDB is authoritative
for time series. Raw five-second telemetry has a 30-day retention policy. Hourly
and daily aggregates may be retained for one year but are derived, reproducible,
and never replace raw evidence during the 30-day window.

**Rationale**: InfluxDB and Grafana match time-series visualization needs, while a
small relational ledger supplies uniqueness and auditable state transitions that
a time-series store does not model cleanly. One host fits the single-node academic
scope and keeps deployment reproducible.

**Alternatives rejected**:

- Cloud-managed stack: adds public exposure, cost, and external availability to a
  LAN-scoped MVP.
- InfluxDB alone: poor fit for alert transitions, outbox transactions, and a
  durable idempotency ledger.
- PostgreSQL plus a time-series extension: capable but operationally heavier than
  required for one node.

**Sources**: [InfluxDB retention](https://docs.influxdata.com/influxdb/v2/reference/internals/data-retention/),
[InfluxDB releases](https://github.com/influxdata/influxdb/releases),
[Mosquitto releases](https://mosquitto.org/blog/),
[Python 3.14.8 release](https://www.python.org/downloads/release/python-3148/),
[Grafana OSS 13.2.3](https://grafana.com/grafana/download/13.2.3?edition=oss),
[Grafana provisioning](https://grafana.com/docs/grafana/latest/administration/provisioning/),
[Grafana alert provisioning](https://grafana.com/docs/grafana/latest/alerting/set-up/provision-alerting-resources/file-provisioning/).

## R-009 Dashboard, alerts, and health

**Decision**: Provision dashboard and datasource definitions from version control.
The main dashboard contains current V/I/P/import-energy cards with units and
quality, last-valid-update and clock status, active-power trend, voltage/current
trend, hourly/daily energy, quality-gap panel, active/resolved alert table, and
ingestion/recovery health. Never render a stale last value as live.

The node evaluates 1-second power blocks with state
`normal -> pending -> firing -> resolved`, using a default 10-second confirmation
and explicit 95% clear threshold/duration. LED/buzzer activates only in `firing`.
The server alert is `open -> acknowledged -> resolved`; acknowledgment records
operator receipt and does not electrically clear the condition. Every transition
is audited. Notifications use a transactional outbox and stable `alert_id` as the
idempotency key.

Publish retained status and a 30-second heartbeat. Mark telemetry stale at 15
seconds and node offline at 30 seconds or on last will. Expose structured logs and
metrics for acquisition gaps, invalid windows, queue depth, clock state, MQTT
reconnects, validation rejects, duplicates, ingest/storage latency, notification
failures, datasource health, and dashboard age.

**Rationale**: Separate physical condition, user acknowledgment, delivery, and
component health states prevent misleading alert semantics and local/remote
coupling.

## R-010 Future analytics dataset and evaluation

**Decision**: No anomaly or forecast model executes in the MVP. The MVP collects
validated five-second telemetry, quality flags, calibration revision, clock
quality, threshold events, and controlled experiment labels. A later feature
exports immutable Parquet datasets plus a manifest containing source query,
interval, exclusions, schema/calibration versions, hashes, code revision, and
environment lockfile.

For anomaly research, define event labels and tolerance windows before training;
split chronologically by complete experiment/day with no window leakage. Compare
against simple threshold and rolling robust-z baselines. Report precision, recall,
F1, false alerts/day, and detection delay on held-out data, stratified by load and
quality. For forecasting, compare against last-value and seasonal-naive baselines
using rolling-origin backtesting; report MAE, RMSE, and WAPE with prediction
horizon and coverage. Exclude invalid/unsynchronized data by declared rules rather
than silent cleaning. Record random seeds where applicable.

**Rationale**: Collection now avoids an unusable historical dataset, but model
claims require a separate specification, adequate history, held-out evaluation,
and explicit promotion criteria.

**Alternative rejected**: Random row splits leak adjacent time windows and inflate
results; training on unvalidated data makes an apparently accurate model inherit
measurement faults.

## R-011 Software baseline and verification

**Decision**: Firmware uses C/C++ with ESP-IDF 5.4 LTS and its Unity test support.
Server code uses Python 3.14.8 with Pydantic/JSON Schema validation, Paho MQTT,
InfluxDB client, SQLAlchemy/Alembic, Prometheus client, and pytest. Infrastructure
is Docker Compose with pinned container images. Exact patch versions and hashes
are fixed in implementation lockfiles.

*Amended 2026-11-25*: no hardware is available yet and no CI service is used.
Firmware calculation and state logic is kept free of hardware calls and built for
the development PC (ESP-IDF host build with Unity; ADC, NVS, I²C, and MQTT behind
thin interfaces with fakes), so it is tested without a board; the same tests later
run on the ESP32-S3. Expected results come from an independent Python reference
calculation, and firmware-generated payloads are validated against the JSON
Schemas. All gates are local `make` targets (plan › Test Strategy).

Verification layers are calculation unit tests with recorded waveform fixtures,
JSON Schema contract tests, broker/ingestion/storage integration tests, outage and
clock-fault injection, dashboard provisioning checks, secret scanning, and
plausibility checks on the 12 V bulb loop (no reference meter, R-004). Hardware-in-the-loop tests are separately
marked because they need the physical prototype.

**Rationale**: These tools have stable support for the selected device, protocol,
storage, and reproducible local deployment, while keeping the repository split
along independently testable boundaries.
