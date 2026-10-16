# Ticketing Backend

A support-ticketing REST API built with Django and Django REST Framework, with a real-time chat layer on top. Customers open tickets, website visitors talk to agents through an embeddable chat widget, agents work conversations and tickets through a validated status workflow, and every change is recorded in an append-only audit log.

## Features

- Three roles (customer, agent, admin) on a custom user model
- Self-service registration at `POST /api/auth/register/`: it always creates a customer (a role can never be chosen), checks the password with Django's validators and accepts an optional unique Iranian mobile number, which is normalized to `09XXXXXXXXX`
- Profile at `GET/PATCH /api/auth/me/`: first and last name, an optional phone number and an optional avatar (PNG, JPEG or WebP up to 2 MB, verified as a real image and stored under a random name). The username and role cannot be changed there. The response carries an `avatar_download_url` instead of a file URL. Agents and admins also get `max_concurrent_chats` (1 to 50, default 5), the number of open chats they accept at the same time
- Password change at `POST /api/auth/password/change/`: it needs the current password, applies Django's validators, revokes every refresh token of the user and returns a fresh token pair for the session that made the change
- User management for admins at `/api/users/`: list with `role` and `is_active` filters, create users (agents by default), change roles, deactivate and reactivate accounts and reset passwords. Every change writes a row to an append-only `UserEvent` log, deactivation and password resets revoke the user's sessions, and an admin cannot demote or deactivate themselves or reset their own password there
- Agents list for assignment dropdowns at `GET /api/agents/`: the id, display name and role of every active agent and admin, readable by agents and admins only. It is not paginated and exposes no usernames, phone numbers or other account details
- Chat sites for admins at `/api/sites/`: a `Site` is a website that will host the chat widget. It has a name, an auto-generated public key, a list of allowed origins, an active flag and the widget settings (greeting, primary color, position, offline timeout, whether a name or a contact is required). Allowed origins are validated, normalized to the form browsers send in the `Origin` header and deduplicated. Sites can be listed (filterable by `key` and `is_active`), created, read and updated, and the key can be rotated at `POST /api/sites/{id}/rotate-key/`. A site is deactivated rather than deleted
- Chat visitors and ticket ownership: a `Visitor` belongs to a site and has an optional name, phone and email, a `last_seen_at` and a `created_at`. Every ticket has a `channel` (`portal`, `chat` or `offline_form`, `portal` by default) and an optional `site`. A ticket belongs to exactly one owner, either a `customer` or a `visitor`, enforced by a database check constraint and by `Ticket.clean()`. Customers and visitors with tickets cannot be deleted, and neither can sites that have visitors or tickets
- Visitor identity: the first contact issues a signed, expiring visitor token that encodes the visitor and the site. A tampered or expired token is rejected, a returning visitor resolves to the same row, and the token is replaced by a fresh one every time the visitor starts or continues a conversation
- Messages as comments: a chat message is a `Comment` with a `kind` (`message` or `system`), an optional `visitor` and an optional `client_msg_id`. Every message has exactly one sender, an `author` or a `visitor`, enforced by a database check constraint and by `Comment.clean()`, and system messages have neither. Sending again with the same `client_msg_id` returns the stored comment instead of creating a second row. Comment responses carry a `sender_type` (`customer`, `agent`, `visitor` or `system`), and internal notes stay hidden from customers
- Public widget API under `/api/widget/`: the public config of a site, starting or resuming a conversation, reading and sending messages, uploading files and getting signed download URLs. Visitors authenticate with the `X-Visitor-Token` header and can only ever reach their own conversation. Every request must come from an origin listed in the site's `allowed_origins` (anything else gets 403), and every route is throttled per IP address and per visitor. Uploads go through the same content checks as every other upload
- Read state and unread counts: a `ConversationRead` row stores, for each participant (a user or a visitor) and ticket, the id of the last message they have read. Every ticket response carries an `unread_count` for the signed-in user: the messages from other people after that point, without internal notes for customers. Participants mark a conversation read at `POST /api/tickets/{id}/read/` (visitors at `POST /api/widget/conversations/{id}/read/`), and the marker only ever moves forward
- Missed-message recovery: a client that lost its connection catches up with `GET /api/tickets/{id}/messages/?after=<id>` (visitors use the widget route with the same parameter). Messages come oldest first, 100 at a time, with `has_more`, and the `message.created` WebSocket event carries the message id that serves as the cursor, so nothing is lost and the order is kept
- WebSocket support: the app runs on ASGI with Django Channels and a Redis channel layer. Clients connect to `/ws/` with a short-lived, single-use ticket obtained over HTTP (users at `POST /api/ws/ticket/`, widget visitors at `POST /api/widget/ws/ticket/`), so no long-lived token ever appears in a URL. Visitors are also checked against the site's allowed origins. A socket can only join the conversations its owner could open over HTTP, and every connection has a message size limit and a message rate limit
- Live events: ticket changes and new messages are pushed to the sockets that may see them, only after the database transaction commits, so a rolled-back change never reaches a socket
- Typing indicators: a participant who has joined a ticket can tell the others in it that they started or stopped typing. The signals are relayed over the channel layer only, never stored, and throttled per connection and ticket
- Agent presence: agents and admins keep a presence socket open at `/ws/presence/`. Presence lives in Redis with a time-to-live that a heartbeat refreshes, so a closed tab goes offline by itself. Each staff member is `available` or `away`, and `GET /api/agents/online/` lists who is online with their open chat count and capacity
- Chat routing: a new chat is assigned right away to the available agent with the fewest open chats (the one who was assigned a chat longest ago breaks ties), never above `max_concurrent_chats`. The assignment goes through the normal ticket serializer, so the audit event is written and the assignee rules apply, and concurrent new chats are serialized with row locks so one agent is not overloaded. With nobody available the chat stays unassigned in the queue
- Claiming: an agent or admin can take an unassigned ticket with `POST /api/tickets/{id}/claim/`, and two agents claiming at once cannot both win
- Offline fallback: when a new chat is started, a Celery task is scheduled with a `countdown`. If no agent is online it runs at once, otherwise after the site's `offline_timeout_minutes`. Unless an agent has replied by then, the conversation becomes an `offline_form` ticket, with an audit event, a system message and a push to the widget asking for optional contact details. The task is idempotent
- JWT authentication with short-lived access tokens, rotating refresh tokens, a blacklist and logout. Tokens are signed with their own `JWT_SIGNING_KEY`, so a leaked `SECRET_KEY` cannot be used to forge them
- Immediate token revocation: a password change or reset invalidates the user's access tokens at once instead of at the end of their 15-minute lifetime, and deactivation does the same
- Rate limiting: every route is throttled per IP address (anonymous) or per user (signed in), with stricter limits on login, registration, password change, user management, site management, signed downloads and WebSocket tickets. A throttled request gets `429` in the standard error format with a `Retry-After` header. Counters live in Redis, so they are shared between processes
- Production hardening: HTTPS redirect, HSTS with subdomains and preload, secure cookies, `nosniff` and a strict referrer policy, checked by `manage.py check --deploy`
- Structured logging: every log line is one JSON object with a timestamp, level, logger, message, `request_id` and `user_id`. A request ID middleware keeps a valid incoming `X-Request-ID` or generates one, stamps it on every log line of that request and returns it in the `X-Request-ID` response header (exposed to browsers through CORS), so a bug report that quotes the ID can be traced end to end. Each request writes one access line with the method, path, status, duration and client IP. Passwords, tokens, signed download URLs and query strings never reach the logs
- Prometheus metrics: `GET /metrics/` exposes request counts and latency per view, plus two custom gauges, the number of open WebSocket connections and the size of the unassigned queue. It needs a bearer token (`METRICS_TOKEN`) and is disabled when no token is set. A Prometheus container in the `monitoring` Compose profile scrapes it
- Role-scoped querysets: a customer only ever sees their own tickets
- Field-level permissions: customers can edit only the title and description of their own open tickets, and status, priority and assignee are staff-only
- Soft delete: only admins can delete a ticket, deletion hides it without removing its comments, attachments or audit rows, and admins can restore it at `/api/tickets/{id}/restore/`
- Ticket status state machine: illegal transitions return 400 and write nothing
- Assignee validation: a ticket can only be assigned to an active agent or admin
- Append-only audit trail of status, assignee and channel changes, enforced in the model and readable at `/api/tickets/{id}/events/`
- Comments with internal notes that customers never receive
- Attachments on tickets and on comments, with a 10 MB limit and a content-type allowlist. Customers cannot see or reach the attachments of internal comments, and only a comment's author can attach files to it
- File safety: the real content type of every upload is read from its magic bytes with a pure-Python library (`filetype`), so the Docker image needs no system packages. The detected type must be on the allowlist and must match the declared `content_type`, so a script renamed to `.png` or a PNG labelled as a PDF is rejected. DOCX and plain ZIP files, both ZIP containers, are told apart by reading the archive's file list, and archives are never extracted. Attachments are stored under random names with the extension taken from the verified type, and the original name is kept in `original_name` for display. Avatars go through the same check
- Pluggable file storage: local disk by default, or any S3-compatible bucket (MinIO for local testing) selected with `STORAGE_BACKEND`
- Protected downloads: `/media/` is never served. Attachments and avatars are reached only through `GET /api/attachments/{id}/download/` and `GET /api/avatars/{id}/download/`, which check access first and return a short-lived signed URL as `{url, expires_in}`. With local storage the URL points to an API route that verifies the signature and streams the file, with S3 it is a presigned URL, and the bucket is never public. Attachment responses carry a `download_url` pointing at that endpoint instead of a file URL
- Forced downloads: every file is served with `Content-Disposition: attachment` and its original name. Local downloads also carry `X-Content-Type-Options: nosniff`, and S3 presigned URLs override the response content type and disposition
- Avatar visibility: users can get their own avatar, staff can get any avatar, everyone signed in can get a staff member's avatar, and a customer's avatar is visible only to that customer and to staff
- Filtering by status, priority and assignee (including `assignee=me`) and cursor pagination
- One error format for every failure: `{"error": {"code", "message", "details"}}`
- Persian (`fa`) language and the Asia/Tehran time zone: timestamps are stored in UTC and returned with the Tehran offset, and custom error messages are marked for translation
- OpenAPI schema and Swagger UI
- Database-free `/health/` endpoint for uptime checks
- Automated tests with a 92% coverage threshold and GitHub Actions CI

