# Telemetry contract fixtures

One valid and one invalid payload per schema in
`specs/001-energy-monitoring-system/contracts/` (measurement fixtures live in
`contracts/examples/`). Each invalid fixture has exactly one defect, asserted in
`tests/contract/test_schemas.py`:

| Fixture | Defect |
|---|---|
| `invalid-node-status.json` | `state` is not in the enum |
| `invalid-node-event.json` | required `local_warning_active` is missing |
| `invalid-threshold-config.json` | `active_power_limit_W` is 0 (must be > 0) |
| `invalid-measurement-ack.json` | `accepted` without `stored_at` |

Identifiers are placeholders (`node-001`, `lab-load-001`, example UUIDs); no real
node IDs, endpoints, or secrets.
