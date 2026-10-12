# Ticketing Backend

A support-ticketing REST API built with Django and Django REST Framework. Customers open tickets, agents work them through a validated status workflow, and every change is recorded in an append-only audit log.

## Features

- Three roles (customer, agent, admin) on a custom user model
- Self-service registration at `POST /api/auth/register/`: it always creates a customer (a role can never be chosen), checks the password with Django's validators and accepts an optional unique Iranian mobile number, which is normalized to `09XXXXXXXXX`
- Profile at `GET/PATCH /api/auth/me/`: first and last name, an optional phone number and an optional avatar (PNG, JPEG or WebP up to 2 MB, verified as a real image and stored under a random name). The username and role cannot be changed there. The response carries an `avatar_download_url` instead of a file URL
- Password change at `POST /api/auth/password/change/`: it needs the current password, applies Django's validators, revokes every refresh token of the user and returns a fresh token pair for the session that made the change
- User management for admins at `/api/users/`: list with `role` and `is_active` filters, create users (agents by default), change roles, deactivate and reactivate accounts and reset passwords. Every change writes a row to an append-only `UserEvent` log, deactivation and password resets revoke the user's sessions, and an admin cannot demote or deactivate themselves or reset their own password there
- Agents list for assignment dropdowns at `GET /api/agents/`: the id, display name and role of every active agent and admin, readable by agents and admins only. It is not paginated and exposes no usernames, phone numbers or other account details
- JWT authentication with short-lived access tokens, rotating refresh tokens, a blacklist and logout
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

## Forgotten passwords

There is no password reset by email. Outbound email is out of scope for this project, so a user who forgets their password asks an admin, who sets a new one with `PATCH /api/users/{id}/` and a `password` field. That also signs the user out of every session. Signed-in users change their own password with `POST /api/auth/password/change/`.

## Tech stack

Python 3.12, Django, Django REST Framework, SimpleJWT, django-filter, drf-spectacular, Pillow, filetype, django-storages with boto3, Celery, Redis, PostgreSQL, MinIO (local S3), Docker, pytest. Celery and Redis are configured for background jobs and have no tasks yet.

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

Run the tests (they always use local storage, whatever `.env` says):

```bash
docker compose exec -e STORAGE_BACKEND=local web pytest --cov
```

### Storing files in MinIO

Files go to local disk by default. To test the S3 path without a provider account, set `STORAGE_BACKEND=s3` in `.env` and start the stack with the `s3` profile:

```bash
docker compose --profile s3 up --build
```

This starts MinIO and creates a private bucket named after `S3_BUCKET_NAME`. The MinIO console is at http://localhost:9001 and signed download URLs are generated against `S3_PUBLIC_ENDPOINT_URL` (`http://localhost:9000`), so your browser can reach them. The containers talk to MinIO at `http://minio:9000`.

## Configuration

Settings are read from environment variables. Copy `.env.example` to `.env` for local development and `.env.prod.example` to `.env.prod` for the production image.

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

Every push and pull request runs linting and the test suite on GitHub Actions. The project is run locally with Docker Compose and is not deployed anywhere.

`Dockerfile.prod` builds the production image, which runs gunicorn with `config.settings.prod` as a non-root user. `.env.prod.example` lists everything that image needs: a PostgreSQL `DATABASE_URL`, `REDIS_URL`, `STORAGE_BACKEND=s3` with the MinIO settings, and the host and origin lists. Migrations run when the container starts if `RUN_MIGRATIONS_ON_START=true`.

## License

MIT. See [LICENSE](LICENSE).
