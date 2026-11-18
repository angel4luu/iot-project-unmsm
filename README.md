# Intelligent Energy Monitoring System — UNMSM IoT, Grupo 5

A small device measures the electricity used by one lab circuit, sends the data
over Wi-Fi to a local server, and shows it on a dashboard with alerts when
consumption goes over a limit. We are also writing an IEEE article (in Spanish)
about it.

**Team**: Matias Vincula · Abigail Llana · Oscar Monzon · Angela Jara · Illary León

> Status: ✅ done · 🔄 in progress · ⏳ next · ⬜ not started · ⏸ on hold

## Where things are

| What | Where |
|---|---|
| System specification (the source of truth) | [specs/001-energy-monitoring-system/](specs/001-energy-monitoring-system/) |
| Article (LaTeX) and its tracker | [article/](article/) · [article/README.md](article/README.md) |
| Rules for AI assistants | [CLAUDE.md](CLAUDE.md), [AGENTS.md](AGENTS.md) |

Build the article: `make -C article` → `article/build/main.pdf`

## Status at a glance

| Track | Where we are | Next |
|---|---|---|
| System | Design finished and adapted to the team's own parts (one AC adapter + resistors to buy). Nothing built yet | Confirm the multimeter model, then break the plan into tasks (`/speckit.tasks`) |
| Article | Introduction, Methodology and Figures 1–4 done and updated to the new hardware (7 pages; Results still empty) | Trim to fit the page limit |

*Last updated: 2026-11-18*

## Roadmap

### System

| Step | What it means | Status |
|---|---|---|
| Design | Requirements, architecture, research, data formats | ✅ Oct 14 (hardware adapted Nov 18) |
| Task list | Turn the design into an ordered to-do list | ⏳ |
| Simulated version | Server, database and dashboard working with fake data | ⬜ |
| Device software | Measuring and calculating on the ESP32 | ⬜ |
| Safety review and calibration | Qualified review **before** connecting to mains; compare against a reference meter | ⬜ |
| Full system tests | Real device end to end, network-outage recovery, security | ⬜ |
| Alerts | Local LED/buzzer and remote notifications | ⬜ |
| Final acceptance | Check all success criteria | ⬜ |

### Article

| Step | Status |
|---|---|
| Setup and requirements | ✅ Oct 28 |
| Introduction (with literature review) | ✅ draft Oct 28 |
| Methodology | ✅ draft Nov 11 |
| Page budget and trimming | ⏳ |
| Figures 1–4 (architecture, wiring, circuit schematic, flowchart) | ✅ Nov 18 (schematic values to check at the bench; add a prototype photo once built) |
| Results and Discussion | ⬜ needs the experiments |
| Conclusions and abstract | ⬜ |
| Review and submission | ⬜ |

## Open decisions

| # | Question | Blocks |
|---|---|---|
| 1 | Reference meter: we don't own one. Borrow a true-RMS multimeter from a university lab, or buy one? | Calibration, accuracy results |
| 2 | How to calculate measurement uncertainty, and how many repetitions per test | Methodology text, experiments |
| 3 | Parts list and total cost | Comparison table in Results |
| 4 | Which conference or journal (page limit, deadline) | Final format |
| 5 | Faculty name and contact emails for the author block | Submission |
| 6 | Which service sends remote alerts | Alerts |

## Key decisions made

- Wi-Fi, not LoRa. No automatic power cut-off (safety).
- Educational prototype built from our own kit: ESP32-S3, ACS712 current sensor (20 A version: measures up to 5 A, about 1.1 kW), OLED, RGB LED, buzzer, DHT22 (calibration only). Only a certified AC adapter and resistors are bought. The ACS712 always goes in a closed box, never on the breadboard.
- The specs win over the article proposal; differences are listed in [article/README.md](article/README.md#decisions).
- Article in Spanish, IEEE conference format, decimal comma.
- No power-factor claims; anomaly detection and forecasting are future work.

## Recent updates

| Date | Update |
|---|---|
| 2026-11-18 | Fig. 3 is now the complete circuit with every ESP32-S3 pin (OLED assumed 4-pin I²C); pin table added to the plan; transistor for the buzzer added to the parts list. Circuit schematic added to the article (Fig. 3). Parts list now has Spanish search terms for buying in Peru. We don't own a multimeter: borrow one from a lab |
| 2026-11-18 | Hardware adapted to the parts we own (ACS712, ESP32-S3, OLED). Specs, Methodology and Figures 1–2 updated. Relay bench idea dropped. ACS712 confirmed as the 20 A version |
| 2026-11-11 | Figures 1–3 drawn (TikZ); Fig. 1 redone as a layered diagram with a legend. Methodology draft merged (`METODOLOGIA` branch). README simplified |
| 2026-11-04 | Repo published on GitHub (private) |
| 2026-10-28 | Article set up; Introduction drafted with 15 verified references; authors added |
| 2026-10-14 | System design finished (specification, plan, research) |

Full history: `git log`.
