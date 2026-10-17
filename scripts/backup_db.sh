#!/bin/sh
set -eu

COMPOSE="${COMPOSE:-docker compose -f docker-compose.prod.yml}"
DB_SERVICE="${DB_SERVICE:-db}"
POSTGRES_USER="${POSTGRES_USER:-ticketing}"
POSTGRES_DB="${POSTGRES_DB:-ticketing}"
BACKUP_DIR="${BACKUP_DIR:-backups}"
BACKUP_RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"

case "$BACKUP_RETENTION_DAYS" in
    ''|*[!0-9]*)
        echo "BACKUP_RETENTION_DAYS must be a whole number." >&2
        exit 1
        ;;
esac

mkdir -p "$BACKUP_DIR"
echo "Backing up database $POSTGRES_DB from $DB_SERVICE with: $COMPOSE"

stamp="${BACKUP_STAMP:-$(date -u +%Y%m%dT%H%M%SZ)}"
target="$BACKUP_DIR/$POSTGRES_DB-$stamp.dump"
partial="$target.partial"

cleanup() {
    rm -f "$partial"
}
trap cleanup EXIT

$COMPOSE exec -T "$DB_SERVICE" pg_dump \
    -U "$POSTGRES_USER" \
    -d "$POSTGRES_DB" \
    --format=custom \
    --no-owner \
    --no-privileges > "$partial"

if [ ! -s "$partial" ]; then
    echo "The dump is empty, nothing was saved." >&2
    exit 1
fi

$COMPOSE exec -T "$DB_SERVICE" pg_restore --list < "$partial" > /dev/null

mv "$partial" "$target"
echo "Backup written to $target"

if [ "$BACKUP_RETENTION_DAYS" -gt 0 ]; then
    find "$BACKUP_DIR" -maxdepth 1 -type f -name "$POSTGRES_DB-*.dump" \
        -mtime +"$BACKUP_RETENTION_DAYS" \
        -exec echo "Removed old backup" {} \; -delete
fi
