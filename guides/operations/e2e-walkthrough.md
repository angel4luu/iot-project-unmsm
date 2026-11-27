# Guided end-to-end walkthrough (simulated node)

A hands-on tour of the whole pipeline with mock data: you start the stack and keep
four views open; the facilitator (Claude or a teammate) sends one kind of simulated
data per case, and you watch it move through each component:

```
simulated node ──MQTT/mTLS──► Mosquitto ──► ingestion ──► SQLite  (registry, ledger, alerts, outbox)
   (sim-e2e)                    view A          │      └─► InfluxDB (readings, alert/notification points)
                                                └─► ntfy (phone)          views B, C ──► Grafana (view D)
```

All values are simulated and NOT VALIDATED. The walkthrough uses its own node,
`sim-e2e`, so it does not mix with the acceptance runs (`sim-001`) or the seven-day
dataset (`sim-history`). Nothing is deleted; the stack keeps running.

## How we work

- **You** run the setup and the viewer commands, and say "ready" before each case.
- **The facilitator** runs the "Send" command of the case and tells you when it
  finished. Every Send command is written out, so you can also run them alone later.
- Each case lists what to look at in each view and a **Pass if** line. A value that
  does not match is worth stopping for: note it, do not patch it on the fly.
- Times: storage is UTC; the dashboard shows Lima time (UTC−5).

## Setup (you, once)

1. Stack running and healthy:

   ```
   make infra-up
   make infra-health
   ```

2. A certificate for the walkthrough node (adds one file pair; existing certificates
   are kept):

   ```
   make dev-certs CERT_NODES=sim-e2e
   ```

3. Dashboard hostname. `.env` binds everything to `127.0.0.1` with
   `DASHBOARD_HOSTNAME=energy.lab.internal`; map that name once:

   ```
   echo '127.0.0.1 energy.lab.internal' | sudo tee -a /etc/hosts
   ```

4. Grafana login: open `https://energy.lab.internal/`. The certificate is Caddy's
   local CA, so the browser warns once; accept it for this host. User `operator`,
   password from `infrastructure/secrets/grafana-admin-password` (open the file in
   your editor; do not paste it anywhere shared). Open **Energy overview**.
5. Phone (optional): with ntfy configured (`guides/operations/ntfy.md`), every
   **opened** alert reaches the phone, including the health and quality alerts of
   cases 4 and 9. To keep the phone quiet, clear `NOTIFICATION_WEBHOOK_URL` and run
   `make infra-up` before you start; alerts then stay `pending` in the outbox.

### The four views

Open four terminals (or panes) at the repository root:

| View | Command | Shows |
|---|---|---|
| A broker | `scripts/e2e-view.sh broker` | every MQTT message of `sim-e2e`, live: status, measurements, events, config, ACKs |
| B SQLite | `scripts/e2e-view.sh db <table>` | `node`, `calibration`, `threshold`, `ledger`, `alert`, `transition`, `outbox` |
| B SQLite | `scripts/e2e-view.sh counts` | ledger messages per state and reject code |
| C InfluxDB | `scripts/e2e-view.sh influx <view> [node] [range]` | `raw`, `status`, `ingest`, `alerts`, `notifications`, `pipeline` (range default `15m`) |
| D Grafana | browser, node `sim-e2e`, last 15 minutes | the dashboard (refreshes every 5 s) |

Keep view A running the whole time. Run the B and C commands again after each case
(or wrap one in `watch -n 5 'scripts/e2e-view.sh db ledger'`). All viewers are read
only: SQLite opens read-only, InfluxDB uses the read-only Grafana token, MQTT uses the
read-only `svc-admin` identity.

### Sending data

Every Send command is `make simulate-e2e SCENARIO=<scenario> DURATION=<time>`: it
runs the simulator with the `sim-e2e` identity (its own certificate). The simulator
prints nothing while it runs, only a summary at the end; watch view A instead.

Simulator levels: normal ≈ 12.6 V, 1.62 A, 20.4 W; "above the limit" = 1.15 × 22 W
≈ 25.3 W.

