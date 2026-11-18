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
  ACS712 test box (ACS712 alone in it, never on a breadboard), upstream
  RCD/GFCI and overcurrent protection, certified AC-AC adapter, household test loads with known
  nameplate ratings, and the signed safety procedure (no reference meter;
  constitution 2.0.0).
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
protected outlet) drives the voltage channel, and the ACS712 zero-current offset
is checked with no current. No mains conductor passes through the ACS712 at
this stage. Current polarity is checked on the first supervised resistive-load
run: active power must be positive; if it is negative, the sign is corrected in
the calibration coefficients, without rewiring.

## 8. Controlled calibration and plausibility check

Hardware work is blocked until the qualified safety review is signed. Then follow
the versioned documents that implementation will place under `guides/safety/` and
`guides/calibration/`:

1. Perform de-energized visual, protective-earth/isolation, polarity, test-box,
   strain-relief, and conductor checks.
2. Energize only through the 30 mA RCD protecting the test outlet (building
   panel or certified portable RCD, tested with its test button) and the
   reviewer-accepted overcurrent protection; never work live or expose terminals.
3. Load the nominal coefficients, warm up 10 minutes, and capture a 60-second
   zero-current record (ACS712 offset).
4. Switch on a resistive load and confirm positive active power (polarity);
   freeze a `nominal` calibration revision.
5. Plausibility check on at least three resistive loads across the range:
   V_RMS in 180-250 V, P within ±15% of each nameplate; record one fan
   qualitatively.
6. Hash and preserve the procedure, wiring/build revisions, raw captures,
   coefficients, software revision, and the plausibility table.

The result is an educational demonstration with readings labeled "not validated"
for 180-250 V and the 0.5-5 A range of the ACS712-20A (about 1.1 kW). It makes no
accuracy claim and is not a permanent-installation, billing, or safety-device
approval.

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
