#!/usr/bin/env python3
"""
Run this locally to generate or renew the GARMIN_TOKENSTORE secret.

Usage:
    python3 export_tokens.py

Authenticates, forces a fresh OAuth2 token refresh (done locally so
Garmin's rate-limit on the exchange endpoint isn't hit), then exports
ONLY the OAuth2 token.  OAuth1 is intentionally omitted — if the secret
leaks the exposure window is limited to the token's remaining lifetime.

Copy the printed string and store it as a GitHub repository secret named
GARMIN_TOKENSTORE under Settings → Secrets and variables → Actions.
"""
import os
import json
import base64
import time
from dataclasses import asdict
from datetime import datetime
from dotenv import load_dotenv
import garth

load_dotenv()

TOKEN_DIR = os.path.expanduser('~/.garth')

email    = os.getenv('GARMIN_EMAIL')    or input('Garmin email: ').strip()
password = os.getenv('GARMIN_PASSWORD') or input('Garmin password: ').strip()

# ── Authenticate ──────────────────────────────────────────────────────────────
if os.path.isdir(TOKEN_DIR):
    try:
        garth.resume(TOKEN_DIR)
        print(f'Loaded existing tokens from {TOKEN_DIR}')
    except Exception as exc:
        print(f'Cached tokens unusable ({exc}), doing fresh login...')
        garth.login(email, password)
        garth.save(TOKEN_DIR)
        print(f'Logged in and saved tokens to {TOKEN_DIR}')
else:
    print(f'Logging in as {email}...')
    garth.login(email, password)
    garth.save(TOKEN_DIR)
    print(f'Logged in and saved tokens to {TOKEN_DIR}')

# ── Force a fresh OAuth2 token (done locally, not rate-limited) ───────────────
print('Refreshing OAuth2 token...')
garth.client.refresh_oauth2()
garth.save(TOKEN_DIR)
print(f'OAuth2 token refreshed and saved to {TOKEN_DIR}')

# ── Export only the OAuth2 token ──────────────────────────────────────────────
oauth2 = garth.client.oauth2_token
token_b64 = base64.b64encode(json.dumps(asdict(oauth2)).encode()).decode()

expires_at  = datetime.fromtimestamp(oauth2.expires_at)
expires_str = expires_at.strftime('%Y-%m-%d %H:%M:%S')
days_left   = (oauth2.expires_at - time.time()) / 86400

print()
print('=' * 60)
print('Add this as GitHub Secret GARMIN_TOKENSTORE:')
print('=' * 60)
print(token_b64)
print('=' * 60)
print(f'Token expires: {expires_str}  ({days_left:.1f} days from now)')
print('Renew before expiry by re-running this script.')
