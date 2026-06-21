#!/usr/bin/env python3
"""Local-only HTTP server that lets the dashboard's Refresh button trigger
run_sync.sh without going through GitHub Actions.

Binds to 127.0.0.1 only and rejects any request whose client address isn't
loopback, so it's not reachable from other devices on the network.
"""

import json
import subprocess
import sys
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOST = "127.0.0.1"
PORT = 5050
PROJECT_DIR = Path("/Users/davidjesse/running-dashboard")
RUN_SYNC = PROJECT_DIR / "run_sync.sh"
LOG_FILE = Path.home() / "running-dashboard-sync.log"
SYNC_TIMEOUT_SECONDS = 300

LOOPBACK_ADDRESSES = {"127.0.0.1", "::1"}


def log(message: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with LOG_FILE.open("a") as f:
        f.write(f"[{timestamp}] {message}\n")


class SyncHandler(BaseHTTPRequestHandler):
    server_version = "RunningDashboardSyncServer/1.0"

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _reject_non_loopback(self) -> bool:
        if self.client_address[0] not in LOOPBACK_ADDRESSES:
            log(f"REJECTED non-loopback request from {self.client_address[0]}")
            self._send_json(403, {"success": False, "message": "Forbidden: localhost only"})
            return True
        return False

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_POST(self):
        if self._reject_non_loopback():
            return

        if self.path != "/sync":
            self._send_json(404, {"success": False, "message": "Not found"})
            return

        log(f"Refresh button triggered local sync (request from {self.client_address[0]})")

        try:
            result = subprocess.run(
                ["/bin/bash", str(RUN_SYNC)],
                cwd=str(PROJECT_DIR),
                capture_output=True,
                text=True,
                timeout=SYNC_TIMEOUT_SECONDS,
            )
            success = result.returncode == 0
            log(f"Local sync trigger finished: {'success' if success else 'FAILED'} (exit {result.returncode})")
            self._send_json(200 if success else 500, {
                "success": success,
                "message": "Sync completed" if success else f"run_sync.sh exited with code {result.returncode}",
            })
        except subprocess.TimeoutExpired:
            log(f"Local sync trigger TIMED OUT after {SYNC_TIMEOUT_SECONDS}s")
            self._send_json(500, {"success": False, "message": "Sync timed out"})
        except Exception as exc:
            log(f"Local sync trigger ERROR: {exc}")
            self._send_json(500, {"success": False, "message": str(exc)})

    def log_message(self, format, *args):
        # Suppress default stderr access logging; trigger logging happens above.
        pass


def main():
    server = ThreadingHTTPServer((HOST, PORT), SyncHandler)
    print(f"sync_server.py listening on http://{HOST}:{PORT} (POST /sync)")
    log(f"sync_server.py started, listening on {HOST}:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        log("sync_server.py stopped")
        server.server_close()


if __name__ == "__main__":
    sys.exit(main())
