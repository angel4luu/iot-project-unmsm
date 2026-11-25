# Low-voltage wiring review checklist

Complete every item and obtain both signatures before each 12 V session. Keep
the adapter unplugged while wiring and during this review. If any item cannot be
confirmed, stop and correct the assembly before connecting the adapter.

| Check | Requirement | Complete |
|---|---|---|
| ☐ | Adapter is certified, thermally protected, rated at least 2 A, and its case and cable are intact. | ☐ |
| ☐ | Adapter has never been opened or modified. | ☐ |
| ☐ | Adapter is unplugged while the circuit is wired or changed. | ☐ |
| ☐ | The 12 V loop is jack terminal 1 → ACS712 IP+ / IP− → bulb → jack terminal 2. | ☐ |
| ☐ | The current loop is off the breadboard; only the ACS712 low-voltage header connects to the breadboard. | ☐ |
| ☐ | Jack and ACS712 screw terminals are tight, with no loose strands. | ☐ |
| ☐ | Loop conductors are 18 AWG (at least 0.75 mm²) and insulation is intact. | ☐ |
| ☐ | No bare conductors cross or can touch; clips and bulb terminals cannot touch each other. | ☐ |
| ☐ | Bulb is on a heat-safe support, clear of cables and other parts; its surface becomes hot. | ☐ |
| ☐ | ESP32 circuitry is low-voltage only, with a common low-voltage GND. | ☐ |
| ☐ | ACS712 VCC is connected to 5 V; GND and OUT are checked against the module labels. | ☐ |
| ☐ | Electrolytic 10 µF capacitor polarity matches its markings and the circuit drawing. | ☐ |
| ☐ | Buzzer driver and buzzer polarity/orientation are checked against the schematic. | ☐ |
| ☐ | RGB LED type and polarity are confirmed; each channel has its series resistor. | ☐ |
| ☐ | Both reviewers know to stop by unplugging the adapter; no rewiring is done while it is plugged in. | ☐ |

## Review record

| Reviewer | Name or role | Signature | Date (YYYY-MM-DD) |
|---|---|---|---|
| 1 | operator A | ____________________ | ____________________ |
| 2 | operator B | ____________________ | ____________________ |

**Session gate:** do not begin the 12 V session until every check is complete
and both reviewers have signed and dated this checklist. Record the completed
review in `guides/safety/review-record.md` as required by T063.

## Scope boundary

This checklist covers only the isolated extra-low-voltage 12 V loop. Any 220 V
work is out of scope for this procedure. A future 220 V test would require an
RCD, a closed test box around the ACS712, and a signed review by a qualified
person before energizing; do not bypass any of those requirements.
