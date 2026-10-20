# Realtime

The app is an ASGI application (`config/asgi.py`). HTTP goes to Django and
WebSocket connections go to `/ws/` and `/ws/presence/` (`config/routing.py`). In
development `runserver` is served by Daphne, so it handles both. The channel
layer is `channels_redis` on `CHANNEL_REDIS_URL` with the key prefix `ticketing`. Tests
use the in-memory channel layer.

## Connecting

1. Get a ticket over HTTP. Signed-in users call `POST /api/ws/ticket/` with
   their access token. Widget visitors call `POST /api/widget/ws/ticket/` with
   `X-Visitor-Token` from an allowed origin. The response is
   `{ticket, expires_in}`.
2. Open `ws://localhost:8000/ws/?ticket=<ticket>` before it expires.

A ticket works once and expires after `WS_TICKET_TTL_SECONDS`. A missing,
unknown, reused or expired ticket, a deactivated user, a deactivated site and a
visitor whose `Origin` header is not in the site's `allowed_origins` are all
refused at the handshake with HTTP 403.

```js
const { ticket } = await fetch("http://localhost:8000/api/ws/ticket/", {
  method: "POST",
  headers: { Authorization: `Bearer ${accessToken}` },
}).then((response) => response.json());

const ws = new WebSocket(`ws://localhost:8000/ws/?ticket=${ticket}`);
ws.onmessage = (event) => console.log(event.data);
ws.onopen = () => ws.send(JSON.stringify({ type: "join", ticket_id: 1 }));
```

## Messages

Every message is a JSON object with a `type`.

| Direction | Message | Meaning |
| --- | --- | --- |
| Client to server | `{"type": "ping"}` | Heartbeat. The server answers `{"type": "pong"}` |
| Client to server | `{"type": "join", "ticket_id": 1}` | Subscribe to a ticket. The server answers `{"type": "joined", "ticket_id": 1}` |
| Client to server | `{"type": "leave", "ticket_id": 1}` | Unsubscribe. The server answers `{"type": "left", "ticket_id": 1}` |
| Client to server | `{"type": "typing", "ticket_id": 1, "is_typing": true}` | Tell others you started or stopped typing. Never answered |
| Server to client | `{"type": "typing", "ticket_id": 1, "is_typing": true, "sender_type": "agent", "sender_name": "..."}` | Someone else in a joined ticket started or stopped typing |
| Server to client | `{"type": "error", "code": "...", "ticket_id": 1}` | A message was rejected |

Error codes: `invalid_json`, `invalid_message`, `unknown_type`,
`invalid_ticket_id`, `not_found`, `not_joined` and `too_many_tickets`.

- A visitor can join only their own conversations, a customer only their own
  tickets, and an agent or admin any ticket that is not deleted. Anything else
  answers `not_found`, so a client cannot tell a missing ticket from someone
  else's.
- A connection can be joined to at most 50 tickets at once.

## Events

Changes are pushed as events with the shape `{"type", "id", "ticket_id",
"data"}`. They are sent only after the database transaction commits.

| Type | `id` | `data` | Recipients |
| --- | --- | --- | --- |
| `message.created` | Message id | `message_id`, `kind`, `sender_type`, `is_internal`, `client_msg_id` | Everyone in the ticket; internal notes reach staff only |
| `ticket.event` | Audit event id | `field_changed`, `old_value`, `new_value` | Everyone in the ticket; assignee changes reach staff only |
| `conversation.offline` | Audit event id of the channel change | `has_contact` | Everyone in the ticket and the agents queue |

- Agents and admins receive every ticket's events through the agents queue.
  Customers and visitors receive events only for tickets they joined.
- `data.message_id` of `message.created` is the id to use as the `after` cursor.
  The `id` of `ticket.event` and `conversation.offline` is from another sequence
  and must never be used as a message cursor.
- `conversation.offline` tells the widget that the chat became offline.
  `has_contact` is `true` when the visitor already left a phone or email. The
  widget can then use `POST /api/widget/conversations/{id}/contact/`.
- A conversion also produces a `ticket.event` with `field_changed` set to
  `channel` and a `message.created` event for the system message.
- Events do not carry message text. Fetch messages with the cursor strategy in
  [API notes](api-notes.md#missed-message-recovery).

## Typing indicators

Typing signals are ephemeral. They are not stored, not part of the audit trail
and not sent to the agents queue.

- The client must have joined the ticket first, otherwise the answer is
  `not_joined`. `is_typing` must be a boolean, otherwise `invalid_message`.
- The sender never receives its own signal, and neither does another socket of
  the same user or visitor.
- The server throttles per connection and ticket: a `true` within
  `WS_TYPING_THROTTLE_SECONDS` of the previous `true` is dropped silently, and a
  `false` is relayed only after a `true`.
- Leaving a ticket or disconnecting while typing sends `is_typing: false`.
- Clients should repeat `true` about every 3 seconds while typing and hide the
  indicator 5 seconds after the last `true`.
- Clients should debounce keystrokes and not send typing signals while writing
  an internal note.

## Limits

| Limit | Result |
| --- | --- |
| Message larger than `WS_MAX_MESSAGE_BYTES` | Connection closed with code `1009` |
| More than `WS_RATE_LIMIT_MESSAGES` messages in `WS_RATE_LIMIT_WINDOW_SECONDS` | Connection closed with code `4429` |
| Binary frame | Connection closed with code `1003` |
| Typing update within `WS_TYPING_THROTTLE_SECONDS` | Dropped silently, connection stays open |

The same size, rate and binary limits apply to the presence socket.

Check that the Redis channel layer works:

```bash
docker compose exec web python manage.py shell -c "from asgiref.sync import async_to_sync; from channels.layers import get_channel_layer; layer = get_channel_layer(); async_to_sync(layer.send)('probe', {'type': 'ping'}); print(async_to_sync(layer.receive)('probe'))"
```

The production image runs Daphne (ASGI), so one process serves HTTP and
WebSocket. See [Self-hosting](self-hosting.md).

## Agent presence

Presence tells the system which staff members are online and whether they accept
new chats. It is kept in Redis with a time-to-live, so a closed tab or crashed
browser drops out by itself.

### Presence socket

Agents and admins connect to
`ws://localhost:8000/ws/presence/?ticket=<ticket>` with a ticket from
`POST /api/ws/ticket/`. An anonymous socket and a visitor are closed with
`4401`, and a customer with `4403`.

