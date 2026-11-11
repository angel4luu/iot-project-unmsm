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
| System | Design finished. Nothing built yet | Break the plan into tasks (`/speckit.tasks`) |
| Article | Introduction, Methodology and Figures 1–3 done (6 pages; Results still empty) | Trim to fit the page limit |

*Last updated: 2026-11-11*

## Roadmap

### System

| Step | What it means | Status |
|---|---|---|
| Design | Requirements, architecture, research, data formats | ✅ Oct 14 |
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
| Figures 1–3 (architecture, wiring, flowchart) | ✅ Nov 11 (add a prototype photo once built) |
| Results and Discussion | ⬜ needs the experiments |
| Conclusions and abstract | ⬜ |
| Review and submission | ⬜ |

## Open decisions

| # | Question | Blocks |
|---|---|---|
| 1 | Which voltage sensor: certified adapter or ZMPT101B board? | Hardware, Methodology text |
| 2 | How to calculate measurement uncertainty, and how many repetitions per test | Methodology text, experiments |
| 3 | Parts list and total cost | Comparison table in Results |
| 4 | Which conference or journal (page limit, deadline) | Final format |
| 5 | Faculty name and contact emails for the author block | Submission |
| 6 | Which service sends remote alerts | Alerts |

## Key decisions made

- Wi-Fi, not LoRa. No automatic power cut-off (safety).
- The specs win over the article proposal; differences are listed in [article/README.md](article/README.md#decisions).
- Article in Spanish, IEEE conference format, decimal comma.
- No power-factor claims; anomaly detection and forecasting are future work.

## Recent updates

| Date | Update |
|---|---|
| 2026-11-11 | Figures 1–3 drawn (TikZ); Fig. 1 redone as a layered diagram with a legend. Methodology draft merged (`METODOLOGIA` branch). README simplified |
| 2026-11-04 | Repo published on GitHub (private) |
| 2026-10-28 | Article set up; Introduction drafted with 15 verified references; authors added |
| 2026-10-14 | System design finished (specification, plan, research) |

Full history: `git log`.
