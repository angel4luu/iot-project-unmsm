# Nominal calibration and plausibility procedure

This procedure uses nominal (datasheet and circuit) coefficients without a
reference meter. **Every reading produced by this procedure is not validated.**
The E1 result is a plausibility check for the tested setup, not an accuracy
claim or a calibration against a traceable standard.

Do not start a 12 V session until the low-voltage wiring review is complete and
signed by two team members in accordance with
[`guides/safety/review-checklist.md`](../safety/review-checklist.md) and T063.
Keep the adapter unplugged whenever wiring is changed. The loop is 12 V AC or
less; 220 V work is outside this procedure.

## Procedure

1. **Confirm the setup and bring-up software.** Use
   `firmware/bringup/stage34_adc_logger` (T029) for the initial GPIO4/GPIO5
   analog-channel check and raw USB capture. Run the complete node firmware in
   `firmware/` for calibration registration and E1 telemetry once its
   measurement and calibration tasks are available; the ADC logger alone does
   not produce the accepted 5 s measurement summaries required for E1. Confirm
   the signed T063 checklist is present before connecting the bulb loop.

2. **Record the run identity before energizing.** Record the build/wiring
   revision, firmware commit, ADC resolution/attenuation and sampling settings,
   ACS712 variant (including its nominal 100 mV/A sensitivity), adapter
   identity and rating, circuit wiring, operator role, bulb/load identity and
   nameplate power, date, and environmental notes. Explicitly record: “No
   reference instrument was used.” Use role placeholders such as `operator A`
   and `operator B` in examples; keep personal names out of tracked evidence.

3. **Check the channels with the logger.** With the adapter unplugged, inspect
   the low-voltage wiring. Use the stage 3–4 ADC logger to check the bias and
   ACS712 zero-current output and, where appropriate, capture the adapter
   waveform. Stop if either ADC channel is clipped, outside its safe range, or
   unstable. Preserve the raw capture; it is diagnostic evidence, not
   reference-meter calibration.

4. **Warm up and capture the zero-current offset.** Leave the bulb disconnected
   from one loop terminal. After the wiring review, connect and power the
   isolated 12 V setup, allow at least 10 minutes for warm-up, then capture 60
   seconds with zero current through the ACS712. Calculate and record the
   offset using the firmware procedure. Repeat this zero-current capture before
   each separate session.

5. **Check polarity and correct the coefficient sign.** Unplug the adapter,
   connect the bulb in the reviewed loop, then reconnect power. With the bulb
   on, active power must be positive. If it is negative, unplug before changing
   anything and correct the sign in the calibration coefficients; do not
   reverse the wiring as a shortcut. Preserve the observed check and resulting
   coefficient revision.

6. **Freeze and register the nominal revision.** Freeze the selected nominal
   coefficients after the offset and polarity checks. Register the frozen
   revision with `energyctl calibration register`; its available options are
   documented by `energyctl --help`. Record the returned revision identifier
   and verify that the node reports it. Do not edit a registered revision in
   place; create a new revision and evidence record if coefficients change.

7. **Run E1, including pilots and the planned final sample.** On each run,
   collect at least 5 minutes with the bulb on and at least 1 minute with it
   off. First complete 3 pilot runs on different days. Then compute the final
   run count from plan › Experiment runs: choose the smallest `n ≤ 10` with
   `n ≥ (t₀.₉₇₅,ₙ₋₁ · s / e)²`, where `s` is the standard deviation of
   per-run power deviation and `e = 5` percentage points. Keep the three pilot
   runs in the evidence; do not silently replace an inconvenient run.

8. **Apply the plausibility criteria.** For each accepted E1 run, verify RMS
   voltage is 10–16 V, active power is positive, and active power is within
   ±20% of the bulb nameplate (16–24 W for a 20 W bulb). With the bulb off,
   current must be within the firmware's absolute noise limit. Windows flagged
   only `calibration_missing` are admissible; any other quality flag makes the
   affected window inadmissible. Report all measured values as **not validated**
   and do not claim measurement accuracy from the nameplate comparison.

9. **Preserve and evaluate the evidence.** Keep raw waveform captures and
   exported 5 s summaries under the ignored `experiments/data/` directory. Add
   the tracked manifest at
   `experiments/manifests/plausibility-YYYYMMDD.json`, recording the run IDs,
   UTC intervals, setup and firmware/calibration revisions, exclusions,
   evaluation command, and SHA-256 hashes for every input. Run
   `experiments/evaluation/plausibility.py` (T061) on the exported summaries
   and load nameplate CSV; review its E1 output and hash manifest against the
   preserved inputs before reporting the result.

## Reporting label

Use the literal label **not validated** on every displayed, exported, or
published measurement from the nominal revision. “Valid” quality means only
that a window passed the software quality checks; it does not mean the nominal
calibration was validated with a reference instrument.
