# Ticketing Backend

A support-ticketing REST API built with Django and Django REST Framework, with a
real-time chat layer. Customers open tickets, website visitors talk to agents
through an embeddable widget, and every change is written to an append-only
audit trail.

The OpenAPI schema in [`schema.yml`](schema.yml) is the source of truth for
routes, request and response bodies, operation ids and permissions. Swagger UI
is served at `/api/docs/` and the JSON schema at `/api/schema/`.

## Features

- Tickets with a status workflow, field-level permissions, soft delete and
  restore, tags, canned replies, CSV export, ratings and a per-participant read
  state with unread counts.
- An embeddable chat widget with visitor tokens, origin checks, conversation
  start/resume, messages, read state, contact details, ratings, attachments and
  signed downloads.
- Real-time WebSocket events for messages, ticket changes and typing, plus an
  agent presence socket and capacity-aware chat routing.
- Offline fallback that turns an unanswered chat into an offline-form ticket and
  lets the visitor leave contact details.
- JWT authentication with rotating refresh tokens, blacklist and immediate
  revocation, plus role-based access for customers, agents and admins.
- Append-only ticket and user audit logs, statistics, and filtering by status,
  priority, assignee, tag, search and overdue state.
- Safe uploads and downloads: magic-byte checks, allowlists, random stored names,
  local or S3-compatible storage and short-lived signed links.
- Operational support: JSON logging with request ids, Redis-backed throttling,
  Prometheus metrics, health checks and production deployment checks.

## Run it

You need Docker with Compose.

```bash
cp .env.example .env
docker compose up --build
```

In a second terminal, migrate the database and seed the demo data:

```bash
make demo
```

Without `make`:

```bash
docker compose exec -T web python manage.py migrate
docker compose exec -T web python manage.py seed_demo
```

- API: http://localhost:8000
- Swagger UI: http://localhost:8000/api/docs/
- Django admin: http://localhost:8000/admin/

`seed_demo` creates a demo customer (`demo_customer`), a demo agent
(`demo_agent`), a chat site and sample conversations. Both accounts use the
password `demo-ticketing-2026`. `make reset-demo` removes the demo data and
seeds a clean state again.

Create a superuser with:

```bash
docker compose exec web python manage.py createsuperuser
```

## Tests

The test settings use local storage, an in-memory cache, channel layer and
Celery broker, and relaxed throttles.

```bash
docker compose exec -e STORAGE_BACKEND=local web pytest --cov
```

Formatting and lint:

```bash
docker compose exec -T web black --check .
docker compose exec -T web isort --check-only .
docker compose exec -T web ruff check .
docker compose exec -T web lint-imports
```

## Documentation

- [API notes](docs/api-notes.md): authentication, resources, ticket workflows,
  messages, ratings, export, stats and audit.
- [Widget](docs/widget.md): the public widget API and conversation lifecycle.
- [Realtime](docs/realtime.md): WebSocket protocol, events, typing and presence.
- [Operations](docs/operations.md): logging, rate limits, metrics and production
  and security checks.
- [Configuration](docs/configuration.md): every environment variable.
- [Self-hosting](docs/self-hosting.md): production image, reverse proxy, backups
  and restore.
- [Architecture](docs/architecture.md): layering and import rules.

## Project layout

| App | Responsibility |
| --- | --- |
| `accounts` | Users, profile, avatars, authentication and the user audit log |
| `tickets` | Tickets, comments, attachments, read state, ratings, tags and export |
| `chat` | Sites, visitors, the widget API, routing, presence and offline fallback |
| `realtime` | ASGI consumers, socket authentication and the realtime HTTP side |
| `core` | Shared infrastructure: errors, logging, metrics, uploads, storage and downloads |
| `config` | Settings, URLs, ASGI routing and Celery |

## License

MIT. See [LICENSE](LICENSE).
