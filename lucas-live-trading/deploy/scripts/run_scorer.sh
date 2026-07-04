#!/usr/bin/env bash
# Weekly scorer run — Linux/cron equivalent of run_scorer.ps1.
#
# Re-ranks all candidate symbols and writes the top-X into
# config.json["symbols"].  The running bot hot-reloads the list within
# ~30 s (new symbols subscribed, removed ones liquidated) — no restart.
#
# Install as a weekly cron job (Sundays 18:00) with:
#   crontab -e
#   0 18 * * 0 /path/to/lucas-live-trading/deploy/scripts/run_scorer.sh
#
# (setup_vps.sh installs this automatically.)

set -uo pipefail

LIVE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
REPO_DIR="$(cd "$LIVE_DIR/.." && pwd)"
LOG_FILE="$LIVE_DIR/scorer_task.log"

cd "$LIVE_DIR"

{
    echo "=== Scorer run $(date '+%Y-%m-%d %H:%M:%S') ==="
    "$REPO_DIR/.venv/bin/python" "$LIVE_DIR/scorer.py"
    echo "=== Exit code: $? ==="
} >> "$LOG_FILE" 2>&1
