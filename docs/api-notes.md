# API notes

[`schema.yml`](../schema.yml) is the source of truth for every route, request
and response body, operation id and permission. This page explains the
conventions and the behaviour that is not obvious from the schema. Swagger UI is
at `/api/docs/` and the JSON schema at `/api/schema/`.

## Conventions

- All routes live under `/api/` unless noted. `/health/`, `/ready/` and
  `/metrics/` are plain Django views outside the schema.
- Staff and customers authenticate with `Authorization: Bearer <access token>`.
  Tokens are obtained from `POST /api/token/` and refreshed with
  `POST /api/token/refresh/`.
- Widget visitors authenticate with `X-Visitor-Token`. Widget routes also check
  the request `Origin` against the site's `allowed_origins`.
- Every failed request uses the same envelope:
  `{"error": {"code": "...", "message": "...", "details": ...}}`. Clients should
  branch on `code`, not on `message`.
- `message` is not localized by this project. The project has no translation
  catalog and does not read `Accept-Language`. Messages written in the project
  are English. Field messages from Django and DRF, such as "This field is
  required.", come from Django's own catalog in the default language (`fa`). The
  text may change between releases, so clients should branch on `code`.
- `details` maps each field to a list of messages, even when there is one.
- List endpoints use cursor pagination where the schema shows a `cursor`
  parameter. The ticket list returns `{next, previous, results}` with ticket
  results, while messages use an id-based `after` cursor.
- Tickets are visible only to their owner (customer or visitor) and to staff.
  Customers and visitors never see internal notes.

## Routes

### Authentication and account

| Method | Route | Who | Purpose |
| --- | --- | --- | --- |
| `POST` | `/api/token/` | Anyone | Log in |
| `POST` | `/api/token/refresh/` | Anyone | Refresh an access token |
| `POST` | `/api/auth/register/` | Anyone | Register a customer |
| `POST` | `/api/auth/logout/` | Signed in | Blacklist a refresh token and close the user's open WebSockets |
| `GET`, `PATCH` | `/api/auth/me/` | Signed in | Read or update the own profile |
| `POST` | `/api/auth/password/change/` | Signed in | Change the own password |

Registration always creates a customer. `PATCH /api/auth/me/` accepts first and
last name, phone and avatar. Agents and admins may also set
`max_concurrent_chats` (1 to 50, default 5). The profile response contains
`avatar_download_url`, not the stored file name.

A password change needs the current password, revokes every refresh token of the
user and returns a fresh token pair. There is no email password reset: an admin
sets a new password with `PATCH /api/users/{id}/`.

Logout takes `{"refresh": "<token>"}` and answers `205`. A body that is not an
object, or a `refresh` that is missing or not a string, is a `400` validation
error. Logout closes every open WebSocket of the user, on every device, not only
the one that logged out. Sockets are not tied to a refresh token, so this is the
only way to stop a logged-out device receiving live events. Other devices
reconnect with a new ticket from `POST /api/ws/ticket/`.

### Users and agents

| Method | Route | Who | Purpose |
| --- | --- | --- | --- |
| `GET`, `POST` | `/api/users/` | Admins | List or create users |
| `GET`, `PATCH` | `/api/users/{id}/` | Admins | Read or update a user |
| `GET` | `/api/agents/` | Agents, admins | Active staff for assignment dropdowns |
| `GET` | `/api/agents/online/` | Agents, admins | Staff with a live presence entry |

Every user change writes a `UserEvent` audit row. Deactivation and password
resets revoke the user's sessions. An admin cannot demote or deactivate
themselves or reset their own password through user management.

### Tickets

| Method | Route | Who | Purpose |
| --- | --- | --- | --- |
| `GET`, `POST` | `/api/tickets/` | Signed in | List or create tickets |
| `GET`, `PUT`, `PATCH`, `DELETE` | `/api/tickets/{id}/` | Signed in | Read or update a ticket; only admins delete |
| `GET` | `/api/tickets/export/` | Agents, admins | CSV export of the filtered list |
| `POST` | `/api/tickets/{id}/restore/` | Admins | Restore a deleted ticket |
| `POST` | `/api/tickets/{id}/claim/` | Agents, admins | Claim an unassigned ticket |
| `POST` | `/api/tickets/{id}/read/` | Signed in | Mark a conversation read |
| `GET` | `/api/tickets/{id}/messages/` | Signed in | Messages after an `after` id |
| `GET` | `/api/tickets/{id}/events/` | Signed in | Ticket audit events |
| `GET`, `POST` | `/api/tickets/{id}/comments/` | Signed in | Deprecated message route |
| `GET`, `POST` | `/api/tickets/{id}/attachments/` | Signed in | Ticket attachments |
| `GET`, `POST` | `/api/tickets/{id}/comments/{comment_id}/attachments/` | Signed in | Comment attachments |
| `GET`, `POST` | `/api/tickets/{id}/rating/` | Customer owner | Read or submit the ticket rating |