## Project layout

| App | What it holds |
| --- | --- |
| `accounts` | The user model, registration, profile, password change, user management, avatars and the `UserEvent` audit log |
| `tickets` | Tickets, comments (which are also chat messages), attachments, read state, the `TicketEvent` audit log, assignment and claiming |
| `chat` | Sites, visitors, visitor tokens, the public widget API, conversations, chat routing and the offline fallback task |
| `realtime` | The WebSocket consumers, single-use socket tickets, event publishing, agent presence and the online agents endpoint |
| `core` | Shared infrastructure: the error envelope, logging, the request ID middleware, Prometheus metrics, upload checks, signed downloads, storage and the append-only and soft-delete base models |
| `config` | Settings (`base`, `dev`, `prod`, `test`), URLs, ASGI routing and Celery |

## API overview

All routes live under `/api/` unless noted. Routes marked "signed in" need a bearer access token.

| Route | Who | Purpose |
| --- | --- | --- |
| `POST /api/token/`, `POST /api/token/refresh/` | Anyone | Log in and refresh the access token |
| `POST /api/auth/register/` | Anyone | Register a customer |
| `POST /api/auth/logout/` | Signed in | Blacklist a refresh token |
| `GET, PATCH /api/auth/me/` | Signed in | Read and update the own profile |
| `POST /api/auth/password/change/` | Signed in | Change the own password and get a new token pair |
| `/api/users/`, `/api/users/{id}/` | Admins | Manage users (`GET`, `POST`, `PATCH`) |
| `GET /api/agents/` | Agents, admins | Active agents and admins for assignment dropdowns |
| `GET /api/agents/online/` | Agents, admins | Staff with a live presence entry |
| `/api/tickets/`, `/api/tickets/{id}/` | Signed in | List, create, read, update tickets. Only admins delete |
| `POST /api/tickets/{id}/restore/` | Admins | Restore a deleted ticket |
| `POST /api/tickets/{id}/claim/` | Agents, admins | Take an unassigned ticket |
| `POST /api/tickets/{id}/read/` | Signed in | Mark a conversation as read |
| `GET /api/tickets/{id}/messages/` | Signed in | Messages after a cursor |
| `GET /api/tickets/{id}/events/` | Signed in | Audit trail of the ticket |
| `GET, POST /api/tickets/{id}/comments/` | Signed in | Comments and messages |
| `GET, POST /api/tickets/{id}/attachments/` | Signed in | Attachments on the ticket |
| `GET, POST /api/tickets/{id}/comments/{comment_id}/attachments/` | Signed in | Attachments on a comment |
| `GET /api/attachments/{id}/download/` | Signed in | Signed download URL of an attachment |
| `GET /api/avatars/{id}/download/` | Signed in | Signed download URL of an avatar |
| `GET /api/downloads/{token}/` | Holder of a signed URL | Stream a file from local storage |
| `/api/sites/` | Admins | Manage chat sites |
| `/api/widget/...` | Visitors | The widget API (see Widget API) |
| `POST /api/ws/ticket/` | Signed in | Single-use WebSocket ticket |
| `GET /health/` | Anyone | Database-free health check (not under `/api/`) |
| `GET /metrics/` | Holder of `METRICS_TOKEN` | Prometheus metrics (not under `/api/`, not in the OpenAPI schema) |
| `GET /api/schema/`, `GET /api/docs/` | Anyone | OpenAPI schema and Swagger UI |

