# Operations

This page covers logging, rate limits, metrics, and the production and security
checks. Configuration variables are listed in
[Configuration](configuration.md).

## Logging

Every log line, from the web process and the Celery worker, is a single JSON
object written to stdout:

```json
{"timestamp":"2026-10-12T09:41:07.532+00:00","level":"INFO","logger":"core.access","message":"request completed","request_id":"3f2b8c1e9a4d4f6f8e1b7c2d5a9e0f13","user_id":7,"method":"GET","path":"/api/tickets/","status":200,"duration_ms":18.4,"client_ip":"172.18.0.1"}
```

- `request_id` comes from an incoming `X-Request-ID` header when it is 8 to 64
  characters of letters, digits, `.`, `_` or `-`; otherwise it is generated.
  Every response carries it in `X-Request-ID`, including errors, throttled
  requests and CORS preflights. The header is exposed through CORS.
- `user_id` is the authenticated user id, or `null` for anonymous requests and
  for login, refresh and registration.
- Every request writes one `core.access` line. `/health/` and `/metrics/` are
  written at `DEBUG` only, and 5xx responses are written at `ERROR`.
  `duration_ms` is the time to produce the response, so streamed downloads do
  not include the transfer.
- Unhandled exceptions are logged by `django.request` at `ERROR` with the
  traceback in `exception` and the same `request_id`. Client errors are covered
  by the access line only.

Follow one request by its id:

```bash
docker compose logs web --no-log-prefix | grep 3f2b8c1e9a4d4f6f8e1b7c2d5a9e0f13
docker compose logs web --no-log-prefix | jq -R -c 'fromjson? | select(.request_id == "3f2b8c1e9a4d4f6f8e1b7c2d5a9e0f13")'
```

The code never logs headers, bodies or query strings. The formatter also
redacts tokens in `/api/downloads/<token>/` paths, bearer tokens, JWTs and
secret-looking query parameters, and masks extra fields with sensitive names
(`password`, `token`, `authorization`, `cookie`, `signature` and similar).

`LOG_LEVEL` sets verbosity (`INFO` by default).

## Rate limits

Throttling uses Redis, because counters are kept in Django's cache. A throttled
request returns `429` with the standard error envelope (`error.code` is
`throttled`) and a `Retry-After` header.

| Scope | Applies to | Counted per | Limit |
| --- | --- | --- | --- |
| `anon` | Every route, signed out | IP address | 120/min |
| `user` | Every route, signed in | User | 300/min |
| `login` | `POST /api/token/` | IP address | 30/min |
| `login_username` | `POST /api/token/` | Username + IP address | 20/hour |
| `login_username_global` | `POST /api/token/` | Username | 120/hour |
| `register` | `POST /api/auth/register/` | IP address | 30/hour |
| `password_change` | `POST /api/auth/password/change/` | User | 5/hour |
| `user_management` | `/api/users/` | User | 60/min |
| `site_management` | `/api/sites/` | User | 60/min |
| `download` | `/api/downloads/{token}/` | IP address | 300/min |
| `export` | `GET /api/tickets/export/` | User | 10/min |
| `attachment_upload` | Attachment upload routes | User | 60/hour |
| `ws_ticket` | `POST /api/ws/ticket/` | User | 30/min |
| `widget_ip` | Every `/api/widget/` route | IP address | 240/min |
| `widget_visitor` | Widget routes with a visitor token | Visitor | 90/min |
| `widget_start` | `POST /api/widget/conversations/` | IP address | 60/hour |
| `widget_upload` | `POST /api/widget/conversations/{id}/attachments/` | Visitor | 30/hour |

When the per-username global login budget is spent, login is delayed by
`LOGIN_USERNAME_SLOWDOWN_SECONDS` instead of rejected, so a botnet cannot lock
an account out. The per-username + IP and per-IP budgets still return `429`.

