# Article (IEEE)

LaTeX sources for the paper *Design, Implementation, and Experimental Evaluation
of an IoT-Based System for Real-Time Electrical Energy Consumption Monitoring and
Analysis*. The requirements are in [SPEC.md](SPEC.md). Overall project tracking is
in the [root README](../README.md#roadmap).

## Build

Requires TeX Live with `IEEEtran`, `latexmk`, and `bibtex`.

```sh
make            # build/main.pdf
make watch      # rebuild on save
make clean      # remove aux files, keep PDF
make distclean  # remove build/
```

The bibliography is active (BibTeX with `IEEEtran.bst`). Every entry is DOI-verified,
or for official statistics checked at the source.

## Layout

```text
article/
├── main.tex                 preamble, abstract, section includes
├── metadata.tex             title, authors, affiliation, keywords
├── sections/
│   ├── 01-introduction.tex
│   ├── 02-methodology.tex
│   ├── 03-results-discussion.tex
│   └── 04-conclusions.tex
├── figures/                 TikZ figure sources (\input from the sections)
├── tables/                  tables written as .tex, generated or hand-written
├── references.bib           verified entries only
├── research/                literature evidence (candidates, comparison, stats)
├── handoff/                 self-contained Codex task prompts
├── SPEC.md                  article requirements
├── latexmkrc, Makefile
└── build/                   output (git-ignored)
```

Conventions:
- The paper is written in **Spanish** (`babel` spanish). Code comments and repo docs stay in English.
- The specs in `../specs/` are the source of truth. `SPEC.md` is guidance only, and every deviation is recorded under Decisions below.
- One sentence per line in the `.tex` files, so diffs stay readable.
- Labels use `sec:`, `fig:`, `tab:`, and `eq:` prefixes.
- Numbers in results tables come from scripts under `../experiments/evaluation/`
  and are never typed by hand. Each table states the evidence artifact it comes from.
- Figures are vector (PDF) wherever possible, and each one has its source next to it.

## Section-to-evidence map

| Paper section | Project source |
|---|---|
| II-B Architecture | `plan.md` › Component and Deployment Design |
| II-C Prototype (Table I, Fig. 2) | `plan.md` › Hardware list, Front end and pin allocation; `research.md` R-001, R-002 |
| II-D Acquisition model | `plan.md` › Quantities; `research.md` R-003; FR-003 |
| II-E Algorithm | `plan.md` › Threshold and alert lifecycle; future analysis module |
| II-F/G Experiments, metrics | `plan.md` › Calibration procedure; SC-001–SC-006 |
| III-B Accuracy | Calibration report (milestone M4) |
| III-C Patterns | Dataset export plus analysis (M7, `experiments/`) |
| III-D Performance | Recovery and latency reports (M5, M6) |

## Status

| # | Step | Status |
|---|---|---|
| A0 | Requirements received; repo setup | ✅ 2026-10-28 |
| A1 | Resolve the decisions that block writing (AD-2 to AD-5) | ✅ 2026-10-28 |
| A2 | **Introduction**: literature search (10–15 papers, 2021–2026), `references.bib`, draft of Section I | ✅ draft 2026-10-28 |
| A3 | Page budget and trimming | ✅ 2026-11-18 (7 → 5 pages; see AD-12) |
| A4 | Draft Methodology (no results needed) | ✅ draft 2026-11-11 (`METODOLOGIA` branch); Figures 1–3 drawn in TikZ; hardware text and Figs. 1–2 updated 2026-11-18 (AD-10) |
| A5 | Experiments, then Results/Discussion (depends on M4–M7) | ⬜ |
| A6 | Conclusions and abstract | ⬜ |
| A7 | Internal review and revision | ⬜ |
| A8 | Venue template check, PDF eXpress, submission | ⬜ |

<a id="decisions"></a>
## Decisions

| # | Decision | Date |
|---|---|---|
| AD-1 | Written in LaTeX with `IEEEtran` in conference mode, built with latexmk/BibTeX | 2026-10-28 |
| AD-2 | Language: Spanish, with a Spanish title (the proposal's translation) | 2026-10-28 |
| AD-3 | *Superseded by AD-10.* Hardware follows `plan.md`/`research.md` R-001 (ESP32 + ADS131M02 + SCT-013-020 + isolated voltage sensing), not the proposal's PZEM-004T. The proposal allows "u otro módulo adecuado" | 2026-10-28 |
| AD-4 | Measured quantities follow the spec: V_RMS, I_RMS, active power, active energy. P is defined as the mean of v·i (FR-003), not V·I·PF. Power factor and frequency get no accuracy claim; they appear only as a limitation and future work. The accuracy table has no PF row | 2026-10-28 |
| AD-5 | "Analysis" means what the spec delivers: hourly/daily/weekly aggregation, peak-period identification (SC-005), and threshold alerts with confirmation that reject startup surges (FR-011, SC-004). Statistical anomaly detection and forecasting are future work (plan › Future Dataset). "Detection accuracy" is measured as correct firing/non-firing of threshold alerts under scripted loads | 2026-10-28 |
| AD-6 | Venue not chosen. Keep the IEEE conference defaults (Letter, ~6 pages) and recheck when one is chosen | 2026-10-28 (deferred) |
| AD-7 | Numbers use a decimal comma (`siunitx` `output-decimal-marker={,}`), following the Spanish/INEI convention. Write numbers with `\SI{}`/`\num{}` | 2026-10-28 |
| AD-8 | Prior-work limitations are narrowed to what the evidence supports (`research/limitations-evidence.md`): heterogeneous validation, rarely measured latency, no controlled outage-recovery evaluation, and analytics evaluated apart from the hardware. The proposal's claims of "no power-factor analysis" and "always depends on connectivity" are contradicted by the literature and are not used | 2026-10-28 |
| AD-9 | Figures are TikZ sources in `figures/`, `\input` into the sections, single-column, black-and-white friendly. Fig. 2 is a single-line wiring diagram without pin numbers until the PCB review; add a labelled photo once the prototype is built | 2026-11-11 |
| AD-14 | No reference meter (user decision, budget). Constitution amended to 2.0.0 (Principle II): a demonstration build may run on nominal coefficients if every value is labeled "not validated" and no accuracy is claimed. Article: research design, Introduction gap and contribution 4 reworded; Table I without the Referencia row; multimeter removed from Figs. 1 and 4; session flow without reference readings; Table II E1–E3 become a plausibility check (V in 180–250 V, P > 0, \|d_P\| ≤ 15 % of nameplate), E4 a fan observed only; Eq. (6) is the deviation from nameplate; Results III-B renamed to plausibility; limitation added. Paper back to 5 pages | 2026-11-18 |
| AD-13 | Test flow made explicit (user request): Fig. 4 shows the test setup (outlet with 30 mA RCD, ACS712-only test box, load, node, server); II-F adds a six-step session flow; Table II names the load or action for each test. The reference-meter part is superseded by AD-14. Methodology now ends on page 5, still within the 6-page budget; Results figures renumbered to Fig. 5–7 | 2026-11-18 |
| AD-12 | Page budget: 6 pages total. Intro + Methodology fit in about 4 pages (Intro about 1 page, Methodology about 3 incl. figures). The old block wiring figure was dropped (its content is in the full circuit, Table I and the text); scenarios and metrics are merged into one single-column table; the prototype is described as a components table plus a numbered signal-flow list; implementation is a 5-stage list. The detailed build steps live in `hardware/build-guide.md`, not in the paper | 2026-11-18 |
| AD-11 | Fig. 3 is a full-width circuitikz schematic of the complete low-voltage circuit with every ESP32-S3 pin (`figures/fig02b-circuit.tex`), using the nominal values and pin table from plan › Front end and pin allocation; the caption says they are to be verified at the bench. Pins are grouped by function, not physical position. OLED assumed 4-pin SSD1306 on I²C until checked. If the bench changes a value, update plan.md first, then the figure and text | 2026-11-18 |
| AD-10 | Hardware follows the 2026-11-18 spec amendment (research R-001–R-005, plan › Hardware list): ESP32-S3 internal ADC with alternating sampling and delay correction, ACS712, certified AC-AC adapter, RAM queue + NVS checkpoint, SNTP without RTC, OLED/RGB LED. The paper presents it as an educational prototype, cites marin2026rmsbenchmark for a comparable ACS712 design, validates W/Wh only on resistive loads (V·I reference from a true-RMS multimeter), and reports the inductive/nonlinear load for V and I only. ACS712 confirmed as the 20 A version (0,5–5 A, about 1,1 kW). The multimeter `\todo` was removed with AD-14. Minimal MVP cutoff (2026-11-18): DHT22 removed from Table I and Fig. 3 (GPIO15 freed); polarity checked by positive P during calibration; protection row is the 30 mA RCD (home panel or portable). Low-voltage circuit on a breadboard (Table I conditioning row); adapter via a female barrel jack with screw terminals, drawn in Fig. 2 and named in Table I | 2026-11-18 |