Ticket list filters include `status`, `priority`, `assignee` (`assignee=me` is
supported), `tag`, `search` and `is_overdue`. Customers only ever see their own
tickets. Customers can edit only the title and description of their own open
tickets; status, priority, assignee and tags are staff-only.

The status workflow is validated: illegal transitions return `400` and write
nothing. Deletion is soft; comments, attachments and audit rows survive, and an
admin can restore the ticket.

Tickets have exactly one owner, either `customer` or `visitor`, enforced by a
database constraint. `channel` is `portal`, `chat` or `offline_form`. Visitor
tickets have `customer: null`; customers never see them.

#### Messages and comments

`POST /api/tickets/{id}/comments/` accepts `body`, `is_internal` (staff only) and
an optional `client_msg_id` of up to 64 characters, unique per ticket. A retry
with the same `client_msg_id` from the same sender returns the stored comment
with `200` instead of `201`. The same id from a different sender is rejected with
`400`. Visitor messages are always public.

`GET /api/tickets/{id}/messages/?after=<id>` is the preferred recovery route. It
returns `{results, has_more, unread_count}` with at most 100 messages, oldest
first. `after` defaults to `0` and must be an integer from 0 to 2^63-1.

#### Read state

`POST /api/tickets/{id}/read/` accepts an optional `last_read_comment_id` and
returns `{last_read_comment_id, unread_count}`. Without it, everything the
participant can see up to now is marked read. The marker only moves forward.
`unread_count` is included in every ticket response.

A message counts as unread when it comes after the marker, the participant may
see it and someone else wrote it. Own messages never count, internal notes never
count for customers or visitors, and system messages count for everyone.

#### Missed-message recovery

1. Keep the highest processed message id per conversation as `last_id`.
2. After connecting or reconnecting, join the socket, wait for `joined`, then
   call the messages route with `after=last_id` until `has_more` is false.
3. On a `message.created` event, call the messages route with `after=last_id`.
4. Merge by message id (and `client_msg_id` for optimistic messages) and only
   move `last_id` up.

Message ids are global, so gaps inside one conversation are normal.

#### Ratings

`GET /api/tickets/{id}/rating/` returns the existing rating or `404`.
`POST` is allowed only for the ticket owner, only after the ticket is resolved
or closed, and only once. The body is `score` (1 to 5) and an optional
`comment`. A conflict returns `409` with `ticket_not_resolved` or
`ticket_already_rated`.

#### Export

`GET /api/tickets/export/` streams a UTF-8 CSV with a byte order mark. It accepts
the same filters as the ticket list, is available to agents and admins, and
escapes cells that start with a formula character. Its throttle scope is
`export`.

### Tags and canned replies

| Method | Route | Who | Purpose |
| --- | --- | --- | --- |
| `GET` | `/api/tags/` | Agents, admins | List tags |
| `POST` | `/api/tags/` | Admins | Create a tag |
| `GET` | `/api/tags/{id}/` | Agents, admins | Read a tag |
| `PATCH`, `DELETE` | `/api/tags/{id}/` | Admins | Update or delete a tag |
| `GET`, `POST` | `/api/canned-replies/` | Agents, admins | List or create canned replies |
| `GET`, `PATCH`, `DELETE` | `/api/canned-replies/{id}/` | Agents, admins | Read, update or delete a canned reply |

Tag names are case-insensitively unique. Deleting a tag writes a `tag` audit
event for every ticket that carried it. Canned replies have a unique shortcut
and an optional title and body.

### Chat sites

| Method | Route | Who | Purpose |
| --- | --- | --- | --- |
| `GET`, `POST` | `/api/sites/` | Admins | List or create sites |
| `GET`, `PATCH` | `/api/sites/{id}/` | Admins | Read or update a site |
| `POST` | `/api/sites/{id}/rotate-key/` | Admins | Replace the public site key |

Sites can be filtered by `key` and `is_active`. `allowed_origins` accepts up to
20 origins in `scheme://host[:port]` form and normalizes them the way browsers
send the `Origin` header. `primary_color` is `#rrggbb`, `position` is
`bottom_right` or `bottom_left`, and `offline_timeout_minutes` is 1 to 1440.
Sites are deactivated, not deleted.

### Stats and audit

| Method | Route | Who | Purpose |
| --- | --- | --- | --- |
| `GET` | `/api/stats/` | Agents, admins | Support metrics |
| `GET` | `/api/audit/` | Admins | Append-only audit trail |

