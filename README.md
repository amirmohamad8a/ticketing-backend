# Ticketing Backend

A support-ticketing REST API built with Django and Django REST Framework. Customers open tickets, agents work them through a validated status workflow, and every change is recorded in an append-only audit log.

## Features

- Three roles (customer, agent, admin) on a custom user model
- JWT authentication with short-lived access tokens, rotating refresh tokens, a blacklist and logout
- Role-scoped querysets: a customer only ever sees their own tickets
- Field-level permissions: customers can edit only the title and description of their own open tickets, and status, priority and assignee are staff-only
- Ticket status state machine: illegal transitions return 400 and write nothing
- Append-only audit trail of status and assignee changes, enforced in the model and readable at `/api/tickets/{id}/events/`
- Comments with internal notes that customers never receive
- Attachments with a 10 MB limit and a content-type allowlist (stored on local disk for now; persistent storage is planned)
- Filtering by status, priority and assignee (including `assignee=me`) and cursor pagination
- One error format for every failure: `{"error": {"code", "message", "details"}}`
- OpenAPI schema and Swagger UI
- Database-free `/health/` endpoint for uptime checks
- Automated tests with an 85% coverage threshold, GitHub Actions CI, and Render deploys that wait for CI to pass

## Tech stack

Python 3.12, Django, Django REST Framework, SimpleJWT, django-filter, drf-spectacular, Celery, Redis, PostgreSQL, Docker, pytest. Celery and Redis are configured for background jobs and have no tasks yet. Production runs on Render (web service and Key Value) and Neon (PostgreSQL).

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

Run the tests:

```bash
docker compose exec web pytest --cov
```

## Configuration

Settings are read from environment variables. Copy `.env.example` to `.env` for local use.

| Variable | Required | Default | Description |
| --- | --- | --- | --- |
| `SECRET_KEY` | Yes | none | Django secret key |
| `DEBUG` | No | `False` | Debug mode. Development settings force it on |
| `ALLOWED_HOSTS` | No | empty | Comma-separated host names |
| `DATABASE_URL` | No | SQLite file | Database connection URL |
| `DJANGO_SETTINGS_MODULE` | No | `config.settings.dev` | `config.settings.prod` in the production image |
| `REDIS_URL` | No | `redis://localhost:6379/0` | Celery broker and result backend |
| `CORS_ALLOWED_ORIGINS` | No | empty | Comma-separated origins allowed to call the API |
| `CSRF_TRUSTED_ORIGINS` | No | empty | Production only. Comma-separated trusted origins |
| `RENDER_EXTERNAL_HOSTNAME` | No | empty | Production only. Set by Render and added to allowed hosts |
| `RUN_MIGRATIONS_ON_START` | No | `false` | Run migrations when the production container starts |
| `WEB_CONCURRENCY` | No | gunicorn default | Number of gunicorn workers |
| `PORT` | No | `8000` | Port gunicorn listens on. Set by Render |

## Deployment

Every push and pull request runs linting and the test suite on GitHub Actions. Render redeploys the `main` branch only after those checks pass, and migrations run when the container starts. The service configuration lives in `render.yaml`.

## License

MIT. See [LICENSE](LICENSE).