---

## Case 1: baseline, nothing known about `sim-e2e`

**Send:** nothing.

**Look:**

- A: no message for `sim-e2e`.
- B: `db node` → `(node: no rows for sim-e2e)`; `counts` → no ledger rows.
- C: `influx raw` → empty.
- D: the node dropdown does not list `sim-e2e`. Pick `sim-history` instead: it shows
  OFFLINE and empty value cards, never zeros or a frozen last value.

**Pass if:** no view invents data for an unknown node.

## Case 2: register the node and its calibration

**Send:**

```
docker exec unmsm-energy-ingestion-1 energyctl node register --node-id sim-e2e \
  --display-name "E2E walkthrough" --hardware-revision simulator \
  --circuit-id sim-e2e-load --circuit-name "E2E simulated load"
docker cp config/e2e/calibration-sim-e2e.yaml unmsm-energy-ingestion-1:/tmp/
docker exec unmsm-energy-ingestion-1 energyctl calibration register /tmp/calibration-sim-e2e.yaml
```

**Look:**

- B: `db node` → one row, status `provisioning`, no `last_seen_at` yet.
- B: `db calibration` → `sim-e2e-nominal-r1`, kind `nominal`, not accepted.
- A, C, D: nothing yet (registration is server state only).

**Pass if:** both rows exist. Running the calibration command again is refused
(revisions are immutable).

Known gaps (found 2026-11-26, not yet fixed): the ingestion service never updates
the registry row, so `status`, `last_seen_at`, `firmware_version` and
`last_valid_observed_at` stay empty (`provisioning`) even while the node sends; live
state is in InfluxDB (`influx status`, dashboard). And readings are accepted and
marked `valid` even though this calibration was never accepted, which the data model
says should not happen.

## Case 3: normal readings (2 min)

**Send:** `make simulate-e2e SCENARIO=normal DURATION=2m`

**Look:**

- A: a retained `status` (`online`), then one `measurements` message every 5 s, each
  followed by an `acks/measurements` message from the server (`accepted`).
- B: `db ledger` → one row per window, state `stored`, `ack_count` 1. `counts` →
  about 24 `stored`. (`db node` does not change: live node state is kept in InfluxDB,
  see `influx status`; known gap, see case 2.)
- C: `influx raw` → one point per window: quality `valid`, ≈ 12.6 V, 1.62 A, 20.4 W,
  the Wh counter rising; `clock_source` `sntp`. `influx status` → state `online`,
  `pending_records` 0.
- D: select `sim-e2e`: identity table with "NOT VALIDATED", value cards filled,
  power line around 20.4 W, Wh rising.
- After the run ends: A shows a retained `status` `offline`; D turns the cards
  STALE and then OFFLINE within 30 s, empty, not zero.

**Pass if:** every window sent is stored once, acknowledged once, and visible on the
dashboard within about 10 s; nothing is shown after the node goes offline.

## Case 4: an excess the server cannot check (no threshold stored yet, 2 min)

The node always evaluates its own limit (simulator: 22 W, confirm 10 s, clear 5 s),
but the server has no threshold for `sim-e2e` yet, so it cannot confirm the node's
claim.

**Send:** `make simulate-e2e SCENARIO=sustained DURATION=2m`

**Look:**

- A: at second ≈ 60 the measurements rise to ≈ 25.3 W; at ≈ 70 an `events` message
  `threshold_entered` (measured ≈ 25.2, threshold 22.0); at ≈ 95 `threshold_cleared`.
- B: `db alert` → one `active_power_threshold` alert, `resolved`, and two
  `pipeline_health` alerts (one per node event), still `open`. `db transition` →
  `open` and `resolved` by `node:sim-e2e`, plus `open` for each health alert with
  reason `cross_check:config_unknown`. `db outbox` → one row per opened alert.
- C: `influx alerts` → the same transitions, with `event_observed_at` (the node's
  event time).
- D: panel 7 (Alert history) lists all three; with ntfy on, the phone gets three
  messages.

