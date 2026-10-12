# Ticketing Backend

A support-ticketing REST API built with Django and Django REST Framework. Customers open tickets, agents work them through a validated status workflow, and every change is recorded in an append-only audit log.

## Features

- Three roles (customer, agent, admin) on a custom user model
- Self-service registration at `POST /api/auth/register/`: it always creates a customer (a role can never be chosen), checks the password with Django's validators and accepts an optional unique Iranian mobile number, which is normalized to `09XXXXXXXXX`
- Profile at `GET/PATCH /api/auth/me/`: first and last name, an optional phone number and an optional avatar (PNG, JPEG or WebP up to 2 MB, verified as a real image and stored under a random name). The username and role cannot be changed there. The response carries an `avatar_download_url` instead of a file URL
- Password change at `POST /api/auth/password/change/`: it needs the current password, applies Django's validators, revokes every refresh token of the user and returns a fresh token pair for the session that made the change
- User management for admins at `/api/users/`: list with `role` and `is_active` filters, create users (agents by default), change roles, deactivate and reactivate accounts and reset passwords. Every change writes a row to an append-only `UserEvent` log, deactivation and password resets revoke the user's sessions, and an admin cannot demote or deactivate themselves or reset their own password there
- Agents list for assignment dropdowns at `GET /api/agents/`: the id, display name and role of every active agent and admin, readable by agents and admins only. It is not paginated and exposes no usernames, phone numbers or other account details
- Chat sites for admins at `/api/sites/`: a `Site` is a website that will host the chat widget. It has a name, an auto-generated public key, a list of allowed origins, an active flag and the widget settings (greeting, primary color, position, offline timeout, whether a name or a contact is required). Allowed origins are validated, normalized to the form browsers send in the `Origin` header and deduplicated. Sites can be listed (filterable by `key` and `is_active`), created, read and updated, and the key can be rotated at `POST /api/sites/{id}/rotate-key/`. A site is deactivated rather than deleted
- Chat visitors and ticket ownership: a `Visitor` belongs to a site and has an optional name, phone and email, a `last_seen_at` and a `created_at`. Every ticket has a `channel` (`portal`, `chat` or `offline_form`, `portal` by default) and an optional `site`. A ticket belongs to exactly one owner, either a `customer` or a `visitor`, enforced by a database check constraint and by `Ticket.clean()`. Customers and visitors with tickets cannot be deleted, and neither can sites that have visitors or tickets
- Messages as comments: a chat message is a `Comment` with a `kind` (`message` or `system`), an optional `visitor` and an optional `client_msg_id`. Every message has exactly one sender, an `author` or a `visitor`, enforced by a database check constraint and by `Comment.clean()`, and system messages have neither. Sending again with the same `client_msg_id` returns the stored comment instead of creating a second row. Comment responses carry a `sender_type` (`customer`, `agent`, `visitor` or `system`), and internal notes stay hidden from customers
- JWT authentication with short-lived access tokens, rotating refresh tokens, a blacklist and logout. Tokens are signed with their own `JWT_SIGNING_KEY`, so a leaked `SECRET_KEY` cannot be used to forge them
- Immediate token revocation: a password change or reset invalidates the user's access tokens at once instead of at the end of their 15-minute lifetime, and deactivation does the same
- Rate limiting: every route is throttled per IP address (anonymous) or per user (signed in), with stricter limits on login, registration, password change, user management, site management and signed downloads. A throttled request gets `429` in the standard error format with a `Retry-After` header. Counters live in Redis, so they are shared between processes
- Production hardening: HTTPS redirect, HSTS with subdomains and preload, secure cookies, `nosniff` and a strict referrer policy, checked by `manage.py check --deploy`
- Structured logging: every log line is one JSON object with a timestamp, level, logger, message, `request_id` and `user_id`. A request ID middleware keeps a valid incoming `X-Request-ID` or generates one, stamps it on every log line of that request and returns it in the `X-Request-ID` response header (exposed to browsers through CORS), so a bug report that quotes the ID can be traced end to end. Each request writes one access line with the method, path, status, duration and client IP. Passwords, tokens, signed download URLs and query strings never reach the logs
- Role-scoped querysets: a customer only ever sees their own tickets
- Field-level permissions: customers can edit only the title and description of their own open tickets, and status, priority and assignee are staff-only
- Soft delete: only admins can delete a ticket, deletion hides it without removing its comments, attachments or audit rows, and admins can restore it at `/api/tickets/{id}/restore/`
- Ticket status state machine: illegal transitions return 400 and write nothing
- Assignee validation: a ticket can only be assigned to an active agent or admin
- Append-only audit trail of status and assignee changes, enforced in the model and readable at `/api/tickets/{id}/events/`
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
- Automated tests with an 85% coverage threshold and GitHub Actions CI

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
- `offline_timeout_minutes`: from 1 to 1440
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

## Forgotten passwords

There is no password reset by email. Outbound email is out of scope for this project, so a user who forgets their password asks an admin, who sets a new one with `PATCH /api/users/{id}/` and a `password` field. That also signs the user out of every session. Signed-in users change their own password with `POST /api/auth/password/change/`.

## Tech stack

