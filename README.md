# Running Dashboard

A self-updating running dashboard powered by Garmin Connect data, built with Python and GitHub Actions.

## How it works

1. **`sync_garmin.py`** — authenticates with Garmin Connect, downloads all running activities for 2025 and 2026, and writes `runs_data.json`.
2. **`build_dashboard.py`** — reads `runs_data.json` and injects it into `template.html`, producing `index.html`.
3. **GitHub Actions** runs both scripts daily at 6 AM Chicago time and commits the updated `index.html` back to the repo.

## Setup

### 1. Create the repository

```bash
git init
git remote add origin https://github.com/YOUR_USERNAME/running-dashboard.git
git add .
git commit -m "Initial commit"
git push -u origin main
```

### 2. Add GitHub Secrets

Go to **Settings → Secrets and variables → Actions** and create two repository secrets:

| Secret name       | Value                        |
|-------------------|------------------------------|
| `GARMIN_EMAIL`    | Your Garmin Connect email    |
| `GARMIN_PASSWORD` | Your Garmin Connect password |

### 3. Enable GitHub Pages (optional)

To serve `index.html` as a public website:

1. Go to **Settings → Pages**
2. Set source to **Deploy from a branch**
3. Select branch `main`, folder `/ (root)`
4. Save — your dashboard will be live at `https://YOUR_USERNAME.github.io/running-dashboard/`

### 4. Trigger a manual sync

Go to **Actions → Sync Garmin & Deploy Dashboard → Run workflow** to run immediately without waiting for the daily schedule.

Or, if you're viewing the dashboard locally on this Mac, just click **Refresh** in the dashboard header — see below.

## Local Refresh button (no GitHub Actions round-trip)

When you view `index.html` on the same Mac that runs the sync, clicking **Refresh**
in the header triggers `run_sync.sh` directly instead of opening GitHub Actions:

1. The button POSTs to `http://localhost:5050/sync`.
2. While waiting, the button shows **Syncing...**.
3. On success: **Synced! Refresh the page to see updates**, then the page
   reloads automatically after 3 seconds.
4. On failure (e.g. the local sync server isn't running): **Local sync server
   not running — opening GitHub Actions instead**, and the GitHub Actions
   page opens in a new tab — the same fallback behavior as before.

This only works when the dashboard is opened from the same Mac that's running
the sync server (`localhost`). If you open the dashboard from your phone or
another device, the local POST will fail (nothing is listening on
`localhost:5050` there) and it'll fall back to the GitHub Actions link.

### Setting up the local sync server

A small local server (`sync_server.py`) listens on `127.0.0.1:5050` and only
accepts requests from localhost. `POST /sync` runs `run_sync.sh` as a
subprocess and returns `{"success": true/false, "message": ...}`. Every
trigger is logged to `~/running-dashboard-sync.log`, the same log `run_sync.sh`
already writes to.

Install it once as a launchd agent so it's always running in the background,
starting automatically on login:

```bash
./install_sync_server.sh
```

Useful commands:

```bash
# Check it's running
launchctl list | grep sync-server

# Test it manually (runs a real sync!)
curl -X POST http://localhost:5050/sync

# Restart it
launchctl kickstart -k gui/$(id -u)/com.davidjesse.sync-server

# Uninstall
launchctl unload ~/Library/LaunchAgents/com.davidjesse.sync-server.plist
rm ~/Library/LaunchAgents/com.davidjesse.sync-server.plist
```

Logs:
- `~/running-dashboard-sync.log` — sync triggers and `run_sync.sh` output (shared with the daily scheduled sync)
- `~/running-dashboard-sync-server.log` — the server process's own stdout/stderr (startup, crashes)

## Running locally

```bash
# Install dependencies
pip install garth python-dotenv

# Create .env with your credentials
echo "GARMIN_EMAIL=you@example.com" > .env
echo "GARMIN_PASSWORD=yourpassword" >> .env

# Sync data and build dashboard
python sync_garmin.py
python build_dashboard.py

# Open index.html in your browser
open index.html
```

## Customising the template

Edit `template.html` to change the dashboard design. The only required line is:

```js
const RUNS_DATA_PLACEHOLDER = null;
```

`build_dashboard.py` replaces that exact line with the injected data. Everything else in the template is up to you.

## Data format

`runs_data.json` structure:

```json
{
  "2026": [
    {
      "date": "2026-04-25",
      "miles": 5.01,
      "pace": 9.04,
      "hr": 134,
      "title": "Wilmette - Base",
      "soccer": false
    }
  ],
  "2025": [ ... ]
}
```

`pace` is decimal minutes per mile (e.g. `9.04` = 9:02 min/mi).  
`soccer: true` flags activities where avg pace > 14 min/mi — these are soccer sessions recorded as running.

## Files

| File | Purpose |
|------|---------|
| `sync_garmin.py` | Fetch and parse Garmin data |
| `build_dashboard.py` | Inject data into template → index.html |
| `template.html` | Dashboard UI template |
| `index.html` | Built dashboard (auto-generated, committed by CI) |
| `runs_data.json` | Parsed run records (auto-generated, committed by CI) |
| `.github/workflows/sync.yml` | Daily sync workflow |
| `sync_server.py` | Local-only HTTP server backing the dashboard's Refresh button |
| `install_sync_server.sh` | Installs `sync_server.py` as a launchd background service |
| `com.davidjesse.sync-server.plist` | launchd agent definition for the sync server |
