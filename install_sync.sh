#!/bin/bash
# Install the running-dashboard launchd sync agent.
set -euo pipefail

PROJECT_DIR="/Users/davidjesse/running-dashboard"
LABEL="com.davidjesse.running-dashboard"
PLIST_SRC="$PROJECT_DIR/$LABEL.plist"
PLIST_DST="$HOME/Library/LaunchAgents/$LABEL.plist"

echo "==> Making run_sync.sh executable"
chmod +x "$PROJECT_DIR/run_sync.sh"

echo "==> Installing plist to ~/Library/LaunchAgents/"
cp "$PLIST_SRC" "$PLIST_DST"

# Unload first in case a stale copy is already registered.
launchctl unload "$PLIST_DST" 2>/dev/null || true
launchctl load "$PLIST_DST"

echo "==> Verifying"
if launchctl list | grep -q "$LABEL"; then
    echo "    OK — $LABEL is loaded"
else
    echo "    FAIL — job did not appear in launchctl list"
    echo "    Try: launchctl list | grep running-dashboard"
    exit 1
fi

echo ""
echo "Sync runs daily at 6:00 AM (fires on next wake if the Mac was asleep)."
echo "Log: ~/running-dashboard-sync.log"
echo ""
echo "Useful commands:"
echo "  Run now:    launchctl start $LABEL"
echo "  Check log:  tail -f ~/running-dashboard-sync.log"
echo ""
echo "To uninstall:"
echo "  launchctl unload ~/Library/LaunchAgents/$LABEL.plist"
echo "  rm ~/Library/LaunchAgents/$LABEL.plist"
