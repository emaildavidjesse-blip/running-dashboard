#!/usr/bin/env python3
import argparse
import os
import sys
import json
import base64
import time
from datetime import date, datetime, timedelta
from dotenv import load_dotenv
import garth
from garth.auth_tokens import OAuth1Token, OAuth2Token

load_dotenv()

TOKEN_DIR = os.path.expanduser('~/.garth')
ACTIVITIES_URL = '/activitylist-service/activities/search/activities'
DATA_FILE = 'runs_data.json'
DEFAULT_START = date(2025, 1, 1)
OVERLAP_DAYS = 5

RUNNING_TYPE_KEYS = {
    'running', 'indoor_running', 'trail_running',
    'treadmill_running', 'virtual_running', 'ultra_run',
    'track_running', 'road_running',
}


def _check_and_arm_oauth2():
    """Verify OAuth2 token expiry and block mid-run refresh attempts.

    Must be called immediately after loading tokens.  Exits with a clear
    message if the token is already expired; prints a warning if it expires
    within 7 days; patches refresh_oauth2() so any accidental call from
    garth internals aborts the run rather than hitting the rate-limited
    exchange endpoint.
    """
    oauth2 = garth.client.oauth2_token
    if not oauth2:
        sys.exit(
            'No OAuth2 token — run export_tokens.py locally and update '
            'GARMIN_TOKENSTORE secret'
        )

    now = time.time()
    expires_str = datetime.fromtimestamp(oauth2.expires_at).strftime('%Y-%m-%d')

    if oauth2.expires_at < now:
        sys.exit(
            f'Token expired on {expires_str} — run export_tokens.py locally '
            'and update GARMIN_TOKENSTORE secret'
        )

    days_left = (oauth2.expires_at - now) / 86400
    if days_left < 7:
        print(
            f'WARNING: Garmin token expires {expires_str} ({days_left:.1f} days) '
            '— run export_tokens.py soon to avoid sync failures'
        )
    else:
        print(f'Token valid until {expires_str} ({days_left:.1f} days remaining)')

    # Block any path that would call sso.exchange() from GitHub Actions IPs.
    def _refresh_blocked():
        sys.exit(
            'Token refresh attempted mid-run — run export_tokens.py locally '
            'and update GARMIN_TOKENSTORE secret'
        )

    garth.client.refresh_oauth2 = _refresh_blocked


