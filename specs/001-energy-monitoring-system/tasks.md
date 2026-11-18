---
description: "Dependency-ordered task list for the energy monitoring MVP"
---

# Tasks: Intelligent Electrical Energy Monitoring System

**Input**: Design documents from `specs/001-energy-monitoring-system/` (spec, plan,
research, data-model, contracts, quickstart) and `.specify/memory/constitution.md`
(2.0.0).

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/.

**Tests**: Included. The constitution (V, VII) and the plan's Testing and
Traceability sections require contract, unit, integration, recovery, security,
and acceptance evidence, so each story starts with its tests.

**Organization**: Tasks are grouped by user story. Two tracks run in parallel
from Phase 2 onward and meet in the integration tasks of each story:

- **Hardware track** (build guide stages 1–6): firmware bring-up apps on the
  breadboard, then the full firmware, the safety review, and the supervised
  nominal calibration and plausibility check.
- **Software track**: contracts, simulator, server stack, and dashboard, testable
  without any hardware.

Constraints carried into every task: no reference meter (constitution 2.0.0) —
every displayed and published value is labeled "not validated" and no accuracy
figure is claimed; no relay or automatic cutoff (FR-016); no secrets or real
endpoints in tracked files (constitution IV); mains work only after the signed
qualified review (constitution I); project procedures live in `guides/`
(`docs/` is git-ignored local material).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on unfinished tasks)
- **[Story]**: US1, US2, US3 (spec.md user stories)
- **[HW]** in a description marks a task that needs the physical prototype

## Path Conventions

Paths follow plan.md › Project Structure: `firmware/`, `services/ingestion/`,
`infrastructure/`, `dashboards/`, `config/`, `experiments/`, `tests/`, `guides/`,
plus `scripts/` for developer tooling.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Repository baseline and tooling for both tracks.

- [ ] T001 Verify `.gitignore` keeps `.specify/` and `specs/` tracked (plan › Project Structure) and add ignores for `infrastructure/secrets/*` except `README.example.md`, `firmware/build/`, `firmware/sdkconfig`, `*.sqlite*`, `experiments/data/`, and `**/secrets.local*` in `.gitignore`
- [ ] T002 Create the source tree from plan.md › Project Structure (`firmware/`, `services/ingestion/`, `infrastructure/`, `dashboards/queries/`, `config/`, `experiments/{export,manifests,evaluation}/`, `tests/{contract,integration,recovery,security,acceptance,fixtures/{waveforms,telemetry,plausibility}}/`, `guides/{architecture,safety,calibration,operations,experiments}/`, `scripts/`) with a one-line `README.md` in each top-level folder
- [ ] T003 Create the root `Makefile` with documented placeholder targets from quickstart.md: `dev-certs`, `secrets-scan`, `contracts-test`, `infra-config-check`, `infra-up`, `infra-health`, `infra-down`, `simulate`, `acceptance-simulated`, `test-integration`, `test-recovery`, `test-security`, `firmware-test`, `firmware-build`, `firmware-flash-test-fixtures`
- [ ] T004 [P] Create `.env.example` with non-secret placeholders only (LAN bind address, trusted subnet CIDR, ports 443/8883, timezone `America/Lima`) and `infrastructure/secrets/README.example.md` listing every secret file name (CA key, leaf keys, Influx tokens, Grafana password, Wi-Fi credentials, notification token) without values
- [ ] T005 [P] Initialize `services/ingestion/pyproject.toml` for Python 3.14 with Paho MQTT, Pydantic, `jsonschema`, InfluxDB client, SQLAlchemy, Alembic, FastAPI, pytest, hypothesis, ruff; lock with `uv` into `services/ingestion/uv.lock`
- [ ] T006 [P] Initialize the ESP-IDF 5.4 LTS project in `firmware/CMakeLists.txt`, `firmware/sdkconfig.defaults` (target esp32s3, encrypted NVS, MQTT 5, SNTP) and empty components `firmware/components/{acquisition,calibration,metering,quality,persistence,threshold,telemetry,ui}/`
- [ ] T007 [P] Add the secret-scanning gate (`gitleaks` config) in `.gitleaks.toml` and wire it to `make secrets-scan` in `Makefile`
- [ ] T008 [P] Add ruff and pytest configuration in `services/ingestion/pyproject.toml` and clang-format settings in `firmware/.clang-format`

