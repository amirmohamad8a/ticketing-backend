# Architecture

## Layers

Dependencies point downwards. A module may import from a lower layer, never from a
higher one.

| Layer | Apps | Allowed imports |
| --- | --- | --- |
| Infrastructure | `core` | Django, third-party libraries, `core` modules only |
| Accounts | `accounts` | `core` |
| Tickets | `tickets` | `core`, `accounts`, `chat.models` |
| Chat | `chat` | `core`, `accounts`, `tickets` |
| Transport | `realtime` | `core`, `accounts`, `tickets`, `chat` |
| Read-only consumers | `stats`, `audit` | Any lower layer |

`stats` and `audit` are not imported by any other app. `realtime` is not imported
by any domain app; the ASGI routing and middleware are its only entry points.

## Model imports

Cross-app model imports are allowed only for Django models and foreign-key string
references. Services, serializers, views, admin modules, tasks and signals are not
imported across a layer boundary except for the documented event receivers below.

The one explicit exception is `tickets.serializers -> chat.models`, used for the
read-only nested `visitor` and `site` ticket output. Test packages are ignored by
the import contracts because they intentionally build cross-app fixtures.

## Domain events

| Event | Defined in | Sent by | Handled by |
| --- | --- | --- | --- |
| `accounts.user_deactivated` | `accounts/signals.py` | `accounts.services.apply_user_side_effects` inside the transaction | `tickets.signals.release_user_tickets` calls `release_tickets` |
| `accounts.user_demoted` | `accounts/signals.py` | `accounts.services.apply_user_side_effects` inside the transaction | `tickets.signals.release_user_tickets` calls `release_tickets` |
| `tickets.tickets_released` | `tickets/signals.py` | `tickets.assignment.release_tickets` after clearing assignees | `chat.signals.reroute_released_chat_tickets` re-routes released chat tickets |

The signals are synchronous. The receiver work stays in the caller's transaction,
so a failure rolls back both the user change and the ticket release. When a user is
both deactivated and demoted, the deactivation signal is sent once and covers the
release.

## Registries

| Registry | Registered by | Consumers |
| --- | --- | --- |
| Scrape collectors (`core.metrics.register_scrape_collector`) | `stats.apps.StatsConfig` | Metrics endpoint |
| File reference sources (`core.orphans.register_file_reference_source`) | `accounts.apps.AccountsConfig` (avatars), `tickets.apps.TicketsConfig` (attachments) | `find_orphan_files` |

Registries keep `core` free of upward imports while letting apps contribute data
to core-owned endpoints and commands.

## Transport modules

`core.events`, `core.groups` and `core.tickets` contain the publishing side of the
realtime transport and the single-use WebSocket tickets. Agent presence lives in
`chat.presence`. The `realtime` app keeps ASGI consumers, handshake authentication,
access checks, routing and HTTP views.

Cache key prefixes are part of the contract:

| Prefix | Owner |
| --- | --- |
| `ws-ticket:` | `core.tickets` |
| `presence:` | `chat.presence` |
| `chat:agents-available` | `chat.availability` |