def authenticate():
    email = os.getenv('GARMIN_EMAIL')
    password = os.getenv('GARMIN_PASSWORD')
    tokenstore_b64 = os.getenv('GARMIN_TOKENSTORE', '').strip()

    if tokenstore_b64:
        try:
            decoded = json.loads(base64.b64decode(tokenstore_b64))
            if isinstance(decoded, list):
                # Old format exported by garth.client.dumps(): [oauth1, oauth2]
                print('NOTE: Old token format — re-run export_tokens.py to export only OAuth2')
                oauth2_dict = decoded[1]
            else:
                # New format: just the OAuth2 dict
                oauth2_dict = decoded

            oauth2 = OAuth2Token(**oauth2_dict)
            # A dummy OAuth1 satisfies garth's internal assertion without
            # enabling the real exchange/refresh path (which we block below).
            dummy_oauth1 = OAuth1Token(oauth_token='disabled', oauth_token_secret='disabled')
            garth.client.configure(oauth1_token=dummy_oauth1, oauth2_token=oauth2)
            _check_and_arm_oauth2()
            print('Authenticated via GARMIN_TOKENSTORE (no token exchange)')
            return
        except SystemExit:
            raise
        except Exception as exc:
            print(f'GARMIN_TOKENSTORE load failed: {exc}')

    if os.path.isdir(TOKEN_DIR):
        try:
            garth.resume(TOKEN_DIR)
            _check_and_arm_oauth2()
            print(f'Authenticated via cached tokens at {TOKEN_DIR}')
            return
        except SystemExit:
            raise
        except Exception as exc:
            print(f'Cached token load failed: {exc}')

    for attempt in range(1, 5):
        try:
            print(f'Logging in as {email} (attempt {attempt})...')
            garth.login(email, password)
            garth.save(TOKEN_DIR)
            _check_and_arm_oauth2()
            print(f'Login successful; tokens saved to {TOKEN_DIR}')
            return
        except SystemExit:
            raise
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
    """Always fetches the full 2025-01-01 → today range.

    The weekly maxmet endpoint resamples its bucket boundaries based on the
    queried date range — a short window returns different (and fewer)
    calendarDates than the full range does, not a subset of the same dates.
    So this can't be fetched incrementally; it's cheap (one HTTP call) and
    always fully replaces the existing vo2max list rather than being merged.
    """
    today = date.today().isoformat()
    data = garth.connectapi(
        f'/metrics-service/metrics/maxmet/weekly/{DEFAULT_START.isoformat()}/{today}'
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

def _year_ranges(start_date, end_date):
    """Split [start_date, end_date] into per-calendar-year (start, end) pairs."""
    ranges = []
    d = start_date
    while d <= end_date:
        year_end = min(date(d.year, 12, 31), end_date)
        ranges.append((d.isoformat(), year_end.isoformat()))
        d = date(d.year + 1, 1, 1)
    return ranges


def fetch_rhr(start_date=None):
    """Bulk-fetch daily RHR via userstats endpoint (1 call per calendar year touched)."""
    username = garth.client.username
    today = date.today()
    result = []

    for start, end in _year_ranges(start_date or DEFAULT_START, today):
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

def fetch_body_battery(start_date=None):
    """Fetch daily BB data:
    - 2026: peak+drawdown+charged from intraday reports/daily endpoint
      (month-by-month; endpoint has ~31-day range limit)
    - 2025: charged only from userstats bulk endpoint (intraday returns 400)

    start_date limits how far back to fetch: 2025 userstats is skipped
    entirely if start_date falls in 2026, and the 2026 month-by-month loop
    only starts at start_date's month.
    """
    import calendar
    username = garth.client.username
    today_d  = date.today()
    today    = today_d.isoformat()
    start    = start_date or DEFAULT_START

    # 2026 intraday — one request per calendar month
    start_month = start.month if start.year >= 2026 else 1
    ranges = []
    for month in range(start_month, today_d.month + 1):
        m_start   = f'2026-{month:02d}-01'
        last_day  = calendar.monthrange(2026, month)[1]
        m_end     = min(date(2026, month, last_day), today_d).isoformat()
        ranges.append((m_start, m_end))

    result  = []
    skipped = 0
    for m_start, m_end in ranges:
        try:
            data = garth.connectapi(
                '/wellness-service/wellness/bodyBattery/reports/daily',
                params={'startDate': m_start, 'endDate': m_end},
            )
        except Exception as exc:
            print(f'  BB fetch error ({m_start}): {exc}')
            continue

        for day in (data or []):
            vals   = day.get('bodyBatteryValuesArray') or []
            levels = [v[1] for v in vals if v and v[1] is not None]
            if len(levels) < 2:
                skipped += 1
                continue

            peak      = max(levels)
            after_peak = levels[levels.index(peak):]
            drawdown  = peak - min(after_peak)
            result.append({
                'date': day['date'], 'peak': peak,
                'drawdown': drawdown, 'charged': day.get('charged'),
            })

    print(f'  bodyBattery 2026: {len(result)} days with intraday data'
          + (f' ({skipped} skipped)' if skipped else ''))

    # 2025 charged + drained from userstats (intraday endpoint returns 400 for 2025)
    if start.year <= 2025:
        try:
            r = garth.connectapi(
                f'/userstats-service/wellness/daily/{username}',
                params={'fromDate': '2025-01-01', 'untilDate': '2025-12-31'},
            )
            metrics = (r or {}).get('allMetrics', {}).get('metricsMap', {})

            # WELLNESS_BODYBATTERY_DRAINED — daily total drain (different from intraday drawdown)
            drained_by_date = {
                e['calendarDate']: int(round(e['value']))
                for e in metrics.get('WELLNESS_BODYBATTERY_DRAINED', [])
                if e.get('value') is not None
            }

            charged_2025 = [
                {
                    'date':     e['calendarDate'],
                    'peak':     None,
                    'drawdown': None,
                    'charged':  int(round(e['value'])),
                    'drained':  drained_by_date.get(e['calendarDate']),
                }
                for e in metrics.get('WELLNESS_BODYBATTERY_CHARGED', [])
                if e.get('value') is not None
            ]
            result.extend(charged_2025)
            drained_ct = len(drained_by_date)
            print(f'  bodyBattery 2025: {len(charged_2025)} days charged, '
                  f'{drained_ct} days drained from userstats')
        except Exception as exc:
            print(f'  BB 2025 userstats fetch error: {exc}')

    # The intraday loop above fetches whole calendar months for API efficiency,
    # which can include days before start_date — trim back to the exact window.
    result = [e for e in result if e['date'] >= start.isoformat()]

    result.sort(key=lambda x: x['date'])
    print(f'  bodyBattery total: {len(result)} days')
    return result


# ── Training load / status ───────────────────────────────────────────────────

_STATUS_MAP = {
    0: 'Unknown', 1: 'Peaking', 2: 'Productive',
    3: 'Maintaining', 4: 'Maintaining', 5: 'Recovery',
    6: 'Unproductive', 7: 'Overreaching',
}
_TREND_MAP = {1: 'Improving', 2: 'Stable', 3: 'Declining'}


def fetch_training_load(start_monday=None):
    """Poll trainingstatus/aggregated for every Monday from start_monday
    (default: 2025-01-06, the first Monday of 2025) → today.
    start_monday must already be Monday-aligned (see main()).
    """
    today   = date.today()
    result  = []
    errors  = []

    d = start_monday or date(2025, 1, 6)
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


# ── Incremental sync helpers ──────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--full', action='store_true',
        help='Full historical re-fetch (2025-01-01 → today), replacing runs_data.json '
             'entirely. Default: incremental sync, fetching only from 5 days before '
             'the most recent existing data point forward to today.',
    )
    return parser.parse_args()