**Checkpoint**: Empty but buildable skeleton; `make secrets-scan` passes.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Contracts, server boundary, simulator, and firmware/board foundations
that every story needs. **No user story work starts before this phase is done.**

### Contracts (software track)

- [ ] T009 [P] Add valid and invalid fixtures for status, event, config, and ACK in `tests/fixtures/telemetry/{valid,invalid}-{node-status,node-event,threshold-config,measurement-ack}.json` (no real node IDs, endpoints, or secrets)
- [ ] T010 Write the contract test suite in `tests/contract/test_schemas.py`: every schema in `specs/001-energy-monitoring-system/contracts/` validates its valid fixtures, rejects its invalid fixtures, the measurement invalid fixture fails "for missing units and an unrecognized field", and payloads above 16 KiB are rejected
- [ ] T011 Write the topic/identity contract test in `tests/contract/test_topics.py`: topic `unmsm/energy/v1/nodes/{node_id}/…`, payload `node_id`, and certificate identity "MUST agree" (contracts/README.md)
- [ ] T012 Implement Pydantic models mirroring the five schemas (validation still delegated to `jsonschema` against the normative files, no divergent copies) in `services/ingestion/src/energy_ingestion/contracts/models.py` and `services/ingestion/src/energy_ingestion/contracts/validate.py`
- [ ] T013 Wire `make contracts-test` to run `tests/contract/` in `Makefile`

### Server boundary (software track)

- [ ] T014 Write `scripts/dev-certs.sh`: private lab CA, broker, ingestion, admin, simulator, and node leaf certificates into the ignored `infrastructure/secrets/`, owner-only permissions; wire `make dev-certs`
- [ ] T015 [P] Write `infrastructure/mosquitto/mosquitto.conf` (MQTT 5, TLS 1.2+ on 8883, `require_certificate true`, `use_identity_as_username true`, no anonymous) and `infrastructure/mosquitto/acl` (node publishes only its own measurements/events/status and subscribes only to its own config/acks; ingestion has the inverse; admin separate)
- [ ] T016 [P] Write `infrastructure/influxdb/setup.sh` creating buckets `energy_raw` and `operations` with 30-day retention and separate Grafana-read, ingestion-write, and admin tokens written only to `infrastructure/secrets/`
- [ ] T017 [P] Write `infrastructure/caddy/Caddyfile`: HTTPS on 443 as the only dashboard ingress, authenticated, proxy to Grafana on the Compose network
- [ ] T018 [P] Write Grafana provisioning `infrastructure/grafana/provisioning/datasources/influxdb.yaml` (read-only token) and `infrastructure/grafana/provisioning/dashboards/dashboards.yaml` (file-provisioned, read-only, no anonymous access, no self-registration)
- [ ] T019 Write `infrastructure/compose.yaml` with exact tags Mosquitto 2.1.2, InfluxDB 2.9.1, Grafana 13.2.3, Caddy 2 (pinned), the ingestion service, Compose secrets mounted read-only, and only 8883/443 published; freeze digests in `infrastructure/compose.lock.yaml`
- [ ] T020 Implement `make infra-config-check`, `infra-up`, `infra-health`, `infra-down` in `Makefile` using `scripts/infra-health.sh` (broker, Influx, Grafana, Caddy, ingestion readiness)
- [ ] T021 Create the SQLite schema with Alembic in `services/ingestion/migrations/versions/0001_initial.py`: tables `monitoring_node`, `circuit`, `calibration_artifact` (with `calibration_kind` enum `nominal`/`reference`, `reference_meter_id` nullable "Null for `nominal`"), `threshold_configuration`, `ingestion_ledger` (`message_id` PK, unique `(node_id, boot_id, sequence)`, `state` in `received`/`stored`/`rejected`), `alert`, `alert_transition` (append-only), `notification_outbox`; WAL mode
- [ ] T022 Implement the persistence layer in `services/ingestion/src/energy_ingestion/persistence/{db.py,ledger.py,influx.py}` (SQLAlchemy session, ledger repository, idempotent Influx point write keyed on observation time with tags `node_id`, `circuit_id`, `quality`, `calibration_revision` only)
- [ ] T023 Implement structured UTC JSON logging (component, event, node, message identity, result/reason, latency; never secrets) in `services/ingestion/src/energy_ingestion/logging.py`

