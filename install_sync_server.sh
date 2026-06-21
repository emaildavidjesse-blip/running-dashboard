#!/bin/bash
# Install the local sync server as a launchd agent so the dashboard's
# Refresh button can trigger a sync without going to GitHub Actions.
set -euo pipefail

PROJECT_DIR="/Users/davidjesse/running-dashboard"
LABEL="com.davidjesse.sync-server"
PLIST_SRC="$PROJECT_DIR/$LABEL.plist"
PLIST_DST="$HOME/Library/LaunchAgents/$LABEL.plist"

echo "==> Making sync_server.py executable"
chmod +x "$PROJECT_DIR/sync_server.py"

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
    echo "    Try: launchctl list | grep sync-server"
    exit 1
fi

sleep 1
if curl -s -o /dev/null -X OPTIONS http://localhost:5050/sync --max-time 1 2>/dev/null; then
    echo "    OK — server is listening on http://localhost:5050"
else
    echo "    NOTE — couldn't confirm server is listening yet; check the log below if the Refresh button doesn't work."
fi

echo ""
echo "Sync server runs permanently in the background, starting on login."
echo "Trigger log:  ~/running-dashboard-sync.log"
echo "Server log:   ~/running-dashboard-sync-server.log"
echo ""
echo "Useful commands:"
echo "  Check it's running: launchctl list | grep sync-server"
echo "  Restart:            launchctl kickstart -k gui/\$(id -u)/$LABEL"
echo "  Test manually:      curl -X POST http://localhost:5050/sync"
echo ""
echo "To uninstall:"
echo "  launchctl unload ~/Library/LaunchAgents/$LABEL.plist"
echo "  rm ~/Library/LaunchAgents/$LABEL.plist"
