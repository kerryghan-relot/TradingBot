#!/usr/bin/env bash
# Daily backup of bars.db — a VPS disk failure or a bad config edit
# should not be able to erase the bot's entire trade/indicator history.
#
# Uses sqlite3's ".backup" command (safe to run against a live,
# WAL-mode database — unlike a plain file copy, which can grab a
# torn/inconsistent snapshot while the bot is writing).
#
# Install as a daily cron job (02:00) with:
#   crontab -e
#   0 2 * * * /path/to/lucas-trading/deploy/scripts/backup_db.sh
#
# (setup_vps.sh installs this automatically.)

set -uo pipefail

TRADING_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DB_FILE="$TRADING_DIR/bars.db"
BACKUP_DIR="$TRADING_DIR/backups"
RETENTION_DAYS=30

mkdir -p "$BACKUP_DIR"

if [ ! -f "$DB_FILE" ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S')  bars.db introuvable — rien a sauvegarder"
    exit 0
fi

STAMP="$(date '+%Y%m%d_%H%M%S')"
DEST="$BACKUP_DIR/bars_${STAMP}.db"

sqlite3 "$DB_FILE" ".backup '$DEST'"
gzip "$DEST"

echo "$(date '+%Y-%m-%d %H:%M:%S')  backup ecrit: ${DEST}.gz"

find "$BACKUP_DIR" -name 'bars_*.db.gz' -mtime "+${RETENTION_DAYS}" -delete
