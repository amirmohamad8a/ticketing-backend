# Configuration

Settings are read from environment variables.

## The env file

Each machine has a single `.env`, which is the only env file. Compose reads it for
variable interpolation and for `env_file`, and the settings read the same
variables. Create it with `sh scripts/bootstrap.sh dev|prod`, or copy
`.env.example` by hand.

`.env.example` has two sections:

- **Development** (active): working local defaults, with `COMPOSE_FILE` set to the
  dev files.
- **Production** (commented out, clearly marked): delete the development section,
  uncomment the production section and replace every `change-me` value. The two
  sections define the same keys, so keep only one.

Production refuses to start when `SECRET_KEY` or `JWT_SIGNING_KEY` is shorter than
50 characters, contains `change-me` or starts with `dev-`, when the two are equal,
or when `METRICS_TOKEN` is an example value. `scripts/bootstrap.sh` generates
64-character hex values that pass these checks.

In production, Compose derives `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS` and, unless
you set it, `CORS_ALLOWED_ORIGINS` from `DOMAIN`, so they are not listed in the
production section.

### Compose variables

These are read by Compose, not by the Django settings.

| Variable | Used in | Default | Description |
| --- | --- | --- | --- |
| `COMPOSE_FILE` | both | set in `.env.example` | Colon-separated Compose files: base plus `docker-compose.dev.yml` or `docker-compose.prod.yml` |
| `COMPOSE_PATH_SEPARATOR` | both | `:` | Separator used in `COMPOSE_FILE`, fixed so it also works on Windows |
| `DOMAIN` | production | none, required | Public host name Caddy serves. `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS` and `CORS_ALLOWED_ORIGINS` derive from it |
| `ADMIN_ALLOWED_IPS` | production | `127.0.0.1` | Space-separated IPs or CIDRs allowed to reach `/admin/`. Everyone else gets `403` |
| `DB_PORT` | development | `5432` | Host port the dev database is published on, on `127.0.0.1` |
| `PYTHON_IMAGE` | both | `python:3.12-slim` | Base image for the Docker build |
| `PIP_INDEX_URL` | both | `https://pypi.org/simple` | Package index used during the Docker build |

Settings are split under `config/settings/`:

- `base.py` composes the shared settings.
- `security.py`, `throttling.py`, `jwt.py`, `storage.py`, `redis.py`,
  `celery.py`, `logging.py`, `widget.py` and `realtime.py` hold one concern
  each.
- `dev.py`, `test.py` and `prod.py` adjust the shared values.
- `loadtest.py` extends `dev.py` and relaxes throttle rates for load tests.

`prod.py` runs the production checks in `validation.py` before the app starts.

## Variables

