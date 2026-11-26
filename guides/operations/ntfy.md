# ntfy notifications (decision 6, T109–T110)

Threshold alerts can reach a phone through [ntfy](https://ntfy.sh): the ingestion
service's notification worker posts each new alert once (outbox, retries) as an
ntfy JSON publish with a Spanish title, priority, and tags. The dashboard stays
LAN-only; this is outbound HTTPS only (FR-007).

## Accepted risk

The free ntfy.sh tier cannot reserve a topic or restrict who reads it. The only
protection is the topic name, so it is treated as a secret: it lives only in
`infrastructure/secrets/notification-token` (git-ignored) and is never logged or
recorded in evidence. Anyone who learns it could read the alerts or post
fake ones. The team accepted this for the lab prototype (2026-11-25): messages carry
only the node and circuit ids, the not-validated power value and limit, quality, and
the alert id. A paid ntfy plan (reserved topic plus access token) or a generic
webhook with a bearer token removes the risk if it ever matters.

## Setup

1. Choose a topic name yourself, for example `unmsm-grupo5-alertas-2026`. Rules
   the service checks: 1–64 characters, only letters, digits, `_` and `-` (no
   spaces or accents). A longer, less obvious name is harder for others to find.
2. In the ntfy phone app, tap **+** (subscribe to topic), enter that name, and keep
   the server as `ntfy.sh`.
3. Write the same name into the secret file, alone on one line, with any editor or:

   ```
   printf '%s\n' 'unmsm-grupo5-alertas-2026' > infrastructure/secrets/notification-token
   chmod 600 infrastructure/secrets/notification-token
   ```

   The file is git-ignored; do not put the name anywhere tracked.
4. In `.env` (git-ignored), set:

   ```
   NOTIFICATION_WEBHOOK_URL=https://ntfy.sh
   NOTIFICATION_FORMAT=ntfy
   ```

   The URL is the server root; the topic travels in the JSON body, never in the URL.
5. `make infra-up`. If the configuration is wrong, the service logs
   `notification_webhook_configuration_invalid` and keeps running with delivery
   disabled (alerts stay `pending` in the outbox).

## Check (T110)

With the phone at hand: `make ntfy-check`. It publishes one sustained simulated
episode as `sim-001`, waits until the service marks the notification `delivered`,
asks three yes/no questions (received, Spanish text, within about 10 s), and writes
`experiments/manifests/ntfy-YYYYMMDD.json` without the URL or topic.

## Turning it off

Clear `NOTIFICATION_WEBHOOK_URL` in `.env` and run `make infra-up`. Do this before
`make acceptance-simulated`: the US3 acceptance tests use their own fake receivers
and skip while the service's worker is sending real notifications.