### Simulator (software track)

- [ ] T024 Implement the node simulator in `services/ingestion/src/energy_ingestion/cli/simulate.py`: dedicated test certificate, schema-valid 5 s windows, status every 30 s, retained last will, and scenarios `normal`, `surge`, `sustained`, `invalid`, `outage`, `duplicate`, `out_of_order`, `clock_holdover`; every window uses a `nominal` calibration revision
- [ ] T025 Wire `make simulate SCENARIO=… DURATION=…` to `services/ingestion/src/energy_ingestion/cli/simulate.py` in `Makefile`

### Firmware and board foundations (hardware track)

- [ ] T026 [P] Define the board pin map from plan.md › Front end and pin allocation in `firmware/main/board.h` (GPIO4 ADC1_CH3 voltage, GPIO5 ADC1_CH4 current, GPIO8/9 OLED I²C, GPIO16 buzzer, GPIO17/18/21 RGB; never GPIO0/3/45/46, 19/20, 35–37)
- [ ] T027 [P] [HW] Bring-up app for build guide stage 1 (board alone: boot, Wi-Fi join, RGB cycles red/green/blue) in `firmware/bringup/stage1_board/main/main.c`
- [ ] T028 [P] [HW] Bring-up app for build guide stage 2 (OLED test text, buzzer 200 ms beep via 2N2222, RGB per colour) in `firmware/bringup/stage2_peripherals/main/main.c`
- [ ] T029 [P] [HW] Bring-up app for build guide stages 3–4 (raw ADC logger: alternating GPIO4/GPIO5 continuous mode at 8,000 conversions/s; prints mean/min/max in mV over USB; reports Vb ≈ 1.65 V with the adapter unplugged and the ACS712 offset ≈ 1.70 V with no current; can dump a raw capture) in `firmware/bringup/stage34_adc_logger/main/main.c`
- [ ] T030 [P] Implement encrypted-NVS credential provisioning from an ignored per-device manifest in `firmware/components/telemetry/provisioning.c` and `scripts/provision-node.py`
- [ ] T031 [P] Implement the clock module (SNTP UTC, `sntp`/`holdover`/`unsynchronized`, monotonic uptime) in `firmware/components/telemetry/clock.c`
- [ ] T032 [P] Implement the Unity test runner and waveform-fixture loader in `firmware/test/main/test_main.c` and `firmware/test/fixtures/README.md`; wire `make firmware-test` and `make firmware-build`
- [ ] T033 [P] Generate synthetic waveform fixtures (pure sine at 220 V/2.3 A in phase, 60° lag, DC offset, clipping, sample gap, no current) in `tests/fixtures/waveforms/generate.py` with outputs in `tests/fixtures/waveforms/*.csv`
- [ ] T034 Annotate build guide stages 1–4 with the bring-up app each stage uses (T027–T029) in `hardware/build-guide.md`

