#!/usr/bin/env python3
import os
import json
import time
from datetime import date
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
    email = os.getenv('GARMIN_EMAIL')
    password = os.getenv('GARMIN_PASSWORD')
    tokenstore_b64 = os.getenv('GARMIN_TOKENSTORE', '').strip()

    if tokenstore_b64:
        try:
            garth.client.loads(tokenstore_b64)
            print('Authenticated via GARMIN_TOKENSTORE (no SSO)')
            return
        except Exception as exc:
            print(f'GARMIN_TOKENSTORE load failed: {exc}')

    if os.path.isdir(TOKEN_DIR):
        try:
            garth.resume(TOKEN_DIR)
            print(f'Authenticated via cached tokens at {TOKEN_DIR}')
            return
        except Exception as exc:
            print(f'Cached token load failed: {exc}')

    for attempt in range(1, 5):
        try:
            print(f'Logging in as {email} (attempt {attempt})...')
            garth.login(email, password)
            garth.save(TOKEN_DIR)
            print(f'Login successful; tokens saved to {TOKEN_DIR}')
            return
        except Exception as exc:
            if '429' in str(exc) and attempt < 4:
                wait = 30 * attempt
                print(f'Rate-limited, waiting {wait}s...')
                time.sleep(wait)
            else:
                raise


# ── Activities ────────────────────────────────────────────────────────────────

def get_activities_by_date(start_date, end_date):
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
    date_str = start_time[:10] if start_time else None

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
        'date': date_str,
        'miles': miles,
        'pace': pace,
        'hr': hr,
        'title': title,
        'soccer': soccer,
    }


# ── VO2 Max ───────────────────────────────────────────────────────────────────

def fetch_vo2max():
    today = date.today().isoformat()
    data = garth.connectapi(
        f'/metrics-service/metrics/maxmet/weekly/2025-01-01/{today}'
    )
    result = []
    for entry in (data or []):
        g = entry.get('generic') or {}
        d = g.get('calendarDate')
        v = g.get('vo2MaxPreciseValue')
        if d and v is not None:
            result.append({
                'date': d,
                'vo2max': v,
                'fitnessAge': g.get('fitnessAge'),
            })
    print(f'  vo2max: {len(result)} weekly readings '
          f'({result[0]["date"]} → {result[-1]["date"]})')
    return result


# ── Race predictions ──────────────────────────────────────────────────────────

def _secs_to_time(total_seconds):
    if not total_seconds:
        return None
    s = int(total_seconds)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f'{h}:{m:02d}:{sec:02d}' if h else f'{m}:{sec:02d}'


def fetch_race_predictions():
    username = garth.client.username
    data = garth.connectapi(
        f'/metrics-service/metrics/racepredictions/latest/{username}'
    )
    if not data:
        return {}
    preds = {
        '5k':       _secs_to_time(data.get('time5K')),
        '10k':      _secs_to_time(data.get('time10K')),
        'half':     _secs_to_time(data.get('timeHalfMarathon')),
        'marathon': _secs_to_time(data.get('timeMarathon')),
    }
    print(f'  race predictions: {preds}')
    return preds


# ── Main ──────────────────────────────────────────────────────────────────────

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

    result['vo2max'] = fetch_vo2max()
    result['racePredictions'] = fetch_race_predictions()

    with open('runs_data.json', 'w') as f:
        json.dump(result, f, indent=2)

    run_total = sum(len(result[y]) for y in ['2025', '2026'])
    print(f'\nSaved {run_total} runs + {len(result["vo2max"])} VO2max readings to runs_data.json')

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
