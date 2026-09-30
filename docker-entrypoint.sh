#!/bin/sh
set -e

if [ "${RUN_MIGRATIONS_ON_START:-false}" = "true" ]; then
    python manage.py migrate --noinput
fi

if [ "${RUN_EMBEDDED_WORKER:-false}" = "true" ]; then
    celery -A config worker --loglevel=info --pool=solo &
fi

exec "$@"