The limits live in `REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]` in
`config/settings/throttling.py`. Behind a reverse proxy set `NUM_PROXIES` to the
number of proxies, so the real client address is read from `X-Forwarded-For`.
With `0` the header is ignored, which prevents spoofing. Production refuses to
start without `NUM_PROXIES`; `ALLOW_ZERO_PROXIES=true` opts into the
direct-access case.

Reset counters while testing by hand:

```bash
docker compose exec redis redis-cli FLUSHDB
```

WebSocket limits are in [Realtime](realtime.md#limits).

## Metrics

`GET /metrics/` returns Prometheus text. It is a plain Django view: no throttle,
no JSON error envelope and no OpenAPI entry.

- Send `Authorization: Bearer <METRICS_TOKEN>`. A missing or wrong token gets
  `401`; an empty `METRICS_TOKEN` makes the route answer `404`.
- `ticketing_http_requests_total{method,view,status}` counts handled requests
  and `ticketing_http_request_duration_seconds{method,view}` is a latency
  histogram. `view` is the URL name, never the raw path. Unmatched routes use
  `unmatched`, unusual methods use `OTHER`, and `/metrics/` itself is not
  counted.
- `ticketing_websocket_connections{endpoint,client}` is the number of open
  sockets. `endpoint` is `tickets` or `presence`; `client` is `agent`,
  `customer` or `visitor`.
- `ticketing_queue_size` is the number of unassigned tickets that are not
  resolved or closed. It uses the same definition as `queue_size` in
  `GET /api/stats/`. A database error leaves this metric out without failing
  the scrape.
- Standard `prometheus_client` Python and process metrics are included.
- Keep `/metrics/` on an internal network. It is exempt from the HTTPS redirect
  so an internal scraper can use plain HTTP.
- With several server processes set `PROMETHEUS_MULTIPROC_DIR` to an empty
  directory before they start. The Celery worker does not serve metrics.

```bash
curl -H "Authorization: Bearer dev-metrics-token" http://localhost:8000/metrics/
docker compose --profile monitoring up -d prometheus
```

Open http://localhost:9090/targets; the `ticketing` target should be `UP`. The
token comes from `METRICS_TOKEN`, and `web` must be in `ALLOWED_HOSTS` because
Prometheus calls `http://web:8000`.

## Production settings check

`manage.py check --deploy` must report no issues with the production settings.
Run it inside the dev container with throwaway keys:

```bash
docker compose exec \
  -e DJANGO_SETTINGS_MODULE=config.settings.prod \
  -e SECRET_KEY=local-deploy-check-secret-key-0123456789-abcdefghijklmnopqrstuvwxyz \
  -e JWT_SIGNING_KEY=local-deploy-check-jwt-key-9876543210-zyxwvutsrqponmlkjihgfedcba \
  -e ALLOWED_HOSTS=localhost \
  -e DATABASE_URL=postgres://ticketing:ticketing@db:5432/ticketing \
  -e NUM_PROXIES=1 \
  web python manage.py check --deploy --fail-level WARNING
```

CI runs the same check on every push.

## Security checks

The `security` CI job runs two checks and fails on findings.

```bash
bandit -r . -c pyproject.toml --severity-level medium --confidence-level medium
pip-audit -r requirements.txt --no-deps --disable-pip
pip-audit -r requirements-dev.txt --no-deps --disable-pip
```

Install the tools with `pip install -r requirements-security.txt`.

- `bandit` scans for common security mistakes at medium severity and medium
  confidence. Configuration is in `[tool.bandit]` in `pyproject.toml`; `B101`
  is skipped because tests use asserts.
- `pip-audit` audits pinned runtime and development dependencies. `--no-deps`
  keeps the audit focused on what the project pins, and `--disable-pip` resolves
  from the requirements files without touching the environment.

## Load testing

Load-test tooling and measured runs live in `loadtest/` when the folder is
present. The dedicated settings module
`config.settings.loadtest` extends development settings and relaxes throttle
rates. It is selected with `DJANGO_SETTINGS_MODULE`, so production never needs a
load-test escape hatch.