| Direction | Message | Meaning |
| --- | --- | --- |
| Server to client | `{"type": "presence", "status": "available"}` | Sent on connect and after every status change |
| Client to server | `{"type": "ping"}` | Heartbeat. Refreshes the TTL and answers `{"type": "pong", "status": "available"}` |
| Client to server | `{"type": "set_status", "status": "away"}` | Set `available` or `away`; answers with a `presence` message |
| Server to client | `{"type": "error", "code": "..."}` | Codes: `invalid_json`, `invalid_message`, `unknown_type`, `invalid_status` |

- A staff member is online while their presence entry exists. It is created on
  connect, refreshed by every `ping` and removed by Redis after
  `PRESENCE_TTL_SECONDS` without a refresh. Clients should ping well inside that
  time, for example every 10 seconds with the default of 30.
- Closing the socket does not delete the entry, so the agent goes offline within
  the TTL.
- Presence is per user, not per socket. Two tabs share one status; closing one
  does not take the agent offline while the other keeps sending heartbeats.
- A new connection keeps the stored status when the entry is alive. Without an
  entry the status starts as `available`.
- Only `available` agents receive new chats. `away` agents stay online and keep
  the chats they have.

### Online agents

`GET /api/agents/online/` lists every active staff member with a live presence
entry, ordered by name.

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

- `open_chats` counts chat tickets assigned to the agent that are not deleted,
  resolved or closed. Converted offline tickets no longer count.
- `accepting_chats` is `true` when the status is `available` and `open_chats` is
  below `max_concurrent_chats`.
- Staff set their own `max_concurrent_chats` (1 to 50, default 5) at
  `PATCH /api/auth/me/`.

Chat routing and offline fallback are described in
[API notes](api-notes.md#chat-routing).