## Chat sites

Admins manage the sites that will host the chat widget at `/api/sites/`. Every request needs an admin token.

| Method | Route | Purpose |
| --- | --- | --- |
| `GET` | `/api/sites/` | List sites, cursor-paginated. Filters: `key` (exact) and `is_active` |
| `POST` | `/api/sites/` | Create a site. Only `name` is required |
| `GET` | `/api/sites/{id}/` | Read a site |
| `PATCH` | `/api/sites/{id}/` | Update a site |
| `POST` | `/api/sites/{id}/rotate-key/` | Replace the public key with a new random one |

- `key`: generated on creation and read-only. It is a public identifier that goes into the embed snippet, not a secret. Rotating it makes the old key stop resolving at once
- `allowed_origins`: up to 20 origins in the form `scheme://host[:port]` with `http` or `https` only. Paths, queries, fragments, credentials and wildcards are rejected. Values are lowercased, default ports (`:80` and `:443`) are dropped and duplicates are removed, so what is stored matches what a browser sends in the `Origin` header
- `primary_color`: a color in the form `#rrggbb`
- `position`: `bottom_right` or `bottom_left`
- `offline_timeout_minutes`: from 1 to 1440. It is how long a new chat may stay unanswered before it becomes an offline ticket (see Offline fallback)
- `greeting`, `require_name` and `require_contact` are plain widget settings
- Sites cannot be deleted. Set `is_active` to `false` instead

## Ticket owners and channels

| Field | Meaning |
| --- | --- |
| `channel` | Where the ticket came from: `portal`, `chat` or `offline_form`. Defaults to `portal` |
| `customer` | The registered user who owns the ticket. Empty for visitor tickets |
| `visitor` | The anonymous widget visitor who owns the ticket. Empty for portal tickets |
| `site` | The site that hosted the widget. Empty for portal tickets |

- Exactly one of `customer` and `visitor` is set on every ticket (`ticket_exactly_one_owner`). A ticket with both or neither is rejected by the database
- Visitor tickets have `customer: null` in ticket responses. Customers never see them, and staff see them in the same list as portal tickets
- `Visitor.phone` uses the same canonical Iranian mobile format as user phones
- A `chat` ticket becomes an `offline_form` ticket when nobody answers it (see Offline fallback). The change is written to the audit trail as a `channel` event

## Messages

`POST /api/tickets/{id}/comments/` accepts `body`, `is_internal` (staff only) and an optional `client_msg_id`.

| Field | Meaning |
| --- | --- |
| `kind` | `message` for a person's message, `system` for a notice written by the system. Read-only |
| `author` | The registered user who wrote it. Empty for visitor and system messages |
| `visitor` | The widget visitor who wrote it. Empty for staff, customer and system messages |
| `sender_type` | `customer`, `agent` (agents and admins), `visitor` or `system` |
| `client_msg_id` | Optional ID of up to 64 characters chosen by the client, unique per ticket |

- A retry with the same `client_msg_id` from the same sender returns the stored comment with `200` instead of `201`, so a message that was sent twice is stored once. The same ID from a different sender in the same ticket is rejected with `400`
- Visitor messages are always public

## Read state

`POST /api/tickets/{id}/read/` marks a conversation as read for the signed-in user. The body is optional: `last_read_comment_id` is the id of the last message the client has shown. Without it, everything the user can see up to now is marked as read. The response is `{last_read_comment_id, unread_count}`.

- A message counts as unread for a participant when it comes after their marker, they are allowed to see it and someone else wrote it. Their own messages never count, internal notes never count for customers or visitors, and system messages count for everyone
- The marker only moves forward, so a late or repeated request can never make messages unread again
- `last_read_comment_id` must be a message the participant can see. Anything else, including the id of an internal note sent by a customer, is `400`
- Read state is kept per person: two agents on the same ticket have separate markers and separate counts, and internal notes written by one agent are unread for the other
- Before a participant has marked a conversation read, every message from other people counts as unread
- `unread_count` is on every ticket response (list, detail and updates), for customers and staff alike

## Missed-message recovery

A WebSocket event is a notification. It names the ticket and the message id but does not carry the message text, so clients read messages over HTTP and use the id of the last message they have processed as a cursor. The same cursor repairs any gap, whether the socket dropped, the tab slept or an event was lost.

| Method | Route | Who | Purpose |
| --- | --- | --- | --- |
| `GET` | `/api/tickets/{id}/messages/?after=<id>` | Customers (own tickets), agents, admins | Messages with an id greater than `after`, oldest first |
| `GET` | `/api/widget/conversations/{id}/messages/?after=<id>` | Visitors | The same for the visitor's own conversation |

- Response: `{results, has_more, unread_count}`, and the widget route adds `agents_available`. `results` holds at most 100 messages, so call again with the id of the last one until `has_more` is `false`
- `after` is a message id. It defaults to `0`, which returns the conversation from its first message. It must be an integer from 0 to 2^63-1, otherwise the answer is `400`
- Ids only grow, so ordering by id is ordering by arrival. Message ids are shared by all tickets, so they are not consecutive inside one ticket, and a jump in the numbers does not mean a message is missing
- Visibility is the same as everywhere else: customers and visitors never receive internal notes, agents and admins receive everything, and the ticket of another customer or visitor, or a deleted ticket, is `404`
- Each message has the same shape as in the matching comment or widget message responses, including `client_msg_id`, so a recovered message can be matched with one the client sent itself

