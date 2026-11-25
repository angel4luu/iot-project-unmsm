# Intelligent Energy Monitoring System — UNMSM IoT, Grupo 5

A small device measures the electricity used by a 12 V bulb powered by a safe plug-in adapter (no 220 V wiring by the team), sends the data
over Wi-Fi to a local server, and shows it on a dashboard with alerts when
consumption goes over a limit. We are also writing an IEEE article (in Spanish)
about it.

**Team**: Matias Vincula · Abigail Llana · Oscar Monzon · Angela Jara · Illary León

> Status: ✅ done · 🔄 in progress · ⏳ next · ⬜ not started · ⏸ on hold

## Where things are

| What | Where |
|---|---|
| System specification (the source of truth) | [specs/001-energy-monitoring-system/](specs/001-energy-monitoring-system/) |
| Prototype build guide, in Spanish (wiring, checks, safety) | [hardware/build-guide.md](hardware/build-guide.md) |
| Article (LaTeX) and its tracker | [article/](article/) · [article/README.md](article/README.md) |
| Rules for AI assistants | [CLAUDE.md](CLAUDE.md), [AGENTS.md](AGENTS.md) |

Build the article: `make -C article` → `article/build/main.pdf`

## Status at a glance

| Track | Where we are | Next |
|---|---|---|
| System | Simulated version works end to end (a fake node's readings are checked, stored once, acknowledged, and shown on the dashboard with STALE/OFFLINE/NO DATA and a "not validated" label). The ESP32 software is now complete and builds: it measures volts, amps, watts and watt-hours, marks each reading valid/degraded/invalid, keeps unsent readings while offline, sends them over the encrypted link, and drives the screen, LED and buzzer; all of this passes its tests on the PC. The script that checks the bulb readings against the bulb's label is ready | Wire the board and run the stage 1–4 test apps; then the 12 V loop check (adapter unplugged) and nominal calibration |
| Article | Introduction done; Methodology adapted to the 12 V loop, revised after the reviewer's comments, and Fig. 1 redrawn as a component and deployment diagram (6 pages; the 5-page target is relaxed until we pick a venue) | Results, once the experiments run |

*Last updated: 2026-11-25*

## Roadmap

### System

| Step | What it means | Status |
|---|---|---|
| Design | Requirements, architecture, research, data formats | ✅ Oct 14 (hardware adapted Nov 18) |
| Task list | Turn the design into an ordered to-do list (106 tasks, hardware and software tracks in parallel) | ✅ Nov 18 (test tasks added Nov 25) |
| Setup and foundations | Repo tools and checks, data-format tests, server stack, fake node, firmware basics tested on the PC, board test apps (Phases 1–2) | ✅ Nov 25 (board test apps still to run on the board) |
| Simulated version | Server, database and dashboard working with fake data | ✅ Nov 25 (1-hour simulated run passed) |
| Device software | Measuring and calculating on the ESP32 | ✅ Nov 25 on the PC (tests and build pass; still to try on the board) |
| Loop check and calibration | Team checks the 12 V bulb loop (adapter unplugged); nominal calibration and plausibility check against the bulb's label (no reference meter) | ⬜ |
| Full system tests | Real device end to end, network-outage recovery, security | ⬜ |
| Alerts | Local LED/buzzer and remote notifications | ⬜ |
| Final acceptance | Check all success criteria | ⬜ |

### Article

| Step | Status |
|---|---|
| Setup and requirements | ✅ Oct 28 |
| Introduction (with literature review) | ✅ draft Oct 28 |
| Methodology | ✅ draft Nov 11; revised Nov 18 after review (compile check pending) |
| Page budget and trimming | ✅ Nov 18 (7 → 5 pages; components table and signal-flow list added) |
| Figures 1–3 (component and deployment diagram, full circuit, flowchart) | ✅ Nov 25 (Fig. 1 redrawn; circuit values to check at the bench; add a prototype photo once built) |
| Results and Discussion | ⬜ needs the experiments |
| Conclusions and abstract | ⬜ |
| Review and submission | ⬜ |

## Open decisions

| # | Question | Blocks |
|---|---|---|
| 0 | ~~Qualified person~~ Not needed for the 12 V demo (2026-11-18). Only needed if we ever test a 220 V appliance (future work) | — |
| 1 | ~~Reference meter~~ Resolved 2026-11-18: none; readings are shown as "not validated" (constitution 2.0.0). A True RMS meter lent by the electrician could be added later | — |
| 2 | ~~How many repetitions per test~~ Rule set 2026-11-18, now also in the plan (2026-11-25): 3 pilot runs of the bulb test, then a formula fixes the final number (max 10); 3 runs for the 1-hour and outage tests | — |
| 7 | ~~Seven-day dataset~~ Resolved 2026-11-18: the simulator produces it (test E5) | — |
| 9 | Tolerances of the resistors and the 12 V adapter we buy (needed for the uncertainty estimate) | Methodology text |
| 3 | Parts list and total cost | Comparison table in Results |
| 4 | Which conference or journal (page limit, deadline) | Final format |
| 5 | Faculty name and contact emails for the author block | Submission |
| 6 | Which service sends remote alerts | Alerts |
| 10 | Screen model: SSD1306 or SH1106 (the second needs a one-line setting change); check the module when the board is wired | Screen on the board |
| 11 | Circuit name is fixed in the device software as `lab-load-001`; fine for one bulb loop, needs a setup field if we ever monitor more than one circuit | Nothing for the demo |

## Key decisions made

- Wi-Fi, not LoRa. No automatic power cut-off (safety).
- Educational prototype built from our own kit: ESP32-S3, ACS712 current sensor (20 A version), OLED, RGB LED, buzzer. All low-voltage wiring on a breadboard (no soldering). No reference multimeter: the dashboard labels every reading "not validated" and the article makes no accuracy claim.
- Demo on a 12 V AC loop (plan B): a certified, thermally protected 220 V → 12 V AC adapter (2 A) powers one 12 V 20 W halogen bulb through the ACS712. Only the adapter plugs into the wall, so no RCD, test box, fuse or electrician is needed. Purchases: the adapter, a barrel jack with screw terminals, resistors, capacitors, a transistor, the bulb, and a terminal strip only if we have no alligator leads. A 220 V appliance test is future work and would bring back the RCD, test box and electrician.
- The specs win over the article proposal; differences are listed in [article/README.md](article/README.md#decisions).
- Article in Spanish, IEEE conference format, decimal comma.
- No power-factor claims; anomaly detection and forecasting are future work.

## Recent updates

| Date | Update |
|---|---|
| 2026-11-25 | Live monitoring, device part (Phase 3B, 17 tasks): the ESP32 software measures the 12 V loop every 5 s (power as the average of volts × amps, never volts × amps of the averages), labels each reading valid/degraded/invalid with the reason, keeps a running watt-hour total that survives restarts (after a crash the next reading is marked "uncertain", and the total can step back by up to one minute of energy), queues up to 256 readings while offline, and shows values, quality and connection on the screen with "NO VALIDADO". New serial commands for the bench calibration steps (zero offset, polarity, freeze). New script checks a bulb run against its label (10–16 V, power within ±20 %, bulb-off current near zero) and keeps file hashes. Everything is tested on the PC; nothing has run on the board yet |
| 2026-11-25 | Live monitoring, server part (Phase 3A, 15 tasks; dashboard queries and the two guides by Codex, reviewed): readings from the fake node are validated, stored exactly once, and acknowledged; a crash in the middle of saving is repeated safely on restart (tested with a real crash). Dashboard: live values only while the node is online and the reading is under 15 s old, otherwise STALE/OFFLINE/NO DATA, with a permanent "not validated" banner. New `energyctl` command registers nodes and calibrations and rejects alert limits above 25 W. Guides: 12 V wiring checklist (signed by two members) and nominal calibration procedure. Fixed along the way: fake-node reruns reused message IDs (now a fresh ID set per run). 1-hour simulated run (T042): all 720 readings stored once, all acknowledged, 100 % on the dashboard within 10 s (target 95 %) |
| 2026-11-25 | Building started (Phases 1–2, 32 tasks; Claude with Codex on the server setup). The server stack starts with one command and only opens the two planned ports; a fake node sends readings over an encrypted connection that rejects unknown or impersonating devices. Firmware basics (clock, Wi-Fi/credential setup, pin map) pass their tests on the PC, checked against reference values computed independently from test signals of the 12 V loop. Test apps for build-guide stages 1–4 are written and noted in the guide; they still need the board. Note: the board's first start permanently stores an encryption key in the chip (one time, harmless) |
| 2026-11-25 | Test plan: no CI service; firmware tests run on our PCs without the board (expected values from a Python reference calculation, firmware messages checked against the data formats), board tests later; 11 test tasks added (106 tasks), including the real-device latency and outage runs; the run counts decided for the article are now in the plan. Diagrams: plan's electrical diagram fixed for the 12 V loop, new physical deployment diagram, and article Fig. 1 redrawn as a component and deployment diagram. Git history squashed (32 → 16 commits) |
| 2026-11-23 | Spec Kit commands now work as native slash commands in Claude Code (`/speckit-implement`, etc.), alongside Codex. No specs or templates changed |
| 2026-11-18 | Article Methodology merged with plan B (12 V bulb loop) and revised after the reviewer's comments: clearer test units and repetitions, step-by-step alert and outage tests, honest wording on delivery guarantees, uncertainty without a reference meter, and a separate metrics section. Details in article/README.md (AD-16) |
| 2026-11-18 | Parts list checked: the build guide now lists every part with an exact quantity (23 rows: 100 kΩ ×1, 4.7 kΩ ×2, 10 kΩ ×3, 470 Ω ×3, 1 kΩ ×1, 10 µF ×1, 22 nF ×2, male-to-female jumpers, 18 AWG loop cable, wire stripper) and a short shopping summary; polarity notes for the capacitor, buzzer and RGB LED. Leftover 220 V details removed from the plan's pin table, research, data model, task T033 and the contract examples (now 12.6 V, 1.62 A, 20.4 W) |
| 2026-11-18 | Plan B: no electrician available, so the demo measures a 12 V halogen bulb fed by a thermally protected 12 V AC adapter. RCD, test box, household loads and the qualified review leave the MVP (kept for a future 220 V test). Tests are now E1 (bulb vs. its label, ±20 %), E2 alerts (bulb on/off, ~15 W limit), E3 latency, E4 recovery, E5 busiest hour with the simulator. Specs, tasks (+2: calibration registration, retention test), build guide, article (Fig. 4 redrawn, Tables I–II) updated |
| 2026-11-18 | Consistency check (`/speckit.analyze`): no critical issues; 3 high to fix before the first 220 V session (who builds the test box, a circular rule on "accepted" calibration, how the dashboard learns the "not validated" label). Build guide: new section 4 on building hardware, firmware and server in parallel, then integrating |
| 2026-11-18 | Task list created (`specs/.../tasks.md`, 93 tasks): setup, shared foundations, then live monitoring (the MVP), history, alerts. Breadboard tests and the server with fake data can run at the same time. Project guides go in `guides/` because `docs/` is not tracked |
| 2026-11-18 | No reference multimeter (we can't afford a True RMS one): constitution 2.0.0 now allows a demo build whose readings are labelled "not validated". Tests E1–E4 check readings against appliance labels (±15 %) instead of claiming accuracy; the test box is now just plug, ACS712 and socket. Article, specs and build guide updated |
| 2026-11-18 | Article: new test-setup figure (Fig. 4), step-by-step test session, and the load or action for each test in Table II. The enclosure is now a test box for the ACS712 only; the multimeter (not a clamp meter) reads current in series through its sockets |
| 2026-11-18 | Low-voltage circuit goes on a breadboard (no soldering); the AC adapter plugs into a female barrel jack with screw terminals instead of cutting its cable (jack drawn in Fig. 2 and listed in Table I) |
| 2026-11-18 | Minimal MVP: temperature sensor (DHT22), barrel socket, 12 V polarity bulb and dedicated test panel dropped; LEDs, buzzer and OLED kept. Protection is the 30 mA RCD from the home panel (or a portable one) plus the outlet's existing breaker, if the reviewer accepts it |
| 2026-11-18 | No lab available: protection (30 mA RCD + 10 A breaker) becomes a portable test panel to buy, assembled by an electrician; household test loads; 12 V bulb for the polarity check |
| 2026-11-18 | Build guide translated to Spanish. Reference multimeter will be bought (not borrowed) |
| 2026-11-18 | Article trimmed from 7 to 5 pages: shorter Introduction, components table, step-by-step signal flow through the circuit, implementation stages, one merged test table. Build guide for the team added (`hardware/build-guide.md`) |
| 2026-11-18 | Fig. 3 is now the complete circuit with every ESP32-S3 pin (OLED assumed 4-pin I²C); pin table added to the plan; transistor for the buzzer added to the parts list. Circuit schematic added to the article (Fig. 3). Parts list now has Spanish search terms for buying in Peru. We don't own a multimeter: borrow one from a lab |
| 2026-11-18 | Hardware adapted to the parts we own (ACS712, ESP32-S3, OLED). Specs, Methodology and Figures 1–2 updated. Relay bench idea dropped. ACS712 confirmed as the 20 A version |
| 2026-11-11 | Figures 1–3 drawn (TikZ); Fig. 1 redone as a layered diagram with a legend. Methodology draft merged (`METODOLOGIA` branch). README simplified |
| 2026-11-04 | Repo published on GitHub (private) |
| 2026-10-28 | Article set up; Introduction drafted with 15 verified references; authors added |
| 2026-10-14 | System design finished (specification, plan, research) |

Full history: `git log`.
