#!/usr/bin/env python3
"""
Auto-check Garmin OAuth2 token expiry; refresh and push to GitHub if within 7 days.
Called by run_sync.sh before each daily sync. Exits 0 always (failures are logged
as warnings so they don't abort the sync when the token is still usable).

Requires in .env:
    GITHUB_TOKEN  — personal access token with secrets:write scope
"""
import os
import sys
import json
import base64
import time
from dataclasses import asdict
from datetime import datetime
from typing import Optional

from dotenv import load_dotenv
import garth
import requests

load_dotenv()

TOKEN_DIR = os.path.expanduser('~/.garth')
OWNER     = 'emaildavidjesse-blip'
REPO      = 'running-dashboard'
SECRET    = 'GARMIN_TOKENSTORE'


def token_days_remaining() -> Optional[float]:
    garth.resume(TOKEN_DIR)
    oauth2 = garth.client.oauth2_token
    if not oauth2:
        return None
    return (oauth2.expires_at - time.time()) / 86400


def do_refresh() -> str:
    """Refresh OAuth2, save locally, and return base64-encoded token."""
    garth.resume(TOKEN_DIR)
    garth.client.refresh_oauth2()
    garth.save(TOKEN_DIR)
    oauth2     = garth.client.oauth2_token
    token_b64  = base64.b64encode(json.dumps(asdict(oauth2)).encode()).decode()
    expires    = datetime.fromtimestamp(oauth2.expires_at)
    days_left  = (oauth2.expires_at - time.time()) / 86400
    print(f'OAuth2 refreshed — new expiry {expires:%Y-%m-%d} ({days_left:.1f} days)')
    return token_b64


def _encrypt_secret(public_key_b64: str, secret_value: str) -> str:
    """Seal with libsodium crypto_box_seal as required by the GitHub Secrets API."""
    from nacl.public import PublicKey, SealedBox
    pk  = PublicKey(base64.b64decode(public_key_b64))
    box = SealedBox(pk)
    return base64.b64encode(box.encrypt(secret_value.encode())).decode()


def upload_to_github(token_b64: str) -> None:
    github_token = os.getenv('GITHUB_TOKEN', '').strip()
    if not github_token:
        print('GITHUB_TOKEN not set in .env — skipping GitHub secret update')
        print('Add GITHUB_TOKEN=<PAT with secrets:write> to .env to enable auto-upload')
        return

    hdrs = {
        'Authorization': f'Bearer {github_token}',
        'Accept':        'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
    }

    # Fetch the repo's public key (required for secret encryption)
    r = requests.get(
        f'https://api.github.com/repos/{OWNER}/{REPO}/actions/secrets/public-key',
        headers=hdrs, timeout=15,
    )
    r.raise_for_status()
    pk_data = r.json()

    encrypted = _encrypt_secret(pk_data['key'], token_b64)

    # Create or update the secret (PUT = upsert)
    r = requests.put(
        f'https://api.github.com/repos/{OWNER}/{REPO}/actions/secrets/{SECRET}',
        headers=hdrs, timeout=15,
        json={'encrypted_value': encrypted, 'key_id': pk_data['key_id']},
    )
    r.raise_for_status()
    print(f'GitHub secret {SECRET} updated successfully')


def main() -> None:
    try:
        days = token_days_remaining()
    except Exception as exc:
        print(f'Could not read token expiry: {exc}')
        return   # not fatal — sync_garmin.py will surface its own auth error

    if days is None:
        print('No OAuth2 token found in ~/.garth')
        return

    if days > 7:
        print(f'Token valid for {days:.0f} more days — no refresh needed')
        return

    print(f'Token expires in {days:.1f} days — refreshing automatically')
    try:
        token_b64 = do_refresh()
        upload_to_github(token_b64)
        print('Token refreshed automatically')
    except Exception as exc:
        print(f'Token refresh/upload failed: {exc}')
        # Non-fatal: sync_garmin.py will still run and may succeed if token
        # isn't actually expired yet (days can be fractional).


if __name__ == '__main__':
    main()
