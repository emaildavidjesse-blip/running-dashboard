#!/usr/bin/env python3
import os
import json
import time
from dotenv import load_dotenv
from garminconnect import Garmin

load_dotenv()

TOKEN_DIR = os.path.expanduser('~/.garth')

RUNNING_TYPE_KEYS = {
    'running', 'indoor_running', 'trail_running',
    'treadmill_running', 'virtual_running', 'ultra_run',
    'track_running', 'road_running',
}


def authenticate():
    """Return an authenticated Garmin client.

    Auth order:
      1. GARMIN_TOKENSTORE env var — either a directory path containing
         garth token files, or the base64 string produced by garth.client.dumps()
      2. Cached token directory at ~/.garth
      3. Fresh email/password login with 429 backoff, then save tokens
    """
    email = os.getenv('GARMIN_EMAIL')
    password = os.getenv('GARMIN_PASSWORD')
    tokenstore_env = os.getenv('GARMIN_TOKENSTORE', '').strip()

    client = Garmin(email, password)

    # 1. Try GARMIN_TOKENSTORE
    if tokenstore_env:
        try:
            if os.path.isdir(tokenstore_env):
                client.login(tokenstore=tokenstore_env)
            else:
                # Treat as base64-encoded token string from garth.client.dumps()
                client.garth.loads(tokenstore_env)
                client.display_name = client.garth.profile.get('displayName', '')
                client.full_name = client.garth.profile.get('fullName', '')
            print('Authenticated via GARMIN_TOKENSTORE')
            return client
        except Exception as exc:
            print(f'GARMIN_TOKENSTORE auth failed ({exc}), trying cached tokens...')

    # 2. Try cached directory
    if os.path.isdir(TOKEN_DIR):
        try:
            client.login(tokenstore=TOKEN_DIR)
            print(f'Authenticated via cached tokens at {TOKEN_DIR}')
            return client
        except Exception as exc:
            print(f'Cached token auth failed ({exc}), falling back to password...')

    # 3. Fresh login with 429 backoff
    for attempt in range(1, 5):
        try:
            print(f'Logging in as {email} (attempt {attempt})...')
            client.login()
            client.garth.dump(TOKEN_DIR)
            print(f'Login successful; tokens saved to {TOKEN_DIR}')
            return client
        except Exception as exc:
            if '429' in str(exc) and attempt < 4:
                wait = 30 * attempt
                print(f'Rate-limited by Garmin SSO, waiting {wait}s...')
                time.sleep(wait)
            else:
                raise


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


def fetch_year(client, year):
    activities = client.get_activities_by_date(
        f'{year}-01-01', f'{year}-12-31', activitytype='running'
    )
    print(f'  {year}: fetched {len(activities)} activities from Garmin')
    return activities


def main():
    client = authenticate()

    result = {'2026': [], '2025': []}
    seen_ids = set()

    for year in ['2025', '2026']:
        activities = fetch_year(client, year)

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