Contract for clients:

1. Keep `last_id`, the highest message id processed for each conversation (`0` when there is none)
2. After every connect or reconnect, open the socket, send `join`, wait for `joined`, and then call the messages route with `after=last_id` until `has_more` is `false`. Joining first means a message sent between the two steps still produces an event
3. When a `message.created` event arrives with a `data.message_id` greater than `last_id`, call the messages route with `after=last_id`. That returns the new message and any earlier one the client missed
4. Merge by message id (and by `client_msg_id` for messages the client sent optimistically) and only ever move `last_id` up, so receiving the same message twice changes nothing

## Widget API

The embeddable widget talks to these routes. They need no staff account.

| Method | Route | Auth | Purpose |
| --- | --- | --- | --- |
| `GET` | `/api/widget/config/?key=<site key>` | none | Public settings of a site plus `agents_available` |
| `POST` | `/api/widget/conversations/` | optional token | Start a conversation, or send into the current one. Returns the visitor token |
| `GET` | `/api/widget/conversations/{id}/messages/?after=<id>` | token | Public messages with an id greater than `after`, oldest first |
| `POST` | `/api/widget/conversations/{id}/messages/` | token | Send a message |
| `POST` | `/api/widget/conversations/{id}/read/` | token | Mark messages as read. Optional `last_read_comment_id`. Returns `{last_read_comment_id, unread_count}` |
| `POST` | `/api/widget/conversations/{id}/attachments/` | token | Send a file as a message (multipart: `file`, optional `body` and `client_msg_id`) |
| `GET` | `/api/widget/attachments/{id}/download/` | token | Short-lived signed download URL as `{url, expires_in}` |
| `POST` | `/api/widget/ws/ticket/` | token | Exchange the visitor token for a single-use WebSocket ticket as `{ticket, expires_in}` |

