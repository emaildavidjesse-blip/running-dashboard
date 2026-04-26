#!/usr/bin/env python3
import os
import json
import time
from dotenv import load_dotenv
import garth

load_dotenv()

RUNNING_TYPE_KEYS = {
    'running', 'indoor_running', 'trail_running',
    'treadmill_running', 'virtual_running', 'ultra_run',
    'track_running', 'road_running',
}

def pace_spm_to_decimal(seconds_per_meter):
    """Convert seconds/meter to decimal min/mile."""
    if not seconds_per_meter or seconds_per_meter <= 0:
        return None
    return round(seconds_per_meter * 1609.344 / 60, 2)

def speed_to_pace(speed_ms):
    """Convert m/s to decimal min/mile."""
    if not speed_ms or speed_ms <= 0:
        return None
    return round((1609.344 / speed_ms) / 60, 2)

def fetch_activities_for_year(year):
    start = 0
    limit = 100
    all_activities = []

    while True:
        result = garth.connectapi(
            '/activitylist-service/activities/search/activities',
            params={
                'startDate': f'{year}-01-01',
                'endDate': f'{year}-12-31',
                'start': start,
                'limit': limit,
            },
        )
        if not result:
            break
        all_activities.extend(result)
        if len(result) < limit:
            break
        start += limit

    return all_activities

def parse_activity(act):
    type_key = (act.get('activityType') or {}).get('typeKey', '').lower()
    if type_key not in RUNNING_TYPE_KEYS:
        return None

    start_time = act.get('startTimeLocal', '')
    date = start_time[:10] if start_time else None

    dist_m = act.get('distance') or 0
    miles = round(dist_m / 1609.344, 2)

    # avgPace is seconds/meter when present; fall back to averageSpeed (m/s)
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

TOKEN_DIR = os.path.expanduser('~/.garth')

def authenticate():
    email = os.getenv('GARMIN_EMAIL')
    password = os.getenv('GARMIN_PASSWORD')

    try:
        garth.resume(TOKEN_DIR)
        print('Resumed session from cached tokens')
        return
    except Exception:
        pass

    for attempt in range(1, 5):
        try:
            print(f'Logging in as {email} (attempt {attempt})...')
            garth.login(email, password)
            garth.save(TOKEN_DIR)
            print('Login successful, tokens saved')
            return
        except Exception as exc:
            if '429' in str(exc) and attempt < 4:
                wait = 30 * attempt
                print(f'Rate-limited by Garmin SSO, waiting {wait}s...')
                time.sleep(wait)
            else:
                raise

def main():
    authenticate()

    result = {'2026': [], '2025': []}
    seen_ids = set()

    for year in ['2025', '2026']:
        activities = fetch_activities_for_year(year)
        print(f'  {year}: fetched {len(activities)} total activities')

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
        print(f'  {year}: {len(runs)} running activities')

    with open('runs_data.json', 'w') as f:
        json.dump(result, f, indent=2)

    total = sum(len(v) for v in result.values())
    print(f'\nSaved {total} runs to runs_data.json')

    # Preview first few runs from most recent year
    for year in ['2026', '2025']:
        runs = result[year]
        if runs:
            print(f'\nFirst 5 runs from {year}:')
            for r in runs[:5]:
                soccer_tag = ' [SOCCER]' if r['soccer'] else ''
                print(f"  {r['date']}  {r['miles']:.2f} mi  pace {r['pace']}  HR {r['hr']}  {r['title']}{soccer_tag}")
            break

if __name__ == '__main__':
    main()
