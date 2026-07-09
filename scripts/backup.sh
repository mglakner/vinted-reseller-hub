#!/bin/sh
# Nightly backup of the database + photos. Run from cron:
#   0 3 * * * /path/to/vinted-reseller-hub/scripts/backup.sh
set -eu
cd "$(dirname "$0")/.."
STAMP=$(date +%Y-%m-%d)
mkdir -p backups
sqlite3 data/vintedhub.db ".backup backups/vintedhub-$STAMP.db"
tar czf "backups/media-$STAMP.tar.gz" -C data media
# keep 14 days
find backups -type f -mtime +14 -delete
# optional: sync to cloud storage with rclone (run `rclone config` first)
# rclone copy backups remote:vinted-hub-backup