**Pass if:** the alert still opens and resolves (the server never drops a node's
alarm), and the missing configuration is reported as a health alert, not ignored.

## Case 5: publish the threshold configuration

**Send:**

```
docker cp config/e2e/threshold-sim-e2e.yaml unmsm-energy-ingestion-1:/tmp/
docker exec unmsm-energy-ingestion-1 energyctl threshold publish /tmp/threshold-sim-e2e.yaml --by "e2e facilitator"
```

**Look:**

- A: a retained `config` message for `sim-e2e` (version 1, limit 22, clear below 20.9).
- B: `db threshold` → version 1 by `e2e facilitator`.

**Pass if:** the stored and published values are the same. Publishing the same file
again is refused ("config_version 1 must be greater than stored version 1"): a
version is never replaced, only superseded by a higher one.

## Case 6: brief surges do not alert (2 min)

**Send:** `make simulate-e2e SCENARIO=surge DURATION=2m`

**Look:**

- A: at second ≈ 30 of each minute one window averages a little higher (a 3 s surge
  inside a 5 s window); no `events` message.
- B: `db alert` → nothing new.
- D: the power line shows two small bumps; panel 7 unchanged.

**Pass if:** no alert; the surge is shorter than the 10 s confirmation.

## Case 7: a sustained excess, end to end (2 min)

**Send:** `make simulate-e2e SCENARIO=sustained DURATION=2m`

**Look:**

- A: as in case 4: entered at ≈ 70 s, cleared at ≈ 95 s.
- B: `db alert` → one new `active_power_threshold` alert, `resolved`, and **no** new
  `pipeline_health` alert (the configuration now matches). `db outbox` → `delivered`
  (ntfy on) or `pending` (notifications off).
- C: `influx alerts` → `opened` time minus `event_observed_at` is well under 10 s;
  `influx notifications` → `sending`, then `delivered`.
- D: panel 7 shows the alert with its delivery state; the phone gets one message
  ("Alerta: potencia sobre el límite", "Valores no validados").

**Pass if:** exactly one alert, resolved by the node, delivered once, with no health
alert.

## Case 8: acknowledge the open health alerts

**Send:**

```
docker exec unmsm-energy-ingestion-1 energyctl alert list --status open
docker exec unmsm-energy-ingestion-1 energyctl alert ack <alert_id> --by "e2e facilitator"
```

(one `ack` per open `pipeline_health` alert from case 4; the list prints full IDs).

**Look:**

- B: `db alert` → those alerts `acknowledged` with `acknowledged_at`. `db transition`
  → `open → acknowledged`, actor `e2e facilitator`. Older rows never change (the
  audit table is append-only).
- C: `influx alerts` → the acknowledged transitions.
- D: panel 7 shows the new state.

**Pass if:** acknowledging twice changes nothing; a resolved alert cannot be
acknowledged.

## Case 9: invalid readings and malformed messages (1 min)

**Send:** `make simulate-e2e SCENARIO=invalid DURATION=1m`

What the simulator sends: every 4th window (sequences 1, 5, 9) is `invalid`
(`sensor_disconnected`, values null), and every 4th window (sequences 3, 7, 11) breaks
the contract (missing unit, unknown field).

**Look:**

- A: `events` `measurement_quality_changed` → `invalid`, then → `valid`
  (`quality_restored`), every 20 s. ACKs say `rejected` for the malformed windows.
- B: `counts` → new `rejected` rows with code `schema_violation`. `db alert` →
  `measurement_quality` alerts opening and resolving (with ntfy on, about three phone
  messages).
- C: `influx raw` → invalid windows have quality `invalid` and **no** V, A, W fields
  (never zeros); malformed windows are missing. `influx ingest` → `rejected` /
  `schema_violation`.
- D: "Measurement quality" row: invalid windows per minute and the flags table;
  "Pipeline health": recent ingestion rejects. The power line has gaps, not drops
  to zero.

