# Phase 1 Quickstart: Safe, Simulated Vertical Slice

This is the target developer and acceptance workflow for the implementation
described by `plan.md`. Commands marked **planned** become available as the tasks
are implemented; they are not assertions that source code already exists.

The first end-to-end run uses a simulator. Do not connect mains voltage merely to
complete this quickstart.

## 1. Prerequisites

- Git, Make, Docker Engine with Compose v2, Python 3.14, and `uv`.
- For firmware-only work: ESP-IDF 5.4 LTS toolchain and an ESP32-S3 DevKitC-1.
- For hardware acceptance: qualified supervision, approved schematic and closed
  enclosure (ACS712 in its own compartment, never on a breadboard), upstream
  RCD/GFCI and overcurrent protection, certified AC-AC adapter, true-RMS reference
  meter, and the signed safety/calibration procedures.
- A trusted-LAN host whose firewall can restrict TCP 443 and 8883 to the lab
  subnets. The host must not have public port forwarding or UPnP exposure.

## 2. Create local configuration without committing secrets

**Planned**:

```bash
cp .env.example .env
cp infrastructure/secrets/README.example.md infrastructure/secrets/README.local.md
make dev-certs
```

Set non-secret network bindings in `.env`. Put CA private key, service/node leaf
keys, Influx tokens, Grafana password, Wi-Fi credentials, and notification token
only in ignored local secret files with owner-only permissions. Do not put real
values in `.env.example`, Compose YAML, firmware source, fixtures, screenshots,
logs, or reports.

Before every commit, run **planned** `make secrets-scan`. If any credential was
ever committed, deleting the visible line is not sufficient: revoke/rotate it and
assess repository-history remediation.

## 3. Validate contracts before starting services

The following check can already be run when a Draft 2020-12 validator such as
`check-jsonschema` is installed:

```bash
check-jsonschema \
  --schemafile specs/001-energy-monitoring-system/contracts/measurement.schema.json \
  specs/001-energy-monitoring-system/contracts/examples/valid-measurement.json
```

The invalid fixture MUST fail:

```bash
check-jsonschema \
  --schemafile specs/001-energy-monitoring-system/contracts/measurement.schema.json \
  specs/001-energy-monitoring-system/contracts/examples/invalid-measurement.json
```

The **planned** aggregate command is `make contracts-test`; it also validates
status, event, config, and ACK fixtures and checks topic/payload identity.

## 4. Start the local server boundary

**Planned**:

```bash
make infra-config-check
make infra-up
make infra-health
```

Expected deployment:

- `https://<trusted-lan-host>/` is the only dashboard entry point.
- MQTT accepts authenticated mutual-TLS clients on port 8883.
- InfluxDB, SQLite, ingestion health API, Grafana port 3000, and container admin
  interfaces are not reachable from the LAN.
- Anonymous dashboard access and anonymous MQTT access fail.

Log in with the locally provisioned operator account. The dashboard should show
`offline / no data`, not zeros and not a fabricated last value.

## 5. Run the simulator vertical slice

The simulator uses a dedicated test certificate and publishes valid five-second
windows plus controllable faults. **Planned**:

```bash
make simulate SCENARIO=normal DURATION=10m
make acceptance-simulated
```

Verify:

1. V, A, W, and Wh appear with timestamp, node/circuit, calibration revision,
   and quality.
2. At least 95% of scheduled summaries are visible within 10 seconds.
3. Hourly/daily/weekly queries use differences of the Wh counter; they never sum
   cumulative totals.
4. A brief power surge returns from pending without alerting.
5. A sustained breach creates local-event evidence, a remote alert, a delivery
   record, and a resolved transition after hysteresis.
6. Invalid values appear as invalid/diagnostic state and do not drive consumption
   alerts.

## 6. Exercise failure recovery and security

**Planned**:

```bash
make test-integration
make test-recovery OUTAGE=10m
make test-security
```

The recovery test disconnects the publisher for 10 minutes, then asserts that at
least 99% of queued records are durably stored and chronologically queryable
within five minutes. It tests exact duplicates, conflicting IDs, out-of-order
arrival, ingestion restarts, storage unavailability, clock holdover, and a full
queue. The service does not ACK before durable storage.

Security checks reject an anonymous client, untrusted certificate, wrong-node
topic, dashboard request without login, and attempts to reach internal service
ports from the LAN.

## 7. Build and bench-test firmware without mains

**Planned**:

```bash
make firmware-test
make firmware-build
make firmware-flash-test-fixtures
```

Start with recorded ADC/waveform fixtures or an isolated signal source. Unit tests
verify RMS, alternating-sample delay and phase correction, active power,
monotonic-time Wh integration, NVS checkpoint recovery, quality classification,
threshold timing, queue replay, config rollback rejection, sample-gap detection,
and the LED/OLED state mapping.

Then a low-voltage bench stage: the certified AC-AC adapter (plugged into a
protected outlet) drives the voltage channel; the ACS712 offset and polarity are
checked with a low-voltage DC current. No mains conductor passes through the
ACS712 at this stage.

## 8. Controlled calibration and hardware acceptance

Hardware work is blocked until the qualified safety review is signed. Then follow
the versioned documents that implementation will place under `docs/safety/` and
`docs/calibration/`:

1. Perform de-energized visual, protective-earth/isolation, polarity, enclosure,
   strain-relief, fuse, and conductor checks.
2. Energize only inside the controlled setup with RCD/GFCI and two-pole 10 A
   protection; never work live or expose terminals.
3. Warm up 10 minutes and capture a 60-second zero-current record (ACS712 offset).
4. Calibrate voltage and current gain on resistive loads, and the phase
   correction on a resistive load (`P = V_RMS*I_RMS`), against the identified
   true-RMS reference meter; log the enclosure temperature.
5. Freeze a new calibration revision.
6. Validate on at least three separate resistive loads across the calibrated
   range, plus one inductive/nonlinear load for V and A only. Require every
   accepted comparison to meet the 5% (or guard-banded) limit.
7. Hash and preserve the procedure, wiring/build revisions, raw captures,
   reference readings, temperatures, coefficients, software revision, and
   pass/fail report.

The result is an educational prototype measurement claim only for 180–250 V, the
0.5–5 A range of the ACS712-20A (about 1.1 kW), and the
tested configurations. It is not a permanent-installation,
billing, or safety-device approval.

## 9. Stop services and preserve evidence

**Planned**:

```bash
make evidence-export RUN_ID=<acceptance-run-id>
make infra-down
```

`infra-down` must preserve named volumes. Volume deletion, counter reset, CA
rotation, and retention-policy changes use separate explicit commands with backup
and confirmation. Acceptance evidence and future analytics snapshots are exported
before the 30-day raw-retention boundary.

## 10. Expected verification matrix

| Gate | Default command | Evidence |
|---|---|---|
| Formatting/static checks | `make lint` | CI log |
| Firmware calculations | `make firmware-test` | Unit/fixture report |
| Boundary compatibility | `make contracts-test` | Valid/invalid schema report |
| Server behavior | `make server-test` | pytest and migration report |
| Integrated path | `make test-integration` | Broker-to-dashboard report |
| Outage recovery | `make test-recovery OUTAGE=10m` | Delivery/latency table |
| Secret/network posture | `make secrets-scan test-security` | Scanner and reachability report |
| Measurement claim | supervised acceptance command defined later | Signed calibration report |
| User outcomes | `make acceptance-simulated` plus supervised hardware run | SC-001–SC-006 checklist |
