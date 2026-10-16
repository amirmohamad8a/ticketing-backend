# Load testing

This directory holds the WebSocket + HTTP load test for the chat widget and the
realtime layer, plus the measured runs under [`results/`](results/).

## Tool: k6

The test is written for [k6](https://k6.io/) (`loadtest/ws_visitors.js`). k6 was
chosen over Locust because the load is mostly long-lived WebSocket connections
with a fixed message rate:

- `k6/ws` speaks the WebSocket protocol natively, so the same script drives the
  visitor sockets, the agent sockets and the REST calls without a custom
  protocol layer.
- k6 is a single static binary. It runs from the official `grafana/k6` image,
  so it does not add anything to `requirements.txt` or `requirements-dev.txt`.
- The VU model and the built-in `Trend`/`Counter` metrics give p50/p95/p99 and
  error counts out of the box.

## What the script does

With `N = VISITORS` and `M = AGENTS`:

1. `setup()` logs in the agent account once (`demo_agent`) and shares the access
   token with every agent VU.
2. Each visitor VU starts a conversation at `POST /api/widget/conversations/`
   with the site key, receives a visitor token, exchanges it for a single-use
   ticket at `POST /api/widget/ws/ticket/` and opens `ws://.../ws/?ticket=...`
   with `Origin` set to an allowed origin of the site.
3. The visitor sends `{"type":"join","ticket_id":...}` and then posts a message
   every `MSG_INTERVAL_MS` over `POST /api/widget/conversations/{id}/messages/`.
4. Each agent VU gets a ticket at `POST /api/ws/ticket/` with the agent access
   token and opens its own `/ws/` socket. Staff sockets receive every ticket
   event through the `agents.queue` channel-layer group. Each agent owns the
   tickets where `ticket_id % M == agentIndex`, lazily joins each one and
   answers with `POST /api/tickets/{id}/comments/`.
5. Latency is measured in one k6 process, so `Date.now()` is a shared clock.
   The visitor stamps each message with `client_msg_id = <send ms>` and the
   agent reports `visitor_to_agent_ms` when the event arrives. The agent stamps
   each reply the same way and the visitor reports `agent_to_visitor_ms`.

Every connection uses a fresh single-use `ws_ticket`; tickets are never reused.

## Prerequisites

- Docker with Compose, and the stack running: `docker compose up -d`.
- A seeded database: `docker compose exec web python manage.py seed_demo`. It
  creates the site `demo-store-widget-key` with origins
  `http://localhost:3000` and `http://127.0.0.1:3000`, the customer
  `demo_customer` and the agent `demo_agent` (password `demo-ticketing-2026`).
  `setup()` only needs the agent account; the customers are the anonymous
  widget visitors the script creates itself.
- The `grafana/k6` image (pulled on first use).

`seed_demo` is idempotent, and the script can be pointed at any site/agent with
`SITE_KEY`, `AGENT_USERNAME` and `AGENT_PASSWORD`.

## Rate limits

A naive run would be stopped by the per-IP widget throttles long before it
measures anything: `widget_start` is 20/hour and `widget_ip` is 120/min, and all
k6 traffic comes from one address. The agent replies share one `user` budget
(300/min) too.

The load test therefore runs the `web` service with relaxed limits, without ever
changing the production defaults. `config/settings/base.py` reads an optional
`LOADTEST_THROTTLE_RATES` JSON object of `{"scope": "rate"}` pairs and merges it
over `REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]`. It is empty by default, so
`docker compose up` keeps the limits documented in the README's "Rate limits"
section. `loadtest/docker-compose.loadtest.yml` is a Compose override that sets
that variable (and adds `web` to `ALLOWED_HOSTS` so k6 can call the service by
name) for the `web` service only:

```bash
docker compose -f docker-compose.yml -f loadtest/docker-compose.loadtest.yml up -d web
```

After a run, go back to the normal limits with `docker compose up -d web`.

## Running

The examples below run k6 on the Compose network and call the app as
`http://web:8000`, so `Origin` can stay `http://localhost:3000`:

```bash
MSYS_NO_PATHCONV=1 docker run --rm \
  --network ticketing-backend_default \
  -v "$PWD/loadtest:/loadtest:ro" \
  -e BASE_URL=http://web:8000 \
  -e VISITORS=50 -e AGENTS=5 \
  -e SESSION_MS=20000 \
  -e MSG_INTERVAL_MS=1000 \
  -e MESSAGE_SIZE=64 \
  -e WARMUP_MS=2000 \
  grafana/k6 run /loadtest/ws_visitors.js
```

On Windows PowerShell, pass the host path instead of `$PWD`:

```powershell
docker run --rm --network ticketing-backend_default `
  -v "C:\path\to\ticketing-backend\loadtest:/loadtest:ro" `
  -e BASE_URL=http://web:8000 -e VISITORS=50 -e AGENTS=5 `
  grafana/k6 run /loadtest/ws_visitors.js
```

Environment variables:

| Variable | Default | Meaning |
| --- | --- | --- |
| `BASE_URL` | `http://localhost:8000` | HTTP base URL |
| `WS_URL` | `BASE_URL` with `ws` scheme | WebSocket base URL |
| `SITE_KEY` | `demo-store-widget-key` | Site whose visitors connect |
| `ORIGIN` | `http://localhost:3000` | `Origin` header, must be in the site's `allowed_origins` |
| `AGENT_USERNAME` / `AGENT_PASSWORD` | `demo_agent` / `demo-ticketing-2026` | Staff account for the agent sockets |
| `VISITORS` | `10` | `N`, visitor sockets and conversations |
| `AGENTS` | `5` | `M`, agent sockets |
| `SESSION_MS` | `20000` | How long each socket stays open |
| `MSG_INTERVAL_MS` | `1000` | Interval between visitor messages |
| `WARMUP_MS` | `2000` | Delay before a visitor starts sending, so agents are connected |
| `MESSAGE_SIZE` | `64` | Message body length in bytes |

Run it at increasing `VISITORS` (for example 10, 50, 100, 200) with a matching
`AGENTS`, and flush Redis between runs so throttles and tickets do not carry
over:

```bash
docker compose exec redis redis-cli FLUSHDB
```

## Reading the results

k6 prints a summary. The metrics to read:

| Metric | Meaning |
| --- | --- |
| `ws_connect_success_rate` | Fraction of attempted handshakes that returned `101` |
| `ws_connect_ms` | Handshake time (p50/p95/p99) |
| `visitor_to_agent_ms` | Visitor send → agent socket receive |
| `agent_to_visitor_ms` | Agent reply → visitor socket receive |
| `messages_sent_total` | Visitor messages that got a 2xx |
| `agent_replies_total` | Agent replies that got a 2xx |
| `visitor_replies_received_total` | Reply events the visitors received |
| `http_429_total`, `http_5xx_total`, `http_other_errors_total` | HTTP failures by class |
| `ws_close_1009_total`, `ws_close_4429_total`, `ws_close_1003_total` | Sockets the server closed for size, rate and binary-frame limits |
| `ws_abnormal_close_total` | Other non-clean closes |
| `ws_connect_failures_total` | Handshakes that did not return `101` |

k6 omits a counter that never received a sample, so a counter missing from the
summary is zero. Compare runs at increasing N to find where latency and error
counts start to grow.

## Results

Measured runs are committed under [`results/`](results/). Each file records the
machine, the parameters, the full table and the observed degradation point.
Start with [`results/2026-10-16-local.md`](results/2026-10-16-local.md), which
also contains the `results-template.md` layout for new runs.