| Variable | Required | Default | Description |
| --- | --- | --- | --- |
| `SECRET_KEY` | Yes | none | Django secret key |
| `JWT_SIGNING_KEY` | Production | `SECRET_KEY` | Key that signs JWTs and visitor tokens. Production refuses to start without one that differs from `SECRET_KEY` |
| `DEBUG` | No | `False` | Debug mode. Development settings force it on |
| `ALLOWED_HOSTS` | No | empty | Comma-separated host names. Include `web` when Prometheus scrapes the app. The production Compose file sets it to `DOMAIN` |
| `DATABASE_URL` | Yes | none | PostgreSQL connection URL. Startup fails for any other scheme |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | With prod | `ticketing` | Credentials the production Compose database container creates. `DATABASE_URL` must match them; `scripts/bootstrap.sh` builds it from them |
| `DJANGO_SETTINGS_MODULE` | No | `config.settings.dev` | `config.settings.prod` in production; `config.settings.loadtest` for load tests |
| `REDIS_URL` | No | `redis://localhost:6379/0` | Celery broker and result backend, Django cache (throttle counters, WebSocket tickets, presence) and the Channels layer |
| `NUM_PROXIES` | Production | `0` in dev | Number of reverse proxies in front of the app, used for the client IP in throttling and logging. Production refuses to start unless it is set |
| `ALLOW_ZERO_PROXIES` | No | `false` | Production only. Allows `NUM_PROXIES=0` for a deliberate direct-access deployment and logs a warning |
| `WEB_REPLICAS` | No | `2` | Production Compose only. Number of `web` containers that Caddy load-balances across |
| `MAX_REQUEST_BODY_BYTES` | No | `65536` | Largest body for normal routes. The ASGI layer answers `413` before Django spools it to disk |
| `MAX_UPLOAD_BODY_BYTES` | No | `11534336` | Largest body on `/attachments/` and `/api/auth/me/`, where multipart uploads go |
| `ADMIN_LOGIN_MAX_ATTEMPTS` | No | `10` | Django admin login attempts per IP address per window. `0` disables the limiter |
| `ADMIN_LOGIN_WINDOW_SECONDS` | No | `300` | Length of the Django admin login attempt window |
| `LOG_LEVEL` | No | `INFO` | Verbosity of the JSON logs (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `METRICS_TOKEN` | No | empty | Bearer token for `GET /metrics/`. Empty disables the endpoint |
| `PROMETHEUS_MULTIPROC_DIR` | No | unset | Directory for metric files when several server processes run. Must exist and be empty at start |
| `CORS_ALLOWED_ORIGINS` | No | empty | Comma-separated origins allowed to call the API. Widget routes accept any origin and check the site's `allowed_origins` instead. The production Compose file defaults it to `https://$DOMAIN` |
| `CSRF_TRUSTED_ORIGINS` | No | empty | Production only. Comma-separated trusted origins. The production Compose file sets it to `https://$DOMAIN` |
| `SECURE_SSL_REDIRECT` | No | `true` | Production only. Redirect HTTP to HTTPS (`/health/`, `/ready/` and `/metrics/` are exempt). Set `false` for plain HTTP without a proxy |
| `SECURE_HSTS_SECONDS` | No | `31536000` | Production only. HSTS lifetime |
| `PORT` | No | `8000` | Port Daphne listens on |
| `STORAGE_BACKEND` | No | `local` | `local` for disk or `s3` for an S3-compatible bucket |
| `DOWNLOAD_URL_TTL_SECONDS` | No | `300` | Lifetime of signed download URLs |
| `VISITOR_TOKEN_LIFETIME_DAYS` | No | `30` | Lifetime of a widget visitor token |
| `VISITOR_RETENTION_DAYS` | No | `30` | Age after which visitors without tickets are deleted and finished-conversation contact details are cleared |
| `WIDGET_POW_DIFFICULTY` | No | `0` in dev, `16` in prod | Leading zero bits a widget conversation challenge must satisfy. `0` disables proof of work |
| `WIDGET_POW_TTL_SECONDS` | No | `300` | Lifetime of a widget proof-of-work challenge |
| `WIDGET_SITE_START_LIMIT_PER_HOUR` | No | `300` | New conversations per site per hour |
| `WIDGET_SITE_MAX_UNASSIGNED_CHATS` | No | `200` | Recent unassigned chats a site may have before new starts get `429` |
| `WIDGET_SITE_UNASSIGNED_WINDOW_MINUTES` | No | `60` | How far back the unassigned-chat cap counts |
| `WS_TICKET_TTL_SECONDS` | No | `30` | Lifetime of a single-use WebSocket ticket |
| `WS_MAX_MESSAGE_BYTES` | No | `4096` | Largest WebSocket message a client may send |
| `WS_RATE_LIMIT_MESSAGES` | No | `30` | Messages a single connection may send per window |
| `WS_RATE_LIMIT_WINDOW_SECONDS` | No | `10` | Length of the per-connection rate-limit window |
| `WS_TYPING_THROTTLE_SECONDS` | No | `2` | Minimum time between relayed typing signals for the same connection and ticket |
| `PRESENCE_TTL_SECONDS` | No | `30` | How long a presence entry lives without a heartbeat |
| `S3_BUCKET_NAME` | With `s3` | none | Bucket that holds attachments and avatars |
| `S3_ACCESS_KEY` | With `s3` | none | Access key for the bucket |
| `S3_SECRET_KEY` | With `s3` | none | Secret key for the bucket |
| `S3_ENDPOINT_URL` | No | AWS | S3 endpoint the server uses, for example `http://minio:9000` |
| `S3_PUBLIC_ENDPOINT_URL` | No | `S3_ENDPOINT_URL` | Endpoint embedded in signed URLs when clients reach the bucket on another address |
| `S3_REGION_NAME` | No | `us-east-1` | Bucket region |
| `AUTO_CLOSE_AFTER_DAYS` | No | `7` | Age after which a resolved ticket is closed |
| `SLA_FIRST_RESPONSE_LOW_MINUTES` | No | `1440` | First-response target for low priority |
| `SLA_FIRST_RESPONSE_MEDIUM_MINUTES` | No | `480` | First-response target for medium priority |
| `SLA_FIRST_RESPONSE_HIGH_MINUTES` | No | `240` | First-response target for high priority |
| `SLA_FIRST_RESPONSE_URGENT_MINUTES` | No | `60` | First-response target for urgent priority |

## S3 and MinIO

Files go to local disk by default. To test the S3 path locally, set
`STORAGE_BACKEND=s3` and start the stack with the `s3` profile:

```bash
docker compose --profile s3 up --build
```

This starts MinIO and creates a private bucket named after `S3_BUCKET_NAME`. The
console is at http://localhost:9001. Containers reach MinIO at
`http://minio:9000`; signed URLs use `S3_PUBLIC_ENDPOINT_URL`
(`http://localhost:9000`) so the browser can reach them.
