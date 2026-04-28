#!/usr/bin/env python3
import os
import json
import time
from datetime import date, timedelta
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
            result.append({'date': d, 'vo2max': v, 'fitnessAge': g.get('fitnessAge')})
    if result:
        print(f'  vo2max: {len(result)} weekly readings ({result[0]["date"]} → {result[-1]["date"]})')
    else:
        print('  vo2max: 0 readings')
    return result


# ── Resting HR ────────────────────────────────────────────────────────────────

def fetch_rhr():
    """Bulk-fetch daily RHR via userstats endpoint (2 calls for 2025+2026)."""
    username = garth.client.username
    today = date.today().isoformat()
    result = []

    for start, end in [('2025-01-01', '2025-12-31'), ('2026-01-01', today)]:
        try:
            r = garth.connectapi(f'/userstats-service/wellness/daily/{username}',
                                 params={'fromDate': start, 'untilDate': end})
            entries = (r.get('allMetrics', {}).get('metricsMap', {})
                       .get('WELLNESS_RESTING_HEART_RATE', []))
            for e in entries:
                if e.get('value') is not None:
                    result.append({'date': e['calendarDate'], 'rhr': int(e['value'])})
        except Exception as exc:
            print(f'  RHR fetch error ({start}): {exc}')

    result.sort(key=lambda x: x['date'])
    if result:
        print(f'  rhr: {len(result)} daily readings ({result[0]["date"]} → {result[-1]["date"]})')
    else:
        print('  rhr: 0 readings')
    return result


# ── Body Battery ──────────────────────────────────────────────────────────────

def fetch_body_battery():
    """Fetch daily BB peak+drawdown from intraday data.

    The reports/daily endpoint has a ~31-day range limit per request, so we
    fetch month-by-month for 2026 only. 2025 returns 400 (no intraday data).
    peak     = maximum BB level reached during the day
    drawdown = peak minus the minimum level after the peak (daily cost)
    """
    today_d = date.today()
    today   = today_d.isoformat()

    # One request per calendar month in 2026
    import calendar
    ranges = []
    for month in range(1, today_d.month + 1):
        start = f'2026-{month:02d}-01'
        last_day = calendar.monthrange(2026, month)[1]
        end_d = date(2026, month, last_day)
        end   = min(end_d, today_d).isoformat()
        ranges.append((start, end))

    result = []
    skipped = 0
    for start, end in ranges:
        try:
            data = garth.connectapi(
                '/wellness-service/wellness/bodyBattery/reports/daily',
                params={'startDate': start, 'endDate': end},
            )
        except Exception as exc:
            print(f'  BB fetch error ({start}): {exc}')
            continue

        for day in (data or []):
            vals = day.get('bodyBatteryValuesArray') or []
            levels = [v[1] for v in vals if v and v[1] is not None]
            if len(levels) < 2:
                skipped += 1
                continue

            peak = max(levels)
            peak_idx = levels.index(peak)
            after_peak = levels[peak_idx:]
            drawdown = peak - min(after_peak)

            result.append({'date': day['date'], 'peak': peak, 'drawdown': drawdown})

    result.sort(key=lambda x: x['date'])
    print(f'  bodyBattery: {len(result)} days with intraday data'
          + (f' ({skipped} skipped — null intraday levels)' if skipped else ''))
    return result


# ── Training load / status ───────────────────────────────────────────────────

_STATUS_MAP = {
    0: 'Unknown', 1: 'Peaking', 2: 'Productive',
    3: 'Maintaining', 4: 'Maintaining', 5: 'Recovery',
    6: 'Unproductive', 7: 'Overreaching',
}
_TREND_MAP = {1: 'Improving', 2: 'Stable', 3: 'Declining'}


def fetch_training_load():
    """Poll trainingstatus/aggregated for every Monday 2025-01-06 → today.
    ~69 sequential calls; no sleep needed as data endpoints are not rate-limited.
    """
    today   = date.today()
    result  = []
    errors  = []

    d = date(2025, 1, 6)           # first Monday of 2025
    while d <= today:
        ds = d.isoformat()
        try:
            r = garth.connectapi(
                f'/metrics-service/metrics/trainingstatus/aggregated/{ds}'
            )
            load_data = (
                (r.get('mostRecentTrainingStatus') or {})
                .get('latestTrainingStatusData') or {}
            )
            if not load_data:
                errors.append(ds)
                d += timedelta(weeks=1)
                continue
            entry = list(load_data.values())[0]
            result.append({
                'date':        entry.get('calendarDate', ds),
                'load':        entry.get('weeklyTrainingLoad'),
                'tunnelMin':   entry.get('loadTunnelMin'),
                'tunnelMax':   entry.get('loadTunnelMax'),
                'status':      _STATUS_MAP.get(entry.get('trainingStatus'), 'Unknown'),
                'fitnessTrend': _TREND_MAP.get(entry.get('fitnessTrend'), 'Stable'),
            })
        except Exception as exc:
            errors.append(ds)
        d += timedelta(weeks=1)

    print(f'  trainingLoad: {len(result)} weekly records'
          + (f', {len(errors)} errors ({errors[:3]})' if errors else ''))
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
    print(f'  racePredictions: {preds}')
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

    result['vo2max']          = fetch_vo2max()
    result['rhr']             = fetch_rhr()
    result['bodyBattery']     = fetch_body_battery()
    result['trainingLoad']    = fetch_training_load()
    result['racePredictions'] = fetch_race_predictions()

    with open('runs_data.json', 'w') as f:
        json.dump(result, f, indent=2)

    run_total = sum(len(result[y]) for y in ['2025', '2026'])
    print(f'\nSaved to runs_data.json:')
    print(f'  runs:        {run_total}  ({len(result["2026"])} in 2026, {len(result["2025"])} in 2025)')
    print(f'  vo2max:      {len(result["vo2max"])} weekly readings')
    print(f'  rhr:         {len(result["rhr"])} daily readings')
    print(f'  bodyBattery:  {len(result["bodyBattery"])} daily readings')
    print(f'  trainingLoad: {len(result["trainingLoad"])} weekly readings')
    print(f'  racePreds:    {result["racePredictions"]}')


if __name__ == '__main__':
    main()
