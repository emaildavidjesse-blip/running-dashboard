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
