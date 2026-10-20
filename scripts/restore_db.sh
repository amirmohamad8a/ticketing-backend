#!/bin/sh
set -eu

COMPOSE="${COMPOSE:-docker compose}"
DB_SERVICE="${DB_SERVICE:-db}"
POSTGRES_USER="${POSTGRES_USER:-ticketing}"
POSTGRES_DB="${POSTGRES_DB:-ticketing}"

if [ "$#" -lt 1 ] || [ "$#" -gt 2 ]; then
    echo "Usage: sh scripts/restore_db.sh <dump-file> [target-database]" >&2
    exit 1
fi

dump="$1"
target_db="${2:-${POSTGRES_DB}_restore}"
echo "Restoring $dump into $target_db with: $COMPOSE"

if [ ! -f "$dump" ]; then
    echo "Dump file not found: $dump" >&2
    exit 1
fi

case "$target_db" in
    ''|*[!A-Za-z0-9_]*)
        echo "The target database name may contain only letters, digits and underscores." >&2
        exit 1
        ;;
esac

if [ "$target_db" = "$POSTGRES_DB" ] && [ "${CONFIRM_RESTORE:-}" != "yes" ]; then
    echo "Refusing to overwrite the live database $POSTGRES_DB." >&2
    echo "Stop the app services and run again with CONFIRM_RESTORE=yes." >&2
    exit 1
fi

$COMPOSE exec -T "$DB_SERVICE" pg_restore --list < "$dump" > /dev/null

$COMPOSE exec -T "$DB_SERVICE" dropdb -U "$POSTGRES_USER" --if-exists --force "$target_db"
$COMPOSE exec -T "$DB_SERVICE" createdb -U "$POSTGRES_USER" "$target_db"
$COMPOSE exec -T "$DB_SERVICE" pg_restore \
    -U "$POSTGRES_USER" \
    -d "$target_db" \
    --no-owner \
    --no-privileges \
    --exit-on-error < "$dump"

echo "Restored $dump into database $target_db. Row counts:"

$COMPOSE exec -T "$DB_SERVICE" psql -U "$POSTGRES_USER" -d "$target_db" -tA -F ' ' -c "
SELECT 'accounts_user', count(*) FROM accounts_user
UNION ALL SELECT 'accounts_userevent', count(*) FROM accounts_userevent
UNION ALL SELECT 'chat_site', count(*) FROM chat_site
UNION ALL SELECT 'chat_visitor', count(*) FROM chat_visitor
UNION ALL SELECT 'tickets_ticket', count(*) FROM tickets_ticket
UNION ALL SELECT 'tickets_ticketevent', count(*) FROM tickets_ticketevent
UNION ALL SELECT 'tickets_comment', count(*) FROM tickets_comment
UNION ALL SELECT 'tickets_attachment', count(*) FROM tickets_attachment
"