**Checkpoint**: `make contracts-test`, `make infra-up`/`infra-health`, `make simulate SCENARIO=normal` run; bring-up apps pass build guide stages 1–4 on the breadboard (no mains).

---

## Phase 3: User Story 1 — Monitor electrical consumption in real time (Priority: P1) 🎯 MVP

**Goal**: The user sees V RMS, A RMS, active W, and import Wh with timestamp,
quality, and the "not validated" label, from the simulator first and then from the
real node, within 10 s.

**Independent Test**: Simulator: `make acceptance-simulated` shows values, labels,
and ≥95% of summaries visible ≤10 s (SC-002 part). Hardware: on the supervised
setup, three resistive household loads meet the SC-001 plausibility check (V in
180–250 V, P > 0, within ±15% of nameplate) and invalid readings are never shown
as plain values (scenario 3, SC-006).

### Tests for User Story 1

- [ ] T035 [P] [US1] Firmware unit tests for RMS, active power as mean of v·i (FR-003; never Vrms·Irms), fractional phase correction of the one-conversion offset, and negative power raising `polarity_reversed` without decrementing energy, using T033 fixtures, in `firmware/test/main/test_metering.c`
- [ ] T036 [P] [US1] Firmware unit tests for quality classification (`valid` requires "all four values, accepted calibration, synchronized or permitted holdover clock, no clipping/sample-gap/disconnect/out-of-range flag, and `valid_sample_ratio >= 0.99`"; `invalid` quantities are null and never copied from the last valid record) in `firmware/test/main/test_quality.c`
- [ ] T037 [P] [US1] Firmware unit tests for monotonic-time Wh integration and NVS checkpoint recovery (`energy_continuity_uncertain` after an unclean restart; new `counter_id` only when continuity cannot be established) in `firmware/test/main/test_energy.c`
- [ ] T038 [P] [US1] Firmware unit test for the LED/OLED state mapping (plan › Local indication: green/red/yellow/blue/white; a non-`valid` value never shown as a plain reading) in `firmware/test/main/test_ui_state.c`
- [ ] T039 [P] [US1] Ingestion unit tests: schema/identity validation, ledger transitions `new -> received -> stored`, `new -> rejected`, `stored -> stored` (duplicate ACK), conflict on same ID with different hash, and "The application ACK is published only from `stored` or `rejected`", in `services/ingestion/tests/test_ledger.py`
- [ ] T040 [P] [US1] Ingestion integration test: crash between Influx write and ledger `stored` repeats the idempotent write on recovery, in `tests/integration/test_crash_recovery.py`
- [ ] T041 [P] [US1] Dashboard provisioning smoke test (datasource healthy, dashboard loads, "offline / no data" with no node, never zeros or a fabricated last value) in `tests/integration/test_dashboard_provisioning.py`
- [ ] T042 [US1] Simulated acceptance test: values carry unit, timestamp, quality, calibration revision, and the "not validated" label; ≥95% visible ≤10 s over 1 h (SC-002), in `tests/acceptance/test_us1_realtime.py`; wire `make acceptance-simulated`

### Firmware implementation for User Story 1 (hardware track)