Python 3.12, Django, Django REST Framework, SimpleJWT, django-filter, drf-spectacular, Pillow, filetype, django-storages with boto3, Celery, Redis, PostgreSQL, MinIO (local S3), Docker, pytest. Redis is Django's cache, which holds the throttle counters, and it is also the Celery broker. Celery has no tasks yet.

## Run locally

You need Docker with Compose.

```bash
cp .env.example .env
docker compose up --build
```

In a second terminal:

```bash
docker compose exec web python manage.py migrate
docker compose exec web python manage.py createsuperuser
docker compose exec web python manage.py seed_demo
```

- API: http://localhost:8000
- Swagger UI: http://localhost:8000/api/docs/
- Admin: http://localhost:8000/admin/

`seed_demo` is optional and safe to run more than once. It creates a demo customer, a demo agent and a few tickets with comments.

`createsuperuser` creates a user with the customer role. To act as an agent or admin in the API, change the role in the admin site.

Run the tests (they always use local storage, an in-memory cache and relaxed throttle limits, whatever `.env` says):

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
- Every request writes one `core.access` line. `/health/` is written at `DEBUG` level only, so uptime checks do not flood the log, and responses with a 5xx status are written at `ERROR`. `duration_ms` is the time taken to produce the response, so for streamed downloads it does not include the transfer.
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

The limits live in `REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]` in `config/settings/base.py`. Behind a reverse proxy, set `NUM_PROXIES` to the number of proxies in front of the app, so the real client address is read from `X-Forwarded-For`. With the default `0` the header is ignored, which stops clients from spoofing it to dodge the limits. To reset the counters while testing by hand, run `docker compose exec redis redis-cli FLUSHDB`.

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

## Configuration

Settings are read from environment variables. Copy `.env.example` to `.env` for local development and `.env.prod.example` to `.env.prod` for the production image.

| Variable | Required | Default | Description |
| --- | --- | --- | --- |
| `SECRET_KEY` | Yes | none | Django secret key |
| `JWT_SIGNING_KEY` | Production | `SECRET_KEY` | Key that signs JWTs. Production refuses to start without one that differs from `SECRET_KEY` |
| `DEBUG` | No | `False` | Debug mode. Development settings force it on |
| `ALLOWED_HOSTS` | No | empty | Comma-separated host names |
| `DATABASE_URL` | No | SQLite file | Database connection URL |
| `DJANGO_SETTINGS_MODULE` | No | `config.settings.dev` | `config.settings.prod` in the production image |
| `REDIS_URL` | No | `redis://localhost:6379/0` | Celery broker and result backend, and Django's cache (throttle counters) |
| `NUM_PROXIES` | No | `0` | Number of reverse proxies in front of the app, used to read the client IP for throttling and logging |
| `LOG_LEVEL` | No | `INFO` | Verbosity of the JSON logs (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `CORS_ALLOWED_ORIGINS` | No | empty | Comma-separated origins allowed to call the API |
| `CSRF_TRUSTED_ORIGINS` | No | empty | Production only. Comma-separated trusted origins |
| `SECURE_SSL_REDIRECT` | No | `true` | Production only. Redirect HTTP to HTTPS (`/health/` is exempt). Set `false` when you reach the container over plain HTTP without a proxy |
| `SECURE_HSTS_SECONDS` | No | `31536000` | Production only. Lifetime of the HSTS header. Once a browser has seen it over HTTPS it insists on HTTPS for that host for this long |
| `RUN_MIGRATIONS_ON_START` | No | `false` | Run migrations when the production container starts |
| `WEB_CONCURRENCY` | No | gunicorn default | Number of gunicorn workers |
| `PORT` | No | `8000` | Port gunicorn listens on |
| `STORAGE_BACKEND` | No | `local` | `local` for disk or `s3` for an S3-compatible bucket |
| `DOWNLOAD_URL_TTL_SECONDS` | No | `300` | Lifetime of signed download URLs |
| `S3_BUCKET_NAME` | With `s3` | none | Bucket that holds attachments and avatars |
| `S3_ACCESS_KEY` | With `s3` | none | Access key for the bucket |
| `S3_SECRET_KEY` | With `s3` | none | Secret key for the bucket |
| `S3_ENDPOINT_URL` | No | AWS | S3 endpoint the server uses, for example `http://minio:9000` |
| `S3_PUBLIC_ENDPOINT_URL` | No | `S3_ENDPOINT_URL` | Endpoint embedded in signed URLs when clients reach the bucket on another address |
| `S3_REGION_NAME` | No | `us-east-1` | Bucket region |

## Production image

Every push and pull request runs linting, the test suite and `check --deploy` on GitHub Actions. The project is run locally with Docker Compose and is not deployed anywhere.

`Dockerfile.prod` builds the production image, which runs gunicorn with `config.settings.prod` as a non-root user. Gunicorn's own access log is switched off, because the app writes a JSON access line with the request ID for every request (see Logging). `.env.prod.example` lists everything that image needs: a PostgreSQL `DATABASE_URL`, `REDIS_URL`, a `JWT_SIGNING_KEY` that differs from `SECRET_KEY`, `STORAGE_BACKEND=s3` with the MinIO settings, and the host and origin lists. Migrations run when the container starts if `RUN_MIGRATIONS_ON_START=true`.

## License

MIT. See [LICENSE](LICENSE).
