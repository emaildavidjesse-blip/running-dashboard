#!/bin/bash
# Daily Garmin dashboard sync — run by launchd, safe to run manually too.

PROJECT_DIR="/Users/davidjesse/running-dashboard"
PYTHON="/usr/bin/python3"
LOG_FILE="$HOME/running-dashboard-sync.log"

# Redirect all output (including from Python subprocesses) to the log file.
exec >> "$LOG_FILE" 2>&1

log()  { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }
fail() {
    log "ERROR: $*"
    osascript -e "display notification \"$* — see ~/running-dashboard-sync.log\" \
        with title \"Garmin Sync Failed\" sound name \"Basso\""
    exit 1
}

log "========================================"
log "Sync started"

cd "$PROJECT_DIR" || fail "Could not cd to $PROJECT_DIR"

log "--- sync_garmin.py ---"
"$PYTHON" sync_garmin.py || fail "sync_garmin.py exited non-zero"

log "--- build_dashboard.py ---"
"$PYTHON" build_dashboard.py || fail "build_dashboard.py exited non-zero"

log "--- git commit & push ---"
git add index.html runs_data.json

if git diff --cached --quiet; then
    log "No changes — nothing to commit"
else
    git -c user.name="local-sync" \
        -c user.email="davidjesse@local" \
        commit -m "chore: sync Garmin data $(date '+%Y-%m-%d')" \
        || fail "git commit failed"
    git push || fail "git push failed"
    log "Pushed to GitHub"
fi

log "Sync complete"
