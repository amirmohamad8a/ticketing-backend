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

- `docker-compose.yml` is the shared base: `db`, `redis`, `broker`, `migrate`,
  `web`, `worker` and `beat`, with the same service names in every environment.
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

- `web`: Daphne, two replicas by default (`WEB_REPLICAS`). Each replica is one
  process; Redis carries WebSocket fan-out, so any replica can serve any socket.
- `worker` and `beat`: Celery.
- `migrate`: a one-shot service that runs `migrate` and must finish before `web`,
  `worker` and `beat` start. Migrations are not part of the entrypoint.
- `frontend`: the Next.js web app, built from the `../ticketing-frontend` repository. It talks to `web` over the Compose network.
- `caddy`: the reverse proxy and the only service that publishes ports.
- PostgreSQL, the `redis` service (cache and Channels layer, `volatile-lru`) and
  the `broker` service (Celery, AOF and `noeviction`, with its own volume).

## Reverse proxy

The production stack includes a `caddy` service configured by `Caddyfile`. Set
`DOMAIN` in `.env`; Caddy gets and renews the certificate, redirects HTTP to
HTTPS and serves everything from one domain: `/api/*`, `/ws/*`, `/admin/*` and `/static/*` go to the `web` replicas on port 8000 (WebSocket upgrades included) and every other path goes to `frontend` on port 3000. Caddy
resolves `web` with `dynamic a`, so it picks up replicas as they start and stop. It caps request bodies at
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

`NUM_PROXIES=1` is right for the single-domain layout. Caddy replaces any inbound `X-Forwarded-For` with the peer address, and the frontend server copies that header to Django without adding an entry, so Django reads the real client address from the last entry for direct API calls and for requests through the frontend. After a change to the proxy chain, check that `client_ip` in the `core.access` log lines for `/api/token/` equals the client address and ignores a spoofed `X-Forwarded-For` header sent with the request.

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

The frontend is a separate repository. The production Compose file builds it from `../ticketing-frontend` and needs `FRONTEND_SESSION_SECRET` (at least 32 random characters) in `.env`.