- [ ] T043 [US1] Implement acquisition (ADC1 continuous DMA, alternating GPIO4/GPIO5 at 8,000 conversions/s = 4,000 pairs/s, Espressif calibration scheme, DMA overrun or missing conversion → `sample_gap`) in `firmware/components/acquisition/acquisition.c`
- [ ] T044 [US1] Implement the calibration component with nominal coefficients (voltage gain from adapter ratio and R1/R2, current gain from 100 mV/A and R3/R4, phase correction of one conversion), `calibration_kind = nominal`, 60 s zero-current offset capture, sign correction, and append-only revisions in NVS in `firmware/components/calibration/calibration.c`
- [ ] T045 [US1] Implement metering (1 s blocks, five blocks per 5 s summary with 20,000 paired samples, RMS, mean v·i, imported Wh with monotonic dt) in `firmware/components/metering/metering.c`
- [ ] T046 [US1] Implement quality classification and flags (`calibration_missing`, `sample_gap`, `adc_clipped`, `sensor_disconnected`, `out_of_range`, `polarity_reversed`, `clock_unsynchronized`, `energy_continuity_uncertain`; ranges 180–250 V and 0.5–5.0 A) in `firmware/components/quality/quality.c`
- [ ] T047 [US1] Implement the NVS energy checkpoint every 60 s and restart continuity in `firmware/components/persistence/checkpoint.c`
- [ ] T048 [US1] Implement the RAM offline queue (≥256 records, write before publish, remove only on `accepted` or `duplicate`, terminal rejection to bounded diagnostics) in `firmware/components/telemetry/queue.c`
- [ ] T049 [US1] Implement MQTT 5 over mTLS (Clean Start false, 24 h session expiry, 15 s keepalive, retained offline last will, client ID = node ID), measurement publish, ACK handling, and retained status every 30 s in `firmware/components/telemetry/mqtt.c`
- [ ] T050 [US1] Implement the OLED and RGB LED driver showing V, A, W, Wh with units, quality, clock/link state and a "no validado" marker for nominal calibration, per plan › Local indication, in `firmware/components/ui/ui.c`
- [ ] T051 [US1] Wire acquisition → metering → quality → queue → telemetry and UI in `firmware/main/main.c`

### Server and dashboard implementation for User Story 1 (software track)

- [ ] T052 [P] [US1] Implement the MQTT subscriber with a stable persistent session in `services/ingestion/src/energy_ingestion/mqtt/client.py`
- [ ] T053 [US1] Implement the ingest pipeline (validate schema and identity → ledger `received` → Influx write → ledger `stored` → publish ACK; reject/quarantine conflicts as data-quality/security events) in `services/ingestion/src/energy_ingestion/mqtt/pipeline.py`
- [ ] T054 [US1] Implement node status tracking (retained status, server-derived `stale` after 15 s without a measurement, `offline` after 30 s or authenticated last will) in `services/ingestion/src/energy_ingestion/health/node_status.py`
- [ ] T055 [P] [US1] Implement the container-only health/readiness API and operations metrics (received/accepted/rejected/duplicate/conflict, ingest/storage latency) in `services/ingestion/src/energy_ingestion/health/api.py`
- [ ] T056 [P] [US1] Write `services/ingestion/Dockerfile` (non-root, pinned base) and add the service to `infrastructure/compose.yaml`
- [ ] T057 [P] [US1] Write Flux queries for latest values, V/I/P time series, quality windows, and pipeline health in `dashboards/queries/{latest,timeseries,quality,health}.flux`
- [ ] T058 [US1] Build `dashboards/energy-overview.json` panels 1 (identity/quality banner with the permanent "not validated" label for `nominal`), 2 (current cards), 3 (active power), 4 (V/I with range bands), 6 (quality), 8 (pipeline health); stale/offline replace live values

### Supervised hardware stages for User Story 1 (hardware track)

