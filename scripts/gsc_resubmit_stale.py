#!/usr/bin/env python3
"""
Read scripts/.gsc_status_history.json (latest run) and re-submit any URL
that has been "Discovered - currently not indexed" for >= MIN_AGE_DAYS to
the Google Indexing API.

Indexing API quota is 200/day. Caps requests at MAX_RESUBMITS.

Env vars:
    GSC_SA_KEY_FILE   path to service-account JSON
    MIN_AGE_DAYS      resubmit if firstSeenDiscovered older than this (default: 7)
    MAX_RESUBMITS     cap per run (default: 50)

Usage:
    python3 scripts/gsc_resubmit_stale.py
"""

import datetime as dt
import json
import os
import sys
import time
from pathlib import Path

import requests
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import service_account

KEY_FILE      = os.environ.get("GSC_SA_KEY_FILE", "scripts/cloudista-8ffbd7d429b1.json")
MIN_AGE_DAYS  = int(os.environ.get("MIN_AGE_DAYS", "7"))
MAX_RESUBMITS = int(os.environ.get("MAX_RESUBMITS", "50"))
HISTORY_FILE  = Path("scripts/.gsc_status_history.json")
SCOPES        = ["https://www.googleapis.com/auth/indexing"]
API_URL       = "https://indexing.googleapis.com/v3/urlNotifications:publish"
DELAY_S       = 0.5


def get_token():
    creds = service_account.Credentials.from_service_account_file(KEY_FILE, scopes=SCOPES)
    creds.refresh(GoogleRequest())
    return creds.token


def main():
    if not HISTORY_FILE.exists():
        print(f"No history at {HISTORY_FILE} — run gsc_status.py first.")
        return 0
    history = json.loads(HISTORY_FILE.read_text())
    runs = history.get("runs", [])
    if not runs:
        print("No runs in history.")
        return 0
    latest = runs[-1]
    today = dt.date.today()

    stale = []
    for r in latest.get("results", []):
        if "Discovered" not in r.get("coverageState", ""):
            continue
        seen = r.get("firstSeenDiscovered")
        if not seen:
            continue
        try:
            seen_date = dt.date.fromisoformat(seen)
        except ValueError:
            continue
        age = (today - seen_date).days
        if age >= MIN_AGE_DAYS:
            stale.append((r["url"], age))

    stale.sort(key=lambda x: -x[1])
    stale = stale[:MAX_RESUBMITS]
    print(f"Found {len(stale)} URLs stuck Discovered for >= {MIN_AGE_DAYS}d (capped at {MAX_RESUBMITS}).")

    if not stale:
        return 0

    token = get_token()
    ok = 0
    for i, (url, age) in enumerate(stale, 1):
        resp = requests.post(
            API_URL,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"url": url, "type": "URL_UPDATED"},
            timeout=15,
        )
        body = resp.json()
        if resp.status_code == 200:
            print(f"  [{i:3}/{len(stale)}] OK ({age}d) {url}")
            ok += 1
        elif resp.status_code == 429:
            print(f"  [{i:3}/{len(stale)}] 429 quota — stopping. {ok} resubmitted this run.")
            return 2
        else:
            err = body.get("error", {}).get("message", str(body))
            print(f"  [{i:3}/{len(stale)}] {resp.status_code} {url} — {err}")
        time.sleep(DELAY_S)

    print(f"\nResubmitted {ok}/{len(stale)} stale URLs.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
