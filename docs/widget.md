# Widget API

The embeddable widget talks to these routes. They need no staff account.
[`schema.yml`](../schema.yml) is the source of truth for the exact request and
response bodies.

| Method | Route | Auth | Purpose |
| --- | --- | --- | --- |
| `GET` | `/api/widget/config/?key=<site key>` | None | Public site settings and `agents_available` |
| `GET` | `/api/widget/challenge/?key=<site key>` | None | Proof-of-work challenge |
| `POST` | `/api/widget/conversations/` | Optional token | Start or continue a conversation |
| `GET` | `/api/widget/conversations/{id}/messages/?after=<id>` | Token | Public messages after an id |
| `POST` | `/api/widget/conversations/{id}/messages/` | Token | Send a message |
| `POST` | `/api/widget/conversations/{id}/read/` | Token | Mark messages read |
| `POST` | `/api/widget/conversations/{id}/contact/` | Token | Store the visitor's phone or email |
| `GET`, `POST` | `/api/widget/conversations/{id}/rating/` | Token | Read or submit the conversation rating |
| `POST` | `/api/widget/conversations/{id}/attachments/` | Token | Send a file as a message |
| `GET` | `/api/widget/attachments/{id}/download/` | Token | Signed download link |
| `POST` | `/api/widget/ws/ticket/` | Token | Single-use WebSocket ticket |

## Authentication and origin

Send the token returned by the first `POST /api/widget/conversations/` in an
`X-Visitor-Token` header. A missing, tampered or expired token, or the token of a
deactivated site, gets `401`. Tokens live for `VISITOR_TOKEN_LIFETIME_DAYS`
days and are replaced every time the visitor starts or continues a conversation.

The `Origin` header must be one of the site's `allowed_origins`. A missing
header, an unlisted origin or a site with no origins gets `403`. Widget routes
send CORS headers so the browser can read that response; the origin check is what
enforces access.

## Config and challenge

`GET /api/widget/config/?key=<site key>` returns the public site settings and
`agents_available`. `agents_available` is `true` while at least one active agent
or admin has a live presence entry with status `available`.

When `WIDGET_POW_DIFFICULTY` is nonzero, the client first reads
`GET /api/widget/challenge/?key=<site key>` and sends the returned `challenge`
and a valid `nonce` as `pow_challenge` and `pow_nonce` when starting a
conversation.

## Starting and continuing a conversation

`POST /api/widget/conversations/` accepts:

- `body` (required, up to 4000 characters): the first message.
- `site_key` (required without a token).
- `name`, `phone`, `email`: stored on the new visitor. The site's
  `require_name` and `require_contact` are enforced.
- `client_msg_id`: optional idempotency key.
- `pow_challenge`, `pow_nonce`: proof-of-work fields.

Without a token, the backend creates a visitor and a conversation. With a token,
the token is replaced by a fresh one and the message goes into the visitor's
current open conversation; if there is none, a new conversation is created. A
message into a `waiting_on_customer` conversation moves it back to
`in_progress`.

The response is `201` when a conversation was created and `200` otherwise. It
contains `token`, `conversation`, `message` and `agents_available`.

A conversation is a ticket with `channel` `chat`. Its title is the start of the
first message and its description is empty. It is routed to an available agent
immediately when possible. If not, offline fallback is scheduled; see
[API notes](api-notes.md#offline-fallback).

## Messages and read state

`GET /api/widget/conversations/{id}/messages/?after=<id>` returns
`{results, has_more, agents_available, unread_count}`. It returns at most 100
public messages, oldest first. `after` defaults to `0` and must be an integer
from 0 to 2^63-1. Internal notes are never returned.

`POST /api/widget/conversations/{id}/messages/` accepts `body` and an optional
`client_msg_id`. Sending into a resolved or closed conversation returns `409`
with `conversation_closed`.

`POST /api/widget/conversations/{id}/read/` accepts an optional
`last_read_comment_id` and returns `{last_read_comment_id, unread_count}`. The
marker only moves forward. See
[API notes](api-notes.md#read-state) for the unread rule.

For reconnects, use the same message-id cursor strategy described in
[API notes](api-notes.md#missed-message-recovery).

## Contact details

`POST /api/widget/conversations/{id}/contact/` stores the visitor's contact
details while the conversation is open. The body accepts `phone` and `email`;
at least one is required. An invalid phone or email returns `400`. A resolved or
closed conversation returns `409` with `conversation_closed`.

Only non-empty values that differ from the stored ones are updated. A change
writes a `contact` audit event on the ticket. The response is the visitor's
`{phone, email}`.

This is the route the widget uses after the `conversation.offline` event asks
for contact details. The event's `has_contact` field is `true` when the visitor
already left a phone number or an email, so the widget can skip asking.

## Ratings

`GET /api/widget/conversations/{id}/rating/` returns the existing rating or
`404`. `POST` submits `score` (1 to 5) and an optional `comment`. A conversation
can be rated only after it is resolved or closed, and only once. A conflict
returns `409` with `ticket_not_resolved` or `ticket_already_rated`.

## Attachments and downloads

`POST /api/widget/conversations/{id}/attachments/` is multipart. It accepts
`file`, an optional `body` and an optional `client_msg_id`. The file becomes a
message of its own, so it appears in order in the thread. It must pass the same
size, type and magic-byte checks as every other upload. A closed conversation
returns `409`.

`GET /api/widget/attachments/{id}/download/` returns `{url, expires_in}`. A
visitor can only get a link for a file on a public message of their own
conversation; everything else is `404`.

## WebSocket ticket

`POST /api/widget/ws/ticket/` returns `{ticket, expires_in}` for
`/ws/?ticket=<ticket>`. The ticket is single-use and expires after
`WS_TICKET_TTL_SECONDS`. See [Realtime](realtime.md).

## Limits

Widget routes are throttled per IP address and per visitor. Starting a
conversation and uploading files have their own stricter scopes. The full table
is in [Operations](operations.md#rate-limits).