**Pass if:** bad readings are visible as bad, malformed messages are refused with a
reason, and nothing is counted as 0 W or 0 Wh.

## Case 10: duplicates and out-of-order delivery (1 min each)

**Send:**

```
make simulate-e2e SCENARIO=duplicate DURATION=1m
make simulate-e2e SCENARIO=out_of_order DURATION=1m
```

**Look:**

- A: in the first run every measurement appears twice and gets two ACKs (`accepted`,
  then `duplicate`); in the second, neighbouring windows arrive swapped.
- B: `db ledger` → each window stored once; for the duplicate run `ack_count` is 2.
  `counts` → no conflicts.
- C: `influx raw` → one point per window, in time order, no gaps; `influx pipeline`
  → `duplicate_total` went up.
- D: the power line is continuous for both runs.

**Pass if:** each window is stored exactly once and ordering does not matter.

## Case 11: node-side outage (3 min)

**Send:** `make simulate-e2e SCENARIO=outage DURATION=3m`

The simulated node is "offline" for the middle minute: it queues its windows and
sends them in order when it reconnects.

**Look:**

- A: one minute without messages, then a burst of the queued windows.
- B: `db ledger` → all windows `stored`; their `received_at` bunches together.
- C: `influx raw` over `15m` → no gap; the late windows keep their original times.
- D: during the gap the cards turn STALE, then OFFLINE; after the burst the line is
  filled back in without a hole.

**Pass if:** no window is lost or duplicated and the history has no gap.

## Case 12: server-side outage (3 min, you stop the service)

**Send:** `make simulate-e2e SCENARIO=normal DURATION=3m`

**You:** at about 40 s run `docker stop unmsm-energy-ingestion-1`; at about 100 s run
`docker start unmsm-energy-ingestion-1`.

**Look:**

- A: measurements keep arriving at the broker; ACKs stop while ingestion is down,
  then catch up after the restart.
- B: once the service is back (≈ 20 s to become healthy), `counts` → every window
  `stored`, none rejected.
- C: `influx raw` → no gap.
- D: the dashboard stops updating while ingestion is down, then fills the hole.

**Pass if:** the broker held the messages and nothing was lost. Do not skip
`docker start`.

## Case 13: clock holdover and loss of sync (1 min 30 s)

**Send:** `make simulate-e2e SCENARIO=clock_holdover DURATION=90s`

**Look:**

- C: `influx raw` → `clock_source` `sntp` for the first 30 s, `holdover` for the
  next 30 s (still `valid`), then `unsynchronized` with quality `degraded` and flag
  `clock_unsynchronized`.
- D: "Clock source and calibration revision" panel and the degraded-per-minute panel.

**Pass if:** a clock that has lost sync degrades the reading's quality instead of
being trusted.

## Case 14 (optional): a week of history

**Send:** nothing; the seven-day dataset is already stored (node `sim-history`,
manifest `experiments/manifests/seven-day.json`).

**Look:** D: select `sim-history`, time range 2026-11-16 00:00 to 2026-11-23 00:00
(Lima). Energy per hour/day/week comes from differences of the Wh counter; the
"Peak hour" panel shows Thursday 2026-11-19 18:00, 23.9 Wh.

**Pass if:** the busiest hour matches and the restart in the middle of the week does
not create a jump.

---

## After the walkthrough

- Nothing needs cleaning up: `sim-e2e` raw data expires with the 30-day retention;
  its SQLite rows (node, calibration, threshold, alerts) stay as an audit record.
- To change the limit on a later run, publish a copy of the threshold file with
  `config_version: 2` and pass the same values to the simulator, e.g.
  `make simulate-e2e SCENARIO=sustained DURATION=2m SIM_ARGS="--config-version 2 --limit-w 18"`
  (plus `--confirm-ms`/`--clear-ms` if they changed), so the simulated node evaluates
  with the configuration the server stored.
- If ntfy is on, clear `NOTIFICATION_WEBHOOK_URL` before `make acceptance-simulated`
  (the US3 tests skip while real notifications are on).
