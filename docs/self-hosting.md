# Self-hosting

Every push and pull request runs linting, the test suite and `check --deploy`
on GitHub Actions. Every merge to `main` also builds both Docker images, and a
smoke test brings up the production stack with throwaway secrets and checks
`/health/` and `/ready/` through the reverse proxy. The project is not deployed
anywhere by the maintainers.

## Quick start

On a host with Docker and Compose, ports 80 and 443 open and a DNS record
pointing `DOMAIN` at it:

```bash
git clone <repository> ticketing-backend
cd ticketing-backend
sh scripts/bootstrap.sh prod
```

The script:

1. Checks that Docker, Compose and the Docker daemon are available.
2. Writes `.env` from the production section of `.env.example`.
3. Generates `SECRET_KEY`, `JWT_SIGNING_KEY`, `METRICS_TOKEN` and the database
   password with `openssl rand -hex 32` (64 characters, so they pass the
   production secret checks) and builds `DATABASE_URL` from the database values.
4. Asks for the public domain and an optional `/admin/` IP allowlist, and sets
   `COMPOSE_FILE` to the production files.
5. Builds and starts the stack.
6. Optionally creates the first admin.

It never overwrites an existing `.env`; to start over, move the file away first.
The first request to the domain makes Caddy obtain the certificate, so the DNS
record must already resolve.

## How the files fit together

- `docker-compose.yml` is the shared base: `db`, `redis`, `migrate`, `web`,
  `worker` and `beat`, with the same service names in every environment.
- `docker-compose.dev.yml` adds the dev differences: the `dev` image target, the
  source bind mount, `runserver`, published loopback ports, MinIO and Prometheus.
- `docker-compose.prod.yml` adds the production differences: the `prod` image
  target, Daphne, the web healthcheck, restart policies, volumes, the `caddy`
  service and the values derived from `DOMAIN`.
- `.env` is the single env file on each machine. Its `COMPOSE_FILE` line picks
  the override, and Compose reads the same file for variable interpolation and
  `env_file`, so plain `docker compose` commands target the right stack.

`.env.example` has a development section and a production section; see
[Configuration](configuration.md#the-env-file).

## Production image

The `prod` target of the multi-stage `Dockerfile` installs runtime dependencies
into a virtualenv, runs `collectstatic` at build time and drops to a non-root
user. It runs Daphne (ASGI), so one process serves both HTTP and WebSocket.
Daphne's access log is disabled because the app writes its own JSON access line;
see [Operations](operations.md#logging).

`PYTHON_IMAGE` and `PIP_INDEX_URL` can point the build at mirrors that work from
inside Iran. Both default to upstream.

The app services share one image tag. Build first, then start, because building
them in parallel inside `up --build` can fail with "image already exists":

```bash
docker compose build
docker compose up -d
```

`make up` does the same.

## Compose stack

- `web`: Daphne.
- `worker` and `beat`: Celery.
- `migrate`: a one-shot service that runs `migrate` and must finish before `web`,
  `worker` and `beat` start. Migrations are not part of the entrypoint.
- `caddy`: the reverse proxy and the only service that publishes ports.
- PostgreSQL and Redis.

## Reverse proxy

The production stack includes a `caddy` service configured by `Caddyfile`. Set
`DOMAIN` in `.env`; Caddy gets and renews the certificate, redirects HTTP to
HTTPS and proxies WebSocket upgrades to `web:8000`. It caps request bodies at
11 MiB (the upload limit), answers `/metrics/` with 404 and allows `/admin/` only
from `ADMIN_ALLOWED_IPS` (space-separated IPs or CIDRs; by default nobody outside
the host itself). The production stack publishes nothing but Caddy's ports 80
and 443, plus 443/udp for HTTP/3. `web` is only reachable inside the Compose
network.

From `DOMAIN` the production Compose file derives `ALLOWED_HOSTS` (the domain),
`CSRF_TRUSTED_ORIGINS` (`https://DOMAIN`) and `CORS_ALLOWED_ORIGINS`
(`https://DOMAIN`, overridable in `.env` when the frontend lives elsewhere). The
production section of `.env.example` sets `NUM_PROXIES=1` and
`SECURE_SSL_REDIRECT=True`.

If you use a different proxy instead:

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
  site's `allowed_origins` for the real host names, and publish the `web` port
  to the proxy yourself.

The development stack publishes PostgreSQL, Redis, MinIO, Prometheus and the app
on `127.0.0.1` only.

## Updating

```bash
git pull
docker compose build
docker compose up -d
```

The `migrate` service runs pending migrations before the app services restart.

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
