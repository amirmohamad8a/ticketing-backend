#!/bin/sh
set -eu

MEDIA_VOLUME="${MEDIA_VOLUME:-ticketing_media_data}"
BACKUP_IMAGE="${BACKUP_IMAGE:-alpine:3.20}"

if [ "$#" -lt 1 ] || [ "$#" -gt 2 ]; then
    echo "Usage: sh scripts/restore_media.sh <archive> [target-volume]" >&2
    exit 1
fi

archive="$1"
target_volume="${2:-${MEDIA_VOLUME}_restore}"

if [ ! -f "$archive" ]; then
    echo "Archive not found: $archive" >&2
    exit 1
fi

case "$target_volume" in
    ''|-*|*[!A-Za-z0-9_.-]*)
        echo "The target volume name may contain only letters, digits, dots, hyphens and underscores." >&2
        exit 1
        ;;
esac

if [ "$target_volume" = "$MEDIA_VOLUME" ] && [ "${CONFIRM_RESTORE:-}" != "yes" ]; then
    echo "Refusing to overwrite the live volume $MEDIA_VOLUME." >&2
    echo "Stop the app services and run again with CONFIRM_RESTORE=yes." >&2
    exit 1
fi

archive_dir="$(cd "$(dirname "$archive")" && pwd)"
archive_name="$(basename "$archive")"

docker run --rm \
    -v "$archive_dir":/in:ro \
    "$BACKUP_IMAGE" \
    tar tzf "/in/$archive_name" > /dev/null

docker volume create "$target_volume" > /dev/null

docker run --rm \
    -v "$target_volume":/data \
    -v "$archive_dir":/in:ro \
    "$BACKUP_IMAGE" \
    sh -c 'find /data -mindepth 1 -delete && tar xzf "/in/$1" -C /data' sh "$archive_name"

echo "Restored $archive into volume $target_volume. File count:"

docker run --rm \
    -v "$target_volume":/data:ro \
    "$BACKUP_IMAGE" \
    sh -c 'find /data -type f | wc -l'
