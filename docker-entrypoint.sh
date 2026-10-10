#!/bin/sh
set -e

if [ "${RUN_MIGRATIONS_ON_START:-false}" = "true" ]; then
    python manage.py migrate --noinput
fi

exec "$@"