def load_existing_data():
    if not os.path.exists(DATA_FILE):
        return None
    with open(DATA_FILE) as f:
        return json.load(f)


def most_recent_start(entries):
    """Most recent date in entries, minus an overlap window, for incremental fetch."""
    if not entries:
        return DEFAULT_START
    most_recent = date.fromisoformat(max(e['date'] for e in entries))
    return most_recent - timedelta(days=OVERLAP_DAYS)


def merge_flat(existing_list, new_list, cutoff_date):
    """Drop existing entries >= cutoff_date, append freshly fetched ones, re-sort ascending."""
    cutoff = cutoff_date.isoformat()
    kept = [e for e in existing_list if e['date'] < cutoff]
    merged = kept + new_list
    merged.sort(key=lambda e: e['date'])
    return merged


def merge_runs(existing_by_year, new_by_year, cutoff_date):
    """Drop existing runs >= cutoff_date (across both years), add new ones, re-sort descending."""
    cutoff = cutoff_date.isoformat()
    merged = {}
    for year in ['2026', '2025']:
        kept = [r for r in existing_by_year.get(year, []) if r['date'] < cutoff]
        combined = kept + new_by_year.get(year, [])
        combined.sort(key=lambda r: r['date'], reverse=True)
        merged[year] = combined
    return merged


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    args = parse_args()
    started = time.time()
    authenticate()

    existing = None if args.full else load_existing_data()
    full_mode = args.full or existing is None
    today = date.today()

    if full_mode:
        print('FULL sync' + (' (--full)' if args.full else ' (no existing runs_data.json)'))
        existing = {'2026': [], '2025': []}
        runs_start = rhr_start = bb_start = DEFAULT_START
        tl_start = date(2025, 1, 6)
    else:
        print('INCREMENTAL sync')
        runs_start = most_recent_start(existing.get('2025', []) + existing.get('2026', []))
        rhr_start  = most_recent_start(existing.get('rhr', []))
        bb_start   = most_recent_start(existing.get('bodyBattery', []))
        tl_recent  = most_recent_start(existing.get('trainingLoad', []))
        tl_start   = max(tl_recent - timedelta(days=tl_recent.weekday()), date(2025, 1, 6))

    # ── Activities ──
    new_runs_by_year = {'2025': [], '2026': []}
    seen_ids = set()

    if full_mode:
        for year in ['2025', '2026']:
            activities = get_activities_by_date(f'{year}-01-01', f'{year}-12-31')
            print(f'  {year}: fetched {len(activities)} activities from Garmin')
            for act in activities:
                parsed = parse_activity(act)
                if parsed is None:
                    continue
                act_id = parsed.pop('id')
                if act_id in seen_ids:
                    continue
                seen_ids.add(act_id)
                new_runs_by_year[year].append(parsed)
            print(f'  {year}: {len(new_runs_by_year[year])} running activities kept')
    else:
        activities = get_activities_by_date(runs_start.isoformat(), today.isoformat())
        print(f'  fetched {len(activities)} activities from Garmin ({runs_start} → {today})')
        for act in activities:
            parsed = parse_activity(act)
            if parsed is None:
                continue
            act_id = parsed.pop('id')
            if act_id in seen_ids:
                continue
            seen_ids.add(act_id)
            new_runs_by_year.setdefault(parsed['date'][:4], []).append(parsed)

    if full_mode:
        result = {'2026': new_runs_by_year['2026'], '2025': new_runs_by_year['2025']}
    else:
        result = merge_runs(existing, new_runs_by_year, runs_start)

    # ── Other metrics ──
    # vo2max is always fully replaced (see fetch_vo2max docstring for why).
    new_vo2max       = fetch_vo2max()
    new_rhr          = fetch_rhr(None if full_mode else rhr_start)
    new_bodyBattery  = fetch_body_battery(None if full_mode else bb_start)
    new_trainingLoad = fetch_training_load(None if full_mode else tl_start)

    result['vo2max'] = new_vo2max
    if full_mode:
        result['rhr']          = new_rhr
        result['bodyBattery']  = new_bodyBattery
        result['trainingLoad'] = new_trainingLoad
    else:
        result['rhr']          = merge_flat(existing.get('rhr', []), new_rhr, rhr_start)
        result['bodyBattery']  = merge_flat(existing.get('bodyBattery', []), new_bodyBattery, bb_start)
        result['trainingLoad'] = merge_flat(existing.get('trainingLoad', []), new_trainingLoad, tl_start)

    result['racePredictions'] = fetch_race_predictions()

    with open(DATA_FILE, 'w') as f:
        json.dump(result, f, indent=2)

    run_total = sum(len(result[y]) for y in ['2025', '2026'])
    elapsed = time.time() - started
    print(f'\nSaved to {DATA_FILE} ({elapsed:.1f}s):')
    print(f'  runs:        {run_total}  ({len(result["2026"])} in 2026, {len(result["2025"])} in 2025)')
    print(f'  vo2max:      {len(result["vo2max"])} weekly readings')
    print(f'  rhr:         {len(result["rhr"])} daily readings')
    print(f'  bodyBattery:  {len(result["bodyBattery"])} daily readings')
    print(f'  trainingLoad: {len(result["trainingLoad"])} weekly readings')
    print(f'  racePreds:    {result["racePredictions"]}')


if __name__ == '__main__':
    main()