- Authentication: send the token from the first `POST /api/widget/conversations/` in an `X-Visitor-Token` header. A missing, tampered or expired token, and the token of a deactivated site, get `401`. A token is valid for `VISITOR_TOKEN_LIFETIME_DAYS` days
- Origin: the `Origin` header must be one of the site's `allowed_origins`. A missing header, an unlisted origin or a site with no origins gets `403`, so add the host page's origin to the site before embedding the widget. The routes send CORS headers to any origin so the browser can read that `403`, and the origin check is what enforces access
- Starting a conversation: `body` (up to 4000 characters) is the first message and is always required. Without a token, `site_key` is required, a visitor is created and `name`, `phone` and `email` are stored (the site's `require_name` and `require_contact` are enforced). With a token, the token is replaced by a fresh one, and the message goes into the visitor's current conversation (one that is not resolved or closed) or opens a new one. The response is `201` when a conversation was created and `200` otherwise, and carries `token`, `conversation`, `message` and `agents_available`
- A conversation is a ticket with `channel` `chat`. Its title is the start of the first message and its description is empty, because the messages are the content. A new conversation is routed to an available agent when it is created (see Chat routing), and an offline fallback is scheduled for it (see Offline fallback)
- Messages: responses never contain internal notes. `GET` returns at most 100 messages as `{results, has_more, agents_available, unread_count}`, so a client that reconnects calls it with the last id it saw until `has_more` is `false` (see Missed-message recovery). `unread_count` is the number of staff messages the visitor has not marked as read
- Closed conversations: sending a message or a file into a resolved or closed conversation gets `409` with the code `conversation_closed`. Start a new conversation with `POST /api/widget/conversations/` instead
- Attachments: the file becomes a message of its own, so it appears in order in the thread. It must pass the same size, type and magic-byte checks as every other upload
- Downloads: a visitor can only get a URL for a file on a public message of their own conversation. Everything else is `404`
- Another visitor's conversation, message or file is always `404`
- `agents_available` is `true` while at least one active agent or admin has a live presence entry with the status `available`

## Forgotten passwords

There is no password reset by email. Outbound email is out of scope for this project, so a user who forgets their password asks an admin, who sets a new one with `PATCH /api/users/{id}/` and a `password` field. That also signs the user out of every session. Signed-in users change their own password with `POST /api/auth/password/change/`.

## WebSockets

The app is an ASGI application (`config/asgi.py`). HTTP goes to Django and WebSocket connections go to `/ws/` and `/ws/presence/` (`config/routing.py`). In development `runserver` is served by Daphne, so it handles both. The channel layer is `channels_redis` on `REDIS_URL`, with the key prefix `ticketing`. Tests use the in-memory channel layer.

### Connecting

1. Get a ticket over HTTP. Signed-in users call `POST /api/ws/ticket/` with their access token. Widget visitors call `POST /api/widget/ws/ticket/` with `X-Visitor-Token` from an allowed origin. The response is `{ticket, expires_in}`.
2. Open `ws://localhost:8000/ws/?ticket=<ticket>` before it expires.

A ticket works once and expires after `WS_TICKET_TTL_SECONDS`. A missing, unknown, reused or expired ticket, a deactivated user, a deactivated site and a visitor whose `Origin` header is not in the site's `allowed_origins` are all refused at the handshake with HTTP 403.

```js
const { ticket } = await fetch("http://localhost:8000/api/ws/ticket/", {
  method: "POST",
  headers: { Authorization: `Bearer ${accessToken}` },
}).then((response) => response.json());

const ws = new WebSocket(`ws://localhost:8000/ws/?ticket=${ticket}`);
ws.onmessage = (event) => console.log(event.data);
ws.onopen = () => ws.send(JSON.stringify({ type: "join", ticket_id: 1 }));
```

### Messages

Every message is a JSON object with a `type`.

| Direction | Message | Meaning |
| --- | --- | --- |
| Client to server | `{"type": "ping"}` | Heartbeat. The server answers `{"type": "pong"}` |
| Client to server | `{"type": "join", "ticket_id": 1}` | Subscribe to a ticket. The server answers `{"type": "joined", "ticket_id": 1}` |
| Client to server | `{"type": "leave", "ticket_id": 1}` | Unsubscribe. The server answers `{"type": "left", "ticket_id": 1}` |
| Client to server | `{"type": "typing", "ticket_id": 1, "is_typing": true}` | Tell the others in the ticket that you started (`true`) or stopped (`false`) typing. Never answered |
| Server to client | `{"type": "typing", "ticket_id": 1, "is_typing": true, "sender_type": "agent", "sender_name": "..."}` | Someone else in a joined ticket started or stopped typing. `sender_type` is `customer`, `agent` or `visitor` |
| Server to client | `{"type": "error", "code": "...", "ticket_id": 1}` | A message was rejected. `ticket_id` is present when it applies |

Error codes: `invalid_json`, `invalid_message`, `unknown_type`, `invalid_ticket_id`, `not_found`, `not_joined` and `too_many_tickets`.

- A visitor can join only their own conversations, a customer only their own tickets, and an agent or admin any ticket that is not deleted. Anything else answers `not_found`, the same as the HTTP API, so a client cannot tell a missing ticket from someone else's
- A connection can be joined to at most 50 tickets at once

### Events

Changes are pushed to sockets as events with the shape `{"type", "id", "ticket_id", "data"}`. They are sent only after the database transaction commits, so a rolled-back change never reaches a socket.

| Type | `id` | `data` | Who receives it |
| --- | --- | --- | --- |
| `message.created` | The message id | `message_id`, `kind`, `sender_type`, `is_internal`, `client_msg_id` | Everyone in the ticket. Internal notes reach staff only |
| `ticket.event` | The audit event id | `field_changed`, `old_value`, `new_value` | Everyone in the ticket. Assignee changes reach staff only |
| `conversation.offline` | The audit event id of the channel change | `has_contact` | Everyone in the ticket and the agents queue |

- Agents and admins receive the events of every ticket through the agents queue. Customers and visitors receive the events of the tickets they have joined
- `data.message_id` of a `message.created` event is the id to use as the `after` cursor. The `id` of a `ticket.event` or a `conversation.offline` event is an audit row id from another sequence and must never be used as a cursor
- `conversation.offline` tells the widget that the chat became an offline ticket. `has_contact` is `true` when the visitor already left a phone number or an email, so the widget can skip asking for them
- A conversion also produces a `ticket.event` with `field_changed` set to `channel` and a `message.created` event for the system message
- Events do not carry the message text. Clients fetch messages as described in Missed-message recovery

### Typing indicators

Typing signals are ephemeral. They are not stored, they are not part of the audit trail and they are not sent to the agents queue, so only sockets that have joined the ticket receive them.

- A client must have joined the ticket first, otherwise the answer is `not_joined`. `is_typing` must be a boolean, otherwise the answer is `invalid_message`
- The sender never receives its own signal, and neither does another socket of the same user or visitor
- The server throttles per connection and ticket: a `true` that follows another `true` within `WS_TYPING_THROTTLE_SECONDS` is dropped silently, and a `false` is relayed only after a `true`
- When a socket leaves a ticket or disconnects while typing, the others receive `is_typing: false`
- A lost `false` must not leave the indicator on forever, so clients repeat `true` about every 3 seconds while the user types and hide the indicator 5 seconds after the last `true`
- Clients should debounce keystrokes before sending, because every message counts against the per-connection rate limit
- Clients should not send typing signals while the user writes an internal note

### Limits

| Limit | Result |
| --- | --- |
| Message larger than `WS_MAX_MESSAGE_BYTES` | Connection closed with code `1009` |
| More than `WS_RATE_LIMIT_MESSAGES` messages in `WS_RATE_LIMIT_WINDOW_SECONDS` | Connection closed with code `4429` |
| Binary frame | Connection closed with code `1003` |
| Typing update within `WS_TYPING_THROTTLE_SECONDS` of the previous one for the same ticket | Dropped silently, the connection stays open |

The same size, rate and binary limits apply to the presence socket.

Check that the Redis channel layer works:

```bash
docker compose exec web python manage.py shell -c "from asgiref.sync import async_to_sync; from channels.layers import get_channel_layer; layer = get_channel_layer(); async_to_sync(layer.send)('probe', {'type': 'ping'}); print(async_to_sync(layer.receive)('probe'))"
```

The production image runs Daphne (ASGI), so the same process serves both HTTP and WebSocket and the widget and presence sockets work in production. See [Self-hosting](docs/self-hosting.md).

## Agent presence

Presence tells the system which staff members are online and whether they accept new chats. It is kept in Redis (Django's cache) with a time-to-live, so a closed tab or a crashed browser drops out by itself.

### Presence socket

Agents and admins connect to `ws://localhost:8000/ws/presence/?ticket=<ticket>` with a ticket from `POST /api/ws/ticket/`. An anonymous socket and a visitor are closed with `4401`, and a customer with `4403`.

| Direction | Message | Meaning |
| --- | --- | --- |
| Server to client | `{"type": "presence", "status": "available"}` | Sent on connect and after every status change |
| Client to server | `{"type": "ping"}` | Heartbeat. Refreshes the time-to-live. The server answers `{"type": "pong", "status": "available"}` |
| Client to server | `{"type": "set_status", "status": "away"}` | Set the status to `available` or `away`. The server answers with a `presence` message |
| Server to client | `{"type": "error", "code": "..."}` | A message was rejected. Codes: `invalid_json`, `invalid_message`, `unknown_type` and `invalid_status` |

- A staff member is online while their presence entry exists. It is created when they connect, refreshed by every `ping` and removed by Redis when it has not been refreshed for `PRESENCE_TTL_SECONDS`. Clients should ping well inside that time, for example every 10 seconds with the default of 30
- Closing the socket does not delete the entry, so the agent goes offline within the time-to-live
- Presence is kept per user, not per socket. Two tabs of the same agent share one status, and closing one tab does not take the agent offline while the other keeps sending heartbeats
- A new connection keeps the stored status when the entry is still alive. Without an entry the status starts as `available`
- Only `available` agents receive new chats. `away` agents stay online and keep the chats they have

### Online agents

`GET /api/agents/online/` is readable by agents and admins. It lists every active staff member with a live presence entry, ordered by name.

```json
[
  {
    "id": 2,
    "name": "Sara Ahmadi",
    "role": "agent",
    "status": "available",
    "max_concurrent_chats": 5,
    "open_chats": 1,
    "accepting_chats": true
  }
]
```

- `open_chats` counts the chat tickets assigned to the agent that are not deleted, resolved or closed. A chat that was converted to an offline ticket no longer counts
- `accepting_chats` is `true` when the status is `available` and `open_chats` is below `max_concurrent_chats`
- Staff set their own `max_concurrent_chats` (1 to 50, default 5) at `PATCH /api/auth/me/`

## Chat routing

When a visitor starts a new conversation, the backend tries to assign it to an agent in the same transaction that creates it.

1. Take the staff members who are active and whose presence status is `available`
2. Lock their user rows (`select_for_update`, in id order), so two concurrent new chats cannot read the same load and pick the same agent
3. Drop agents whose open chats have reached `max_concurrent_chats`
4. Pick the agent with the fewest open chats. On a tie, pick the one who was assigned a chat longest ago (agents never assigned one go first), and then the lowest id
5. Assign through the normal ticket serializer, so the assignee rules apply (an active agent or admin) and an `assignee` audit event is written with no actor

- With no available agent the conversation stays unassigned in the queue. Later messages in the same conversation do not trigger routing again. The offline fallback decides what happens to a chat that stays unanswered (see Offline fallback)
- `last_chat_assigned_at` on the user is updated whenever routing or a claim assigns a chat, and it drives the round-robin tie-break
- The assignee audit event reaches staff sockets only, never customers or visitors

### Claiming

`POST /api/tickets/{id}/claim/` lets an agent or admin take a ticket. Customers get `403`.

- An unassigned ticket is assigned to the caller and an `assignee` audit event is written
- A ticket that is already assigned to the caller is returned unchanged
- A ticket assigned to someone else answers `409` with the code `ticket_already_assigned`
- The ticket row is locked while it is checked, so two agents claiming at once cannot both succeed
- A deleted ticket is `404`. A manual claim does not check the caller's `max_concurrent_chats`

## Offline fallback

A chat that nobody answers becomes an offline ticket, so the visitor can leave contact details and be answered later. The Celery worker must be running (`docker compose up` starts it).

When a visitor starts a new conversation, `chat.convert_to_offline` is scheduled with a `countdown`, after the transaction commits:

- Nobody online (no active agent or admin with the presence status `available`): countdown `0`
- Someone online: the site's `offline_timeout_minutes`, counted from the start of the conversation

The task changes nothing, and returns `false`, when:

- the ticket does not exist or is deleted
- the ticket is no longer a `chat` ticket, which makes every repeated run a no-op
- the ticket is resolved or closed
- an agent or admin has already written a public message in it (internal notes do not count)

Otherwise it does this in one transaction, with the ticket row locked:

1. Sets `channel` to `offline_form`
2. Writes a `channel` audit event (`chat` to `offline_form`, no actor)
3. Adds a `system` message telling the visitor to leave contact details
4. Pushes a `conversation.offline` event with `has_contact`, which is `true` when the visitor already gave a phone or an email

- The assignee is kept, and the conversation continues in the same ticket. A converted ticket no longer counts towards an agent's open chats
- The `channel` audit event reaches everyone in the ticket, like any non-assignee event
- A broker outage when scheduling is logged and does not fail the visitor's request
- The widget has no route yet for sending contact details after a conversation has started. The event only tells it to ask

## Tech stack

Python 3.12, Django, Django REST Framework, SimpleJWT, django-filter, drf-spectacular, Pillow, filetype, django-storages with boto3, Channels with Daphne, Celery, Redis, PostgreSQL, MinIO (local S3), prometheus_client and Prometheus, Docker, pytest. Redis is Django's cache, which holds the throttle counters, the WebSocket tickets and the presence entries, the Channels layer that fans WebSocket events out between processes, and the Celery broker. Celery runs the offline fallback task.

## Run locally

You need Docker with Compose.

```bash
cp .env.example .env
docker compose up --build
```

In a second terminal, one command migrates the database, seeds the demo data and prints the demo logins:

```bash
make demo
```

Without `make`, run the same two commands directly:

```bash
docker compose exec -T web python manage.py migrate
docker compose exec -T web python manage.py seed_demo
```

- API: http://localhost:8000
- Swagger UI: http://localhost:8000/api/docs/
- Admin: http://localhost:8000/admin/

`seed_demo` creates a demo customer (`demo_customer`), a demo agent (`demo_agent`), a chat site, tickets and conversations, and prints their logins. Both accounts use the password `demo-ticketing-2026`. It is idempotent, so it is safe to run more than once. Before recording a demo, `make reset-demo` (or `docker compose exec -T web python manage.py reset_demo`) removes everything the demo accounts and the demo site produced and seeds a clean state again.

For an admin account, run `docker compose exec web python manage.py createsuperuser` and change the role in the admin site to act as an agent or admin in the API.

The `celery` service starts with the stack and runs the offline fallback task. To watch it work, start a chat with no agent online and follow the worker log:

```bash
docker compose logs -f celery
```

Run the tests (they always use local storage, an in-memory cache, channel layer and Celery broker, and relaxed throttle limits, whatever `.env` says):

```bash
docker compose exec -e STORAGE_BACKEND=local web pytest --cov
```

### Storing files in MinIO

Files go to local disk by default. To test the S3 path without a provider account, set `STORAGE_BACKEND=s3` in `.env` and start the stack with the `s3` profile:

```bash
docker compose --profile s3 up --build
```

This starts MinIO and creates a private bucket named after `S3_BUCKET_NAME`. The MinIO console is at http://localhost:9001 and signed download URLs are generated against `S3_PUBLIC_ENDPOINT_URL` (`http://localhost:9000`), so your browser can reach them. The containers talk to MinIO at `http://minio:9000`.

## Logging

Every log line, from the web process and from the Celery worker, is a single JSON object written to stdout:

```json
{"timestamp":"2026-10-12T09:41:07.532+00:00","level":"INFO","logger":"core.access","message":"request completed","request_id":"3f2b8c1e9a4d4f6f8e1b7c2d5a9e0f13","user_id":7,"method":"GET","path":"/api/tickets/","status":200,"duration_ms":18.4,"client_ip":"172.18.0.1"}
```

- `request_id`: taken from an incoming `X-Request-ID` header when it is 8 to 64 characters of letters, digits, `.`, `_` or `-`, otherwise generated. Every response carries it in `X-Request-ID`, including errors, throttled requests and CORS preflights, and the header is exposed to browsers through CORS so the frontend can show it in an error message.
- `user_id`: the id of the user authenticated by the JWT, `null` for anonymous requests and for the login, refresh and registration routes.
- Every request writes one `core.access` line. `/health/` and `/metrics/` are written at `DEBUG` level only, so uptime checks and metric scrapes do not flood the log, and responses with a 5xx status are written at `ERROR`. `duration_ms` is the time taken to produce the response, so for streamed downloads it does not include the transfer.
- Unhandled exceptions are logged by `django.request` at `ERROR` with the traceback in `exception` and the same `request_id`. Client errors (4xx) are covered by the access line only.

To follow one request, quote its ID from the `X-Request-ID` header:

```bash
docker compose logs web --no-log-prefix | grep 3f2b8c1e9a4d4f6f8e1b7c2d5a9e0f13
docker compose logs web --no-log-prefix | jq -R -c 'fromjson? | select(.request_id == "3f2b8c1e9a4d4f6f8e1b7c2d5a9e0f13")'
```

Secrets are kept out of the logs in two ways. The code never logs request headers, request bodies or query strings, and the access line records the path only. On top of that, the formatter scrubs every message and traceback, replacing the token in `/api/downloads/<token>/` paths, bearer tokens, JWTs and secret-looking query parameters, and it masks extra fields whose names look sensitive (`password`, `token`, `authorization`, `cookie`, `signature` and similar).

`LOG_LEVEL` sets the verbosity (`INFO` by default).

## Rate limits

Throttling needs Redis, because the counters are kept in Django's cache. A throttled request returns `429` with the usual error envelope (`error.code` is `throttled`) and a `Retry-After` header.

| Scope | Applies to | Counted per | Limit |
| --- | --- | --- | --- |
| `anon` | Every route, signed out | IP address | 60/min |
| `user` | Every route, signed in | User | 300/min |
| `login` | `POST /api/token/` | IP address | 10/min |
| `register` | `POST /api/auth/register/` | IP address | 10/hour |
| `password_change` | `POST /api/auth/password/change/` | User | 5/hour |
| `user_management` | `/api/users/` | User | 60/min |
| `site_management` | `/api/sites/` | User | 60/min |
| `download` | `/api/downloads/{token}/` | IP address | 300/min |
| `ws_ticket` | `POST /api/ws/ticket/` | User | 30/min |
| `widget_ip` | Every `/api/widget/` route | IP address | 120/min |
| `widget_visitor` | Widget routes called with a visitor token | Visitor | 90/min |
| `widget_start` | `POST /api/widget/conversations/` | IP address | 20/hour |
| `widget_upload` | `POST /api/widget/conversations/{id}/attachments/` | Visitor | 30/hour |

The limits live in `REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]` in `config/settings/base.py`. Behind a reverse proxy, set `NUM_PROXIES` to the number of proxies in front of the app, so the real client address is read from `X-Forwarded-For`. With the default `0` the header is ignored, which stops clients from spoofing it to dodge the limits. To reset the counters while testing by hand, run `docker compose exec redis redis-cli FLUSHDB`.

WebSocket connections have their own limits, described under Limits in the WebSockets section.

## Metrics

`GET /metrics/` returns metrics in the Prometheus text format. It is a plain Django view, so it has no throttle, no JSON error envelope and no entry in the OpenAPI schema.

- Authentication: send `Authorization: Bearer <METRICS_TOKEN>`. A missing or wrong token gets `401`. When `METRICS_TOKEN` is empty the route answers `404`, so metrics are off unless you set a token
- `ticketing_http_requests_total{method,view,status}` counts handled requests and `ticketing_http_request_duration_seconds{method,view}` is a latency histogram. `view` is the URL name (for example `ticket-detail`), never the raw path, so ids don't create new series. Requests that match no route use `unmatched`, and unusual HTTP methods are grouped as `OTHER`. `/metrics/` itself is not counted, and the duration is the time taken to produce the response, so for streamed downloads it does not include the transfer
- `ticketing_websocket_connections{endpoint,client}` is the number of open WebSocket connections. `endpoint` is `tickets` or `presence` and `client` is `agent`, `customer` or `visitor`
- `ticketing_queue_size` is the number of unassigned tickets that are not resolved or closed. It is computed from the database on every scrape and uses the same definition as `queue_size` in `GET /api/stats/`. If the database cannot be read, the scrape still succeeds and this one metric is left out
- The standard Python and process metrics of `prometheus_client` (`python_gc_*`, `process_*`) are included as well
- The route is meant for an internal network. Do not publish `/metrics/` through the reverse proxy. It is exempt from the HTTPS redirect so an internal scraper can use plain HTTP
- With several server processes, set `PROMETHEUS_MULTIPROC_DIR` to an empty directory before the processes start. The connection gauge then adds up over live processes. The production image does not set this yet. The Celery worker does not serve metrics

Look at it by hand:

```bash
curl -H "Authorization: Bearer dev-metrics-token" http://localhost:8000/metrics/
```

Run a local Prometheus that scrapes it every 15 seconds:

```bash
docker compose --profile monitoring up -d prometheus
```

Open http://localhost:9090/targets: the `ticketing` target should be `UP`. The token comes from `METRICS_TOKEN` in `.env` and `web` must be in `ALLOWED_HOSTS`, because Prometheus calls the app as `http://web:8000`. The scrape settings are in `monitoring/prometheus.yml`.

## Checking the production settings

`manage.py check --deploy` must report no issues with the production settings. The command below runs it inside the dev container with throwaway keys:

```bash
docker compose exec \
  -e DJANGO_SETTINGS_MODULE=config.settings.prod \
  -e SECRET_KEY=local-deploy-check-secret-key-0123456789-abcdefghijklmnopqrstuvwxyz \
  -e JWT_SIGNING_KEY=local-deploy-check-jwt-key-9876543210-zyxwvutsrqponmlkjihgfedcba \
  -e ALLOWED_HOSTS=localhost \
  web python manage.py check --deploy --fail-level WARNING
```

CI runs the same check on every push.

## Security checks

The `security` job runs two checks on every push and pull request. Both fail the job on findings, so a security regression blocks the merge.

- `bandit -r . -c pyproject.toml --severity-level medium --confidence-level medium` scans the source for common security mistakes (unsafe calls, hardcoded passwords, weak crypto and similar). The threshold is **medium severity and medium confidence**: only findings at that level or above are reported and fail the job, and the configuration lives in `[tool.bandit]` in `pyproject.toml` (`B101`, the assert warning, is skipped there because asserts are used in tests). Low-severity and low-confidence noise is deliberately not enforced.
- `pip-audit -r requirements.txt --no-deps --disable-pip` audits the pinned runtime dependencies for known CVEs, and a second invocation audits `requirements-dev.txt`. `--no-deps` keeps the audit focused on what the project pins, and `--disable-pip` resolves from the requirements files without touching the environment. Any known vulnerability fails the job.

Run the same commands locally after `pip install -r requirements-security.txt`:

```bash
bandit -r . -c pyproject.toml --severity-level medium --confidence-level medium
pip-audit -r requirements.txt --no-deps --disable-pip
pip-audit -r requirements-dev.txt --no-deps --disable-pip
```

## Load test results

Load-test tooling and measured runs live in [`loadtest/`](loadtest/README.md). Results are committed under [`loadtest/results/`](loadtest/results/); each file records the machine, the parameters and the observed degradation point. The first run, at 10, 50, 100 and 200 concurrent visitors against the local Docker stack, is in [`loadtest/results/2026-10-16-local.md`](loadtest/results/2026-10-16-local.md).

## Configuration

Settings are read from environment variables. Copy `.env.example` to `.env` for local development and `.env.prod.example` to `.env.prod` for the production image.

| Variable | Required | Default | Description |
| --- | --- | --- | --- |
| `SECRET_KEY` | Yes | none | Django secret key |
| `JWT_SIGNING_KEY` | Production | `SECRET_KEY` | Key that signs JWTs and visitor tokens. Production refuses to start without one that differs from `SECRET_KEY` |
| `DEBUG` | No | `False` | Debug mode. Development settings force it on |
| `ALLOWED_HOSTS` | No | empty | Comma-separated host names. Include `web` when Prometheus scrapes the app |
| `DATABASE_URL` | No | SQLite file | Database connection URL |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | With prod | `ticketing` | Credentials the production Compose database container creates. `DATABASE_URL` must match them |
| `DJANGO_SETTINGS_MODULE` | No | `config.settings.dev` | `config.settings.prod` in the production image |
| `REDIS_URL` | No | `redis://localhost:6379/0` | Celery broker and result backend, Django's cache (throttle counters, WebSocket tickets, presence) and the Channels layer |
| `NUM_PROXIES` | No | `0` | Number of reverse proxies in front of the app, used to read the client IP for throttling and logging |
| `LOG_LEVEL` | No | `INFO` | Verbosity of the JSON logs (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `METRICS_TOKEN` | No | empty | Bearer token for `GET /metrics/`. Empty disables the endpoint |
| `PROMETHEUS_MULTIPROC_DIR` | No | unset | Directory for metric files when several server processes run. Must exist and be empty at start |
| `CORS_ALLOWED_ORIGINS` | No | empty | Comma-separated origins allowed to call the API. Widget routes accept any origin and check the site's `allowed_origins` instead |
| `CSRF_TRUSTED_ORIGINS` | No | empty | Production only. Comma-separated trusted origins |
| `SECURE_SSL_REDIRECT` | No | `true` | Production only. Redirect HTTP to HTTPS (`/health/` and `/metrics/` are exempt). Set `false` when you reach the container over plain HTTP without a proxy |
| `SECURE_HSTS_SECONDS` | No | `31536000` | Production only. Lifetime of the HSTS header. Once a browser has seen it over HTTPS it insists on HTTPS for that host for this long |
| `PORT` | No | `8000` | Port Daphne listens on |
| `WEB_PORT` | No | `8000` | Host port the production Compose file publishes. Set `127.0.0.1:8000` to expose the app to a local reverse proxy only |
| `STORAGE_BACKEND` | No | `local` | `local` for disk or `s3` for an S3-compatible bucket |
| `DOWNLOAD_URL_TTL_SECONDS` | No | `300` | Lifetime of signed download URLs |
| `VISITOR_TOKEN_LIFETIME_DAYS` | No | `30` | Lifetime of a widget visitor token |
| `WS_TICKET_TTL_SECONDS` | No | `30` | Lifetime of a single-use WebSocket ticket |
| `WS_MAX_MESSAGE_BYTES` | No | `4096` | Largest message a client may send over a WebSocket. A bigger one closes the connection |
| `WS_RATE_LIMIT_MESSAGES` | No | `30` | Messages a single connection may send per window |
| `WS_RATE_LIMIT_WINDOW_SECONDS` | No | `10` | Length of the per-connection rate-limit window |
| `WS_TYPING_THROTTLE_SECONDS` | No | `2` | Minimum time between two relayed typing signals of the same connection and ticket |
| `PRESENCE_TTL_SECONDS` | No | `30` | How long a presence entry lives without a heartbeat before the agent counts as offline |
| `S3_BUCKET_NAME` | With `s3` | none | Bucket that holds attachments and avatars |
| `S3_ACCESS_KEY` | With `s3` | none | Access key for the bucket |
| `S3_SECRET_KEY` | With `s3` | none | Secret key for the bucket |
| `S3_ENDPOINT_URL` | No | AWS | S3 endpoint the server uses, for example `http://minio:9000` |
| `S3_PUBLIC_ENDPOINT_URL` | No | `S3_ENDPOINT_URL` | Endpoint embedded in signed URLs when clients reach the bucket on another address |
| `S3_REGION_NAME` | No | `us-east-1` | Bucket region |

## Production image and self-hosting

Every push and pull request runs linting, the test suite and `check --deploy` on GitHub Actions, and every merge to `main` also builds both images as a check. The project is run locally with Docker Compose and is not deployed anywhere.

`Dockerfile.prod` is a multi-stage build: it installs the runtime dependencies into a virtualenv, runs `collectstatic` at build time and drops to a non-root user. It runs Daphne, the ASGI server, so one process serves both HTTP and WebSocket. Daphne's access log is switched off because the app writes its own JSON access line (see Logging). The base image and the pip index can be pointed at mirrors that work from inside Iran with the optional `PYTHON_IMAGE` and `PIP_INDEX_URL` build arguments, which default to upstream.

`docker-compose.prod.yml` runs the whole stack: `web` (Daphne), `worker` and `beat` (Celery), a one-shot `migrate` service that runs before the app services start, PostgreSQL and Redis. Migrations are a separate service, not part of the entrypoint. `.env.prod.example` lists everything the stack needs.

[`docs/self-hosting.md`](docs/self-hosting.md) walks through running that Compose file on any machine or VPS: generating secrets, putting Caddy or nginx with HTTPS and `wss://` in front, and setting hosts, CORS, CSRF and widget origins. The frontend is a separate application; this repository is the API only.

## License

MIT. See [LICENSE](LICENSE).