- [ ] T059 [P] [US1] Write the safety review checklist and sign-off record (build guide stage 5: ACS712 test box, RCD test, breaker acceptance, USB policy) in `guides/safety/review-checklist.md`
- [ ] T060 [P] [US1] Write the nominal calibration and plausibility procedure (plan › Calibration and plausibility procedure, steps 1–9) in `guides/calibration/nominal-calibration.md`
- [ ] T061 [P] [US1] Implement the plausibility evaluation script (input: exported 5 s summaries and a CSV of load nameplates; output: table E1–E4 with V in 180–250 V, P > 0, `d_P = (P_m − P_n)/P_n × 100` within ±15% for E1–E3, E4 observed only; SHA-256 manifest) in `experiments/evaluation/plausibility.py` with a fixture in `tests/fixtures/plausibility/example.csv`
- [ ] T062 [US1] [HW] Bench integration without mains: flash the full firmware, confirm Vb and offset readings, and connect to the server via the simulator certificate replaced by the node certificate; record evidence in `experiments/manifests/bench-YYYYMMDD.json`
- [ ] T063 [US1] [HW] Qualified safety review of the ACS712 test box and setup, signed before any mains connection, recorded in `guides/safety/review-record.md` (blocks T064)
- [ ] T064 [US1] [HW] Supervised session: RCD test, warm-up, offset, polarity, freeze the `nominal` calibration revision, run E1–E4 per `guides/calibration/nominal-calibration.md`; store raw captures and summaries under the ignored `experiments/data/` with a tracked manifest in `experiments/manifests/plausibility-YYYYMMDD.json`
- [ ] T065 [US1] Generate the plausibility table for the article from T064 evidence with `experiments/evaluation/plausibility.py` into `experiments/evaluation/out/plausibility.csv`

**Checkpoint**: US1 is the MVP: real-time values visible from the simulator and from the real node, labeled "not validated", with a plausibility table.

---

## Phase 4: User Story 2 — Review consumption history (Priority: P2)

**Goal**: Hourly, daily, and weekly consumption views and the peak hour; outages
recover without duplicates or reordering.

**Independent Test**: Load a seven-day dataset and find the highest-consumption hour
in < 2 min (SC-005); after a 10 min outage, ≥99% of retained records are stored
and queryable in order within 5 min (SC-003).

### Tests for User Story 2

- [ ] T066 [P] [US2] Golden-query tests for hourly/daily/weekly energy from Wh counter differences ("never by summing cumulative totals"), counter resets via `counter_id`, exclusion of invalid windows, and `America/Lima` day boundaries, in `tests/integration/test_history_queries.py`
- [ ] T067 [P] [US2] Firmware unit tests for queue drain (oldest first, ≥2 records/s, ≤10 in flight, new observations still enqueued) in `firmware/test/main/test_queue_drain.c`
- [ ] T068 [US2] Recovery test: disconnect the publisher 10 min, assert ≥99% of retained records stored and chronologically queryable within 5 min, plus exact duplicates, conflicting IDs, out-of-order arrival, ingestion restart, storage unavailability, clock holdover, and full queue, in `tests/recovery/test_outage.py`; wire `make test-recovery OUTAGE=10m`

### Implementation for User Story 2

- [ ] T069 [US2] Implement the firmware drain policy in `firmware/components/telemetry/queue.c`
- [ ] T070 [US2] Implement observation-time ordering (sort on `window_end`, then `boot_id`/`sequence`; never arrival order) and late-arrival handling in `services/ingestion/src/energy_ingestion/persistence/influx.py`
- [ ] T071 [P] [US2] Write hourly/daily/weekly energy and peak-hour (h*) Flux queries in `dashboards/queries/{hourly,daily,weekly,peak_hour}.flux`
- [ ] T072 [US2] Add panel 5 (hourly bars, daily/weekly totals, peak-hour marker) to `dashboards/energy-overview.json`
- [ ] T073 [P] [US2] Implement the daily Parquet export with manifest (exact query, UTC interval, schema/calibration/firmware revisions, quality exclusions, controlled-load labels, file hashes, code commit, environment-lock hash) in `experiments/export/export_daily.py`
- [ ] T074 [US2] Produce the seven-day dataset for SC-005/E8 and record its manifest in `experiments/manifests/seven-day.json` — **blocked on the open decision** whether it comes from supervised sessions spread over a week or from the simulator (README › Open decisions)
- [ ] T075 [US2] Timed operator check (first-time user finds the peak hour in < 2 min, SC-005) recorded in `tests/acceptance/us2_operator_check.md`

**Checkpoint**: History views work on stored data; outage recovery passes.

---

## Phase 5: User Story 3 — Receive threshold alerts (Priority: P3)

