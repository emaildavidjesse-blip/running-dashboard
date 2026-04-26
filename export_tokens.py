#!/usr/bin/env python3
"""
Run this once locally to generate a GARMIN_TOKENSTORE secret.

Usage:
    python3 export_tokens.py

It will prompt for your Garmin credentials (and an MFA code if required),
save tokens to ~/.garth/, then print the base64 token string.

Copy that string and add it as a GitHub repository secret named
GARMIN_TOKENSTORE under Settings → Secrets and variables → Actions.
"""
import os
from dotenv import load_dotenv
from garminconnect import Garmin

load_dotenv()

TOKEN_DIR = os.path.expanduser('~/.garth')

email    = os.getenv('GARMIN_EMAIL')    or input('Garmin email: ').strip()
password = os.getenv('GARMIN_PASSWORD') or input('Garmin password: ').strip()

client = Garmin(email, password)

if os.path.isdir(TOKEN_DIR):
    try:
        client.garth.load(TOKEN_DIR)
        print(f'Loaded existing tokens from {TOKEN_DIR} (no new login needed)')
    except Exception as exc:
        print(f'Cached tokens unusable ({exc}), doing fresh login...')
        client.garth.login(email, password, prompt_mfa=lambda: input('MFA code: ').strip())
        client.garth.dump(TOKEN_DIR)
        print(f'Tokens saved to {TOKEN_DIR}')
else:
    print(f'Logging in as {email}...')
    client.garth.login(email, password, prompt_mfa=lambda: input('MFA code: ').strip())
    os.makedirs(TOKEN_DIR, exist_ok=True)
    client.garth.dump(TOKEN_DIR)
    print(f'Tokens saved to {TOKEN_DIR}')

# Print base64 string for GitHub Secret
token_str = client.garth.dumps()
print()
print('=' * 60)
print('Add this as GitHub Secret GARMIN_TOKENSTORE:')
print('=' * 60)
print(token_str)
print('=' * 60)
