#!/bin/sh
set -eu

MEDIA_VOLUME="${MEDIA_VOLUME:-ticketing_media_data}"
BACKUP_IMAGE="${BACKUP_IMAGE:-alpine:3.20}"
BACKUP_DIR="${BACKUP_DIR:-backups}"
BACKUP_RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"

case "$BACKUP_RETENTION_DAYS" in
    ''|*[!0-9]*)
        echo "BACKUP_RETENTION_DAYS must be a whole number." >&2
        exit 1
        ;;
esac

if ! docker volume inspect "$MEDIA_VOLUME" > /dev/null 2>&1; then
    echo "Docker volume not found: $MEDIA_VOLUME" >&2
    exit 1
fi

mkdir -p "$BACKUP_DIR"
backup_abs="$(cd "$BACKUP_DIR" && pwd)"

stamp="${BACKUP_STAMP:-$(date -u +%Y%m%dT%H%M%SZ)}"
name="media-$stamp.tgz"
target="$BACKUP_DIR/$name"
partial="$target.partial"

cleanup() {
    rm -f "$partial" || true
}
trap cleanup EXIT

docker run --rm \
    -v "$MEDIA_VOLUME":/data:ro \
    -v "$backup_abs":/out \
    "$BACKUP_IMAGE" \
    tar czf "/out/$name.partial" -C /data .

if [ ! -s "$partial" ]; then
    echo "The archive is empty, nothing was saved." >&2
    exit 1
fi

docker run --rm \
    -v "$backup_abs":/out:ro \
    "$BACKUP_IMAGE" \
    tar tzf "/out/$name.partial" > /dev/null

mv "$partial" "$target"
echo "Backup written to $target"

if [ "$BACKUP_RETENTION_DAYS" -gt 0 ]; then
    find "$BACKUP_DIR" -maxdepth 1 -type f -name "media-*.tgz" \
        -mtime +"$BACKUP_RETENTION_DAYS" \
        -exec echo "Removed old backup" {} \; -delete
fi