**Goal**: Sustained excess power produces a local warning ≤2 s and a remote alert
≤10 s; brief surges do not alert; local warning works with the server down.

**Independent Test**: With the simulator and with a real load switched on and off,
brief surges return from `pending` without alerting, sustained breaches alert
locally and remotely, and the node still warns locally with the server stopped
(SC-004, scenarios 1–3).

### Tests for User Story 3

- [ ] T076 [P] [US3] Firmware unit tests for the local state machine (`normal --value > limit--> pending`, `pending --confirmed for confirm_ms--> firing`, `pending --value <= limit or invalid--> normal`, `firing --value < clear_below_W--> clearing`, `clearing --below for clear_ms--> resolved --> normal`, `clearing --value >= clear_below_W--> firing`; invalid data never confirms or clears) in `firmware/test/main/test_threshold.c`
- [ ] T077 [P] [US3] Firmware unit tests for config handling (bounds `active_power_limit_W` "`>0` and `<=1100`", `confirm_ms` "1,000–300,000; default 10,000", `clear_below_W` "`>=0` and `< active_power_limit_W`", rollback rejection) in `firmware/test/main/test_config.c`
- [ ] T078 [P] [US3] Ingestion tests for alert lifecycle (`open -> acknowledged -> resolved`, open may resolve directly, acknowledgment never clears the physical condition, append-only `AlertTransition`) and event/config/measurement cross-check raising a health alert on disagreement, in `services/ingestion/tests/test_alerts.py`
- [ ] T079 [P] [US3] Outbox tests (states `pending`, `sending`, `delivered`, `failed_terminal`; exponential backoff with jitter; idempotency on `alert_id`; provider failure never blocks storage) in `services/ingestion/tests/test_outbox.py`
- [ ] T080 [US3] Simulated alert acceptance (surge vs sustained, local ≤2 s, remote ≤10 s, server-down local warning) in `tests/acceptance/test_us3_alerts.py`

### Implementation for User Story 3

- [ ] T081 [US3] Implement retained config reception, NVS storage of the last accepted version, and rollback rejection in `firmware/components/threshold/config.c`
- [ ] T082 [US3] Implement the 1 s threshold state machine, node events (`threshold_entered`, `threshold_cleared`, `measurement_quality_changed`), and buzzer/red LED only in `firing`/`clearing` (no relay, FR-016) in `firmware/components/threshold/threshold.c`
- [ ] T083 [P] [US3] Implement `energyctl` (validate versioned YAML, store and audit, publish retained config; reject limits above 1,100 W) in `services/ingestion/src/energy_ingestion/cli/energyctl.py` with `config/thresholds.example.yaml`
- [ ] T084 [US3] Implement event-to-alert handling, transitions, and cross-check in `services/ingestion/src/energy_ingestion/thresholds/alerts.py`
- [ ] T085 [US3] Implement the notification outbox worker with a generic outbound HTTPS webhook adapter (runtime-only token, redacted errors; provider choice is open decision 6) in `services/ingestion/src/energy_ingestion/notifications/outbox.py`
- [ ] T086 [US3] Add panel 7 (alert table/history with evidence, severity, state, notification state, transition times) to `dashboards/energy-overview.json`
- [ ] T087 [US3] [HW] Supervised alert run with a real load (iron on/off below and above a configured limit; server stopped for the local-warning case) recorded in `experiments/manifests/alerts-YYYYMMDD.json`

**Checkpoint**: All three stories work independently and together.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Security, health diagnosis, documentation, and evidence for the article.

