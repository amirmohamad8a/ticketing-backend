#!/bin/sh
set -eu

BACKUP_STAMP="${BACKUP_STAMP:-$(date -u +%Y%m%dT%H%M%SZ)}"
export BACKUP_STAMP

here="$(cd "$(dirname "$0")" && pwd)"

sh "$here/backup_db.sh"

if [ "${STORAGE_BACKEND:-local}" = "s3" ]; then
    echo "STORAGE_BACKEND is s3, so the media volume is skipped. Enable versioning or replication on the bucket."
else
    sh "$here/backup_media.sh"
fi
