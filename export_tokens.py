#!/usr/bin/env python3
"""
Run this once locally to generate a GARMIN_TOKENSTORE secret.

Usage:
    python3 export_tokens.py

It will reuse cached tokens in ~/.garth/ if present (no login needed),
otherwise it will prompt interactively and handle MFA if required.

Copy the printed string and add it as a GitHub repository secret named
GARMIN_TOKENSTORE under Settings → Secrets and variables → Actions.
"""
import os
from dotenv import load_dotenv
import garth

load_dotenv()

TOKEN_DIR = os.path.expanduser('~/.garth')

email    = os.getenv('GARMIN_EMAIL')    or input('Garmin email: ').strip()
password = os.getenv('GARMIN_PASSWORD') or input('Garmin password: ').strip()

if os.path.isdir(TOKEN_DIR):
    try:
        garth.resume(TOKEN_DIR)   # garth.client.load(TOKEN_DIR)
        print(f'Loaded existing tokens from {TOKEN_DIR} (no new login needed)')
    except Exception as exc:
        print(f'Cached tokens unusable ({exc}), doing fresh login...')
        garth.login(email, password)
        garth.save(TOKEN_DIR)
        print(f'Tokens saved to {TOKEN_DIR}')
else:
    print(f'Logging in as {email}...')
    garth.login(email, password)
    garth.save(TOKEN_DIR)
    print(f'Tokens saved to {TOKEN_DIR}')

print()
print('=' * 60)
print('Add this as GitHub Secret GARMIN_TOKENSTORE:')
print('=' * 60)
print(garth.client.dumps())
print('=' * 60)