- [ ] T088 [P] Security tests (anonymous MQTT, untrusted certificate, wrong-node topic, dashboard without login, internal ports unreachable from the LAN) in `tests/security/test_security.py`; wire `make test-security`
- [ ] T089 [P] Fault-injection test that stops each stage (acquisition, connectivity, ingestion, storage, threshold, presentation) and asserts the health view names it (FR-017) in `tests/integration/test_stage_health.py`
- [ ] T090 [P] Write the architecture overview in `guides/architecture/overview.md` and the operations runbook (start/stop, backups, certificate rotation, retention, secret rotation) in `guides/operations/runbook.md`
- [ ] T091 [P] Write the latency/recovery evidence script producing tables for E5–E7 (mean and p95 latency, recovery R) in `experiments/evaluation/performance.py`
- [ ] T092 Run quickstart.md sections 2–8 end to end and record deviations in `guides/operations/quickstart-validation.md`
- [ ] T093 Update trackers for the completed implementation (`README.md` status/roadmap/recent updates; `article/README.md` status) and move pending article `\todo{}` results only from preserved evidence (T065, T091)

---

## Dependencies & Execution Order

### Phase dependencies

- **Phase 1 Setup**: none.
- **Phase 2 Foundational**: after Phase 1; blocks all stories. Inside it, the
  software track (T009–T025) and the hardware track (T026–T034) are independent.
- **Phase 3 US1**: after Phase 2. Software tasks (T052–T058) need only the
  simulator; firmware tasks (T043–T051) need T026–T033; T062 needs both tracks;
  T063 (signed review) strictly precedes T064 (first mains connection).
- **Phase 4 US2**: after Phase 2; uses US1's pipeline for storage but is testable
  with simulator data. T074 waits on the seven-day-data decision.
- **Phase 5 US3**: after Phase 2; firmware threshold tasks need T045/T046; T087
  needs T063 signed.
- **Phase 6**: after the stories it covers.

### Story order

US1 (P1) → US2 (P2) → US3 (P3) for a single team; US2 and US3 can proceed in
parallel with US1's hardware stages because the simulator stands in for the node.

### Within each story

Tests first (they must fail), then firmware/server implementation, then
integration, then supervised hardware tasks last (plan: "place supervised mains
tests after all simulation and low-voltage gates").

---

## Parallel Execution Examples

### Phase 2 (two people)

```text
Software: T009, T014, T015, T016, T017, T018 in parallel → T019 → T020 → T021 → T022 → T024
Hardware: T026, T027, T028, T029 in parallel (breadboard stages 1–4) → T030, T031, T032, T033
```

### User Story 1

```text
Tests in parallel: T035, T036, T037, T038, T039, T040, T041
Server in parallel with firmware: T052–T058 (software)  |  T043–T051 (firmware)
Procedures in parallel: T059, T060, T061
```

### User Story 3

```text
Tests in parallel: T076, T077, T078, T079
Then: T081 → T082 (firmware)  |  T083, T084, T085 (server)
```

---

## Implementation Strategy

### MVP first (User Story 1 only)

1. Phase 1 → Phase 2 (contracts, server, simulator; bring-up on the breadboard).
2. Phase 3 software tasks with the simulator → `make acceptance-simulated`.
3. Phase 3 firmware tasks → bench integration without mains (T062).
4. Signed safety review (T063) → supervised plausibility session (T064, T065).
5. **Stop and validate**: values visible, labeled "not validated", plausibility table done.

### Incremental delivery

US1 (live monitoring) → US2 (history and recovery) → US3 (alerts), each demoable
on its own. The article's Results section is filled only from preserved evidence
(T065, T074, T087, T091).

---

## Notes

- Total: 93 tasks. [HW] tasks need the physical prototype; all others run on a
  laptop with Docker and the ESP-IDF toolchain.
- Open decisions that affect tasks: seven-day dataset source (T074), notification
  provider (T085), OLED pin count and RGB LED type (T028, T050), repetitions per
  scenario (T064).
- The schema flag `adc_crc_error` comes from the earlier external-ADC design and
  is never raised by the internal ADC; keep it for compatibility.
- Commit after each task or logical group; never commit `infrastructure/secrets/`,
  `.env`, or raw captures with private data.