`GET /api/stats/` takes optional `date_from` and `date_to`. The default range is
30 days and the maximum is 366. Stats include ticket counts, per-day and
per-channel series, first-response and resolution averages, ratings and open
chats per agent.

`GET /api/audit/` supports `kind`, `actor`, `field_changed`, `date_from`,
`date_to` and `cursor`. It returns `{next, results}`. Audit rows are append-only.

### Downloads

| Method | Route | Who | Purpose |
| --- | --- | --- | --- |
| `GET` | `/api/attachments/{id}/download/` | Signed in | Signed attachment download link |
| `GET` | `/api/avatars/{id}/download/` | Signed in | Signed avatar download link |
| `GET` | `/api/downloads/{token}/` | Link holder | Stream a local-storage file |

Attachment and avatar routes check access first and return
`{url, expires_in}`. With S3 the URL is presigned. With local storage it points
to `/api/downloads/{token}/`, which verifies the signature and streams the file
in 64 KB chunks.

`/media/` is never served. Every download is forced with
`Content-Disposition: attachment` and `X-Content-Type-Options: nosniff` on local
responses. Attachment responses also contain a `download_url` field.

Avatar visibility: users can read their own avatar, staff can read any avatar,
signed-in users can read staff avatars, and a customer avatar is visible only to
that customer and staff.

### Realtime HTTP

| Method | Route | Who | Purpose |
| --- | --- | --- | --- |
| `POST` | `/api/ws/ticket/` | Signed in | Single-use WebSocket ticket |
| `POST` | `/api/widget/ws/ticket/` | Widget visitor | Single-use WebSocket ticket |

The socket protocol is in [Realtime](realtime.md). The widget routes are in
[Widget](widget.md).

### Widget

The public widget API is documented in [Widget](widget.md). It covers
`/api/widget/config/`, `/api/widget/challenge/`, the conversation routes,
attachments, ratings, contact details and downloads.

### Health and schema

| Method | Route | Who | Purpose |
| --- | --- | --- | --- |
| `GET` | `/health/` | Anyone | Database-free liveness check |
| `GET` | `/ready/` | Anyone | Dependency readiness check, cached for 5 seconds |
| `GET` | `/metrics/` | Metrics token | Prometheus metrics |
| `GET` | `/api/schema/` | Anyone in development; admin only when enabled in production | OpenAPI schema |
| `GET` | `/api/docs/` | Anyone in development; admin only when enabled in production | Swagger UI |

`/health/`, `/ready/` and `/metrics/` are not in the OpenAPI schema. See
[Operations](operations.md) for logging, throttling and metrics.

## Chat routing

When a visitor starts a conversation, the backend tries to assign it in the same
transaction that creates it.

1. Take active staff with a live `available` presence entry.
2. Lock their user rows in id order.
3. Drop agents whose open chats have reached `max_concurrent_chats`.
4. Pick the agent with the fewest open chats, then the one assigned a chat
   longest ago, then the lowest id.
5. Assign through `assign_ticket`, which calls `update_ticket`. That applies
   `validate_assignee` and records the assignee event, so routed chats follow the
   same rules and audit trail as a manual assignment. If the assignee is rejected,
   the chat stays queued.

With no available agent the conversation stays queued. Later messages do not
retry routing. The minute sweep assigns queued chats in creation order when an
agent has capacity. `last_chat_assigned_at` drives the round-robin tie-break.

`POST /api/tickets/{id}/claim/` is the manual path. An unassigned ticket is
assigned to the caller; the caller's own ticket is returned unchanged; another
agent's ticket returns `409` with `ticket_already_assigned`. A claim does not
check `max_concurrent_chats`.

## Offline fallback

A chat that nobody answers becomes an `offline_form` ticket. The Celery worker
must be running.

When a new conversation cannot be routed, `chat.convert_to_offline` is scheduled
after the transaction commits. With nobody online the countdown is `0`;
otherwise it is the site's `offline_timeout_minutes`. The minute sweep also
converts chats that passed their timeout without a public staff reply.

Conversion is skipped when the ticket is missing or deleted, is no longer a chat,
is resolved or closed, or already has a public staff message. Otherwise, in one
transaction with the ticket row locked, it:

1. Sets `channel` to `offline_form`.
2. Writes a `channel` audit event.
3. Adds a `system` message asking the visitor to leave contact details.
4. Publishes `conversation.offline` with `has_contact`.

The assignee is kept and the conversation continues in the same ticket. The
widget can submit contact details at `POST /api/widget/conversations/{id}/contact/`
while the conversation is open; see [Widget](widget.md#contact-details).
