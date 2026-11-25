# US2 operator check: find the busiest hour (T075, SC-005)

SC-005: a first-time user can identify the highest-consumption hour in a seven-day
dataset in under 2 minutes without assistance. This sheet is the procedure and the
record. Fill in one row per participant; keep the sheet with the run evidence.

## Before the session (operator)

1. Stack running (`make infra-up`) and the seven-day dataset loaded
   (`make dataset-seven-day`, manifest `experiments/manifests/seven-day.json`).
2. Open the dashboard "Energy overview" on the lab PC, logged in as the viewer
   account, with node `sim-history` selected and the time range set to
   **2026-11-16 00:00 to 2026-11-23 00:00** (America/Lima). Scroll to the top.
3. Known answer (do not show it to the participant): **Thursday 2026-11-19,
   18:00–19:00 Lima, 23.86 Wh**. The runner-up is Tuesday 2026-11-17 17:00
   (20.32 Wh).

## Participant

- Has not seen this dashboard before and was not involved in building it.
- Gets no help after the task is read. Questions are answered with "please do
  what you think is right".

## Task (read aloud, word for word)

> "This page shows the electricity used by a lamp over one week. Please tell me
> the hour of the week in which it used the most energy: the day and the hour.
> Say it out loud when you are sure."

## Timing and pass rule

- Start the timer when you finish reading the task; stop it when the participant
  states a day and an hour.
- Pass: the stated day and hour match the known answer **and** the time is under
  2:00. A wrong answer is a fail, whatever the time.
- Values on the page are labelled "not validated" (simulated data); that does not
  affect this check.

## Record

| Date | Participant (initials) | Time (m:ss) | Answer given | Correct? | Pass? | Operator |
|---|---|---|---|---|---|---|
| | | | | | | |
| | | | | | | |
| | | | | | | |

Notes (where the participant looked first, hesitations, anything confusing):
