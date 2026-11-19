# Intelligent Energy Monitoring System — UNMSM IoT, Grupo 5

A small device measures the electricity used by one appliance plugged into a protected wall outlet, sends the data
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
| System | Design finished and adapted to the team's own parts (one AC adapter + resistors to buy). Nothing built yet | Consistency check (`/speckit.analyze`), then start building: repo setup, then the server with fake data and the breadboard tests in parallel |
| Article | Introduction done; Methodology revised after the reviewer's comments and trimmed back to a 5-page paper | Compile in Overleaf and confirm 5 pages; fix the test loads in the specs; then Results, once the experiments run |

*Last updated: 2026-11-18*

## Roadmap

### System

| Step | What it means | Status |
|---|---|---|
| Design | Requirements, architecture, research, data formats | ✅ Oct 14 (hardware adapted Nov 18) |
| Task list | Turn the design into an ordered to-do list (93 tasks, hardware and software tracks in parallel) | ✅ Nov 18 |
| Simulated version | Server, database and dashboard working with fake data | ⏳ |
| Device software | Measuring and calculating on the ESP32 | ⬜ |
| Safety review and calibration | Qualified review **before** connecting to mains; nominal calibration and plausibility check (no reference meter) | ⬜ |
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
| Figures 1–3 (architecture, full circuit, flowchart) | ✅ Nov 18 (old wiring figure dropped; circuit values to check at the bench; add a prototype photo once built) |
| Results and Discussion | ⬜ needs the experiments |
| Conclusions and abstract | ⬜ |
| Review and submission | ⬜ |

## Open decisions

| # | Question | Blocks |
|---|---|---|
| 0 | Who is the qualified person (licensed electrician or electrical-engineering teacher) who reviews the setup and signs the safety review? | Any 220 V test |
| 1 | ~~Reference meter~~ Resolved 2026-11-18: none; readings are shown as "not validated" (constitution 2.0.0). A True RMS meter lent by the electrician could be added later | — |
| 2 | ~~How many repetitions per test~~ Rule set 2026-11-18: 3 pilot runs per load, then a formula fixes the final number (max 10); 3 runs for the 1-hour and outage tests | — |
| 8 | Test loads: the article now uses two 100 W bulbs (one is below the sensor's range) and a 1 kW load without a thermostat (not an iron). The specs and build guide still say 100 W / iron and need a Spec Kit amendment | Plan, build guide |
| 9 | Tolerances of the resistors and AC adapter we buy (needed for the uncertainty estimate) | Methodology text |
| 7 | Seven-day dataset for the "busiest hour" test (E8): short supervised sessions over a week, or the simulator? | Task T074, Results |
| 3 | Parts list and total cost | Comparison table in Results |
| 4 | Which conference or journal (page limit, deadline) | Final format |
| 5 | Faculty name and contact emails for the author block | Submission |
| 6 | Which service sends remote alerts | Alerts |

## Key decisions made

- Wi-Fi, not LoRa. No automatic power cut-off (safety).
- Educational prototype built from our own kit: ESP32-S3, ACS712 current sensor (20 A version: measures up to 5 A, about 1.1 kW), OLED, RGB LED, buzzer. All low-voltage wiring on a breadboard (no soldering). Minimal purchases: certified AC adapter with a female barrel jack with screw terminals, resistors and capacitors, a transistor for the buzzer, a small test box for the ACS712 only (plug, ACS712 and a socket for the appliance), and a portable 30 mA RCD only if the home panel has none. The ACS712 always goes in a closed box, never on the breadboard. No reference multimeter: the dashboard labels every reading "not validated" and the article makes no accuracy claim.
- The specs win over the article proposal; differences are listed in [article/README.md](article/README.md#decisions).
- Article in Spanish, IEEE conference format, decimal comma.
- No power-factor claims; anomaly detection and forecasting are future work.

## Recent updates

| Date | Update |
|---|---|
| 2026-11-18 | Article Methodology revised after the reviewer's comments: clearer test units and repetitions, safer and in-range test loads, step-by-step outage and alert tests, honest wording on delivery guarantees, uncertainty without a reference meter, a separate metrics section and pseudocode. Details in article/README.md (AD-15) |
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
