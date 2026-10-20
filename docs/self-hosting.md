# Self-hosting

Every push and pull request runs linting, the test suite and `check --deploy`
on GitHub Actions. Every merge to `main` also builds both Docker images as a
check. The project is run locally with Docker Compose and is not deployed
anywhere by the maintainers.

## Production image

The `prod` target of the multi-stage `Dockerfile` (the `dev` target is the
development image) installs runtime dependencies into
a virtualenv, runs `collectstatic` at build time and drops to a non-root user.
It runs Daphne (ASGI), so one process serves both HTTP and WebSocket. Daphne's
access log is disabled because the app writes its own JSON access line; see
[Operations](operations.md#logging).

`PYTHON_IMAGE` and `PIP_INDEX_URL` can point the build at mirrors that work from
inside Iran. Both default to upstream.

## Compose stack

`docker-compose.yml` plus the `docker-compose.prod.yml` override runs:

- `web`: Daphne.
- `worker` and `beat`: Celery.
- `migrate`: a one-shot service that runs before the app services.
- PostgreSQL and Redis.

Migrations are a separate service, not part of the entrypoint.
The production section of `.env.example` lists everything the stack needs. Copy
the file to `.env`, delete the development section and uncomment the production
one; its `COMPOSE_FILE` line selects the prod override, so plain `docker compose`
commands target the right stack.

## Reverse proxy

- Cap the request body at the proxy first (`client_max_body_size` in nginx or
  the equivalent in Caddy). The ASGI layer enforces `MAX_REQUEST_BODY_BYTES`
  (64 KB by default) on normal routes and `MAX_UPLOAD_BODY_BYTES` (11 MB) on
  upload routes, and answers `413` before Django spools an oversized or chunked
  body to disk. Set the proxy upload cap to `MAX_UPLOAD_BODY_BYTES` and keep a
  smaller cap elsewhere.
- Do not expose `/admin/` to the public internet. Put it behind an allowlist or
  a VPN. Django admin logins are not covered by DRF throttles; the per-IP
  limiter (`ADMIN_LOGIN_MAX_ATTEMPTS` per `ADMIN_LOGIN_WINDOW_SECONDS`, 10 per
  300 by default) is a safety net, not a substitute for keeping the route
  private.
- Terminate TLS at the proxy and forward `X-Forwarded-Proto: https`.
- Proxy WebSocket upgrades for `/ws/` and `/ws/presence/`, including `wss://`.
- Set `NUM_PROXIES` to the number of proxies in front of the app. Production
  refuses to start without it. Use `ALLOW_ZERO_PROXIES=true` only for a
  deliberate direct-access deployment.
- Set `ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`, `CSRF_TRUSTED_ORIGINS` and each
  site's `allowed_origins` for the real host names.

The development stack (`docker-compose.yml` plus `docker-compose.dev.yml`) publishes PostgreSQL, Redis, MinIO,
Prometheus and the app on `127.0.0.1` only. The production Compose file defaults
`WEB_PORT` to `127.0.0.1:8000`, so a reverse proxy on the same host is the only
way in.

## Backups and restore

The scripts under `scripts/` run plain `docker compose`, which uses the
`COMPOSE_FILE` from `.env`. Export `COMPOSE` to target a different stack:

```bash
COMPOSE="docker compose -f docker-compose.yml -f docker-compose.dev.yml" sh scripts/backup_db.sh
```

- `backup_db.sh` prints the Compose command and database it targets.
- `backup_media.sh` prints the volume it archives.
- `restore_db.sh` and `restore_media.sh` restore those archives.

The frontend is a separate application; this repository is the API only.
