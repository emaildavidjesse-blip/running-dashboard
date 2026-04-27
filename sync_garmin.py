#!/usr/bin/env python3
import os
import json
import time
from dotenv import load_dotenv
import garth

load_dotenv()

TOKEN_DIR = os.path.expanduser('~/.garth')
ACTIVITIES_URL = '/activitylist-service/activities/search/activities'

RUNNING_TYPE_KEYS = {
    'running', 'indoor_running', 'trail_running',
    'treadmill_running', 'virtual_running', 'ultra_run',
    'track_running', 'road_running',
}


def authenticate():
    """Load tokens into garth.client — the global garth session.

    Auth order:
      1. GARMIN_TOKENSTORE env var — base64 string from export_tokens.py.
         garth.client.loads() configures tokens directly; zero HTTP calls.
      2. Cached directory at ~/.garth — same, no SSO.
      3. Fresh SSO login with 429 backoff, then caches tokens for next run.
    """
    email = os.getenv('GARMIN_EMAIL')
    password = os.getenv('GARMIN_PASSWORD')
    tokenstore_b64 = os.getenv('GARMIN_TOKENSTORE', '').strip()

    # 1. Base64 token string
    if tokenstore_b64:
        try:
            garth.client.loads(tokenstore_b64)
            print('Authenticated via GARMIN_TOKENSTORE (no SSO)')
            return
        except Exception as exc:
            print(f'GARMIN_TOKENSTORE load failed: {exc}')

    # 2. Cached token directory (~/.garth)
    if os.path.isdir(TOKEN_DIR):
        try:
            garth.resume(TOKEN_DIR)   # garth.client.load(TOKEN_DIR)
            print(f'Authenticated via cached tokens at {TOKEN_DIR}')
            return
        except Exception as exc:
            print(f'Cached token load failed: {exc}')

    # 3. Fresh SSO login
    for attempt in range(1, 5):
        try:
            print(f'Logging in as {email} (attempt {attempt})...')
            garth.login(email, password)   # garth.client.login(email, password)
            garth.save(TOKEN_DIR)          # garth.client.dump(TOKEN_DIR)
            print(f'Login successful; tokens saved to {TOKEN_DIR}')
            return
        except Exception as exc:
            if '429' in str(exc) and attempt < 4:
                wait = 30 * attempt
                print(f'Rate-limited, waiting {wait}s...')
                time.sleep(wait)
            else:
                raise


def get_activities_by_date(start_date, end_date):
    """Fetch all running activities between dates, paginating 20 at a time."""
    activities = []
    start = 0
    limit = 20
    while True:
        page = garth.connectapi(ACTIVITIES_URL, params={
            'startDate': start_date,
            'endDate': end_date,
            'start': str(start),
            'limit': str(limit),
            'activityType': 'running',
        })
        if not page:
            break
        activities.extend(page)
        start += limit
    return activities


def pace_spm_to_decimal(seconds_per_meter):
    if not seconds_per_meter or seconds_per_meter <= 0:
        return None
    return round(seconds_per_meter * 1609.344 / 60, 2)


def speed_to_pace(speed_ms):
    if not speed_ms or speed_ms <= 0:
        return None
    return round((1609.344 / speed_ms) / 60, 2)


def parse_activity(act):
    type_key = (act.get('activityType') or {}).get('typeKey', '').lower()
    if type_key not in RUNNING_TYPE_KEYS:
        return None

    start_time = act.get('startTimeLocal', '')
    date = start_time[:10] if start_time else None

    dist_m = act.get('distance') or 0
    miles = round(dist_m / 1609.344, 2)

    avg_pace_raw = act.get('avgPace')
    if avg_pace_raw and avg_pace_raw > 0:
        pace = pace_spm_to_decimal(avg_pace_raw)
    else:
        pace = speed_to_pace(act.get('averageSpeed') or 0)

    hr_raw = act.get('averageHR')
    hr = int(hr_raw) if hr_raw else None

    title = act.get('activityName', '')
    soccer = bool(pace and pace > 14.0)

    return {
        'id': act.get('activityId'),
        'date': date,
        'miles': miles,
        'pace': pace,
        'hr': hr,
        'title': title,
        'soccer': soccer,
    }


def main():
    authenticate()

    result = {'2026': [], '2025': []}
    seen_ids = set()

    for year in ['2025', '2026']:
        activities = get_activities_by_date(f'{year}-01-01', f'{year}-12-31')
        print(f'  {year}: fetched {len(activities)} activities from Garmin')

        runs = []
        for act in activities:
            parsed = parse_activity(act)
            if parsed is None:
                continue
            act_id = parsed.pop('id')
            if act_id in seen_ids:
                continue
            seen_ids.add(act_id)
            runs.append(parsed)

        result[year] = runs
        print(f'  {year}: {len(runs)} running activities kept')

    with open('runs_data.json', 'w') as f:
        json.dump(result, f, indent=2)

    total = sum(len(v) for v in result.values())
    print(f'\nSaved {total} runs to runs_data.json')

    for year in ['2026', '2025']:
        runs = result[year]
        if runs:
            print(f'\nFirst 5 runs from {year}:')
            for r in runs[:5]:
                tag = ' [SOCCER]' if r['soccer'] else ''
                print(f"  {r['date']}  {r['miles']:.2f} mi  pace {r['pace']}  HR {r['hr']}  {r['title']}{tag}")
            break


if __name__ == '__main__':
    main()
