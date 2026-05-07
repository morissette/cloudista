#!/usr/bin/env python3
"""
Request Google indexing for all URLs in the cloudista.org sitemap.
Uses the Google Indexing API with a service account key.

Usage:
    python3 scripts/request_indexing.py

Requirements:
    pip install google-auth requests
"""

import os
import sys
import time
import xml.etree.ElementTree as ET

import requests
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import service_account

KEY_FILE    = os.environ.get("GSC_SA_KEY_FILE", "scripts/cloudista-8ffbd7d429b1.json")
SITEMAP_URL = "https://cloudista.org/sitemap.xml"
SCOPES      = ["https://www.googleapis.com/auth/indexing"]
API_URL     = "https://indexing.googleapis.com/v3/urlNotifications:publish"
STATE_FILE  = os.environ.get("GSC_STATE_FILE", "scripts/.indexing_done.txt")
DELAY_S     = 0.5   # stay well under the 200/day quota


def get_access_token():
    creds = service_account.Credentials.from_service_account_file(KEY_FILE, scopes=SCOPES)
    creds.refresh(GoogleRequest())
    return creds.token


def fetch_sitemap_urls():
    resp = requests.get(SITEMAP_URL, timeout=10)
    resp.raise_for_status()
    root = ET.fromstring(resp.text)
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    return [loc.text.strip() for loc in root.findall(".//sm:loc", ns) if loc.text]


def request_indexing(url, token):
    resp = requests.post(
        API_URL,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"url": url, "type": "URL_UPDATED"},
        timeout=10,
    )
    return resp.status_code, resp.json()


def load_done():
    try:
        with open(STATE_FILE) as f:
            return set(line.strip() for line in f if line.strip())
    except FileNotFoundError:
        return set()


def mark_done(url):
    with open(STATE_FILE, "a") as f:
        f.write(url + "\n")


def main():
    print("Fetching sitemap...")
    urls = fetch_sitemap_urls()
    done = load_done()
    remaining = [u for u in urls if u not in done]
    print(f"Found {len(urls)} URLs — {len(done)} already submitted, {len(remaining)} remaining\n")

    if not remaining:
        print("All URLs already submitted.")
        return

    print("Getting access token...")
    token = get_access_token()

    ok = 0
    errors = []

    for i, url in enumerate(remaining, 1):
        code, body = request_indexing(url, token)
        if code == 200:
            print(f"  [{i:3}/{len(remaining)}] OK  {url}")
            mark_done(url)
            ok += 1
        elif code == 429:
            err = body.get("error", {}).get("message", "quota exceeded")
            print(f"  [{i:3}/{len(remaining)}] 429 Quota exceeded — stopping. Run again tomorrow.")
            print(f"  Submitted {ok} this run. {len(done) + ok}/{len(urls)} total done.")
            sys.exit(2)
        else:
            err = body.get("error", {}).get("message", str(body))
            print(f"  [{i:3}/{len(remaining)}] {code} {url}  -- {err}")
            errors.append((url, code, err))
        time.sleep(DELAY_S)

    print(f"\nDone. {ok}/{len(remaining)} submitted this run. {len(done) + ok}/{len(urls)} total.")
    if errors:
        print(f"\n{len(errors)} error(s):")
        for url, code, err in errors:
            print(f"  {code}  {url}  -- {err}")
        sys.exit(1)


if __name__ == "__main__":
    main()
