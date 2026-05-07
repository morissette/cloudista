#!/usr/bin/env python3
"""
Given a list of changed blog/*.txt paths (one per line on stdin), call
URL Inspection on each post's live URL and emit a markdown comment body
to stdout for posting on the PR.

Env vars:
    GSC_SA_KEY_FILE   path to service-account JSON
    GSC_SITE_URL      property identifier (default: sc-domain:cloudista.org)
    BASE_URL          public URL prefix (default: https://cloudista.org/blog/)

Usage:
    git diff --name-only origin/main...HEAD -- 'blog/*.txt' | python3 scripts/gsc_inspect_pr.py > comment.md
"""

import os
import re
import sys
import time

import requests
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import service_account

KEY_FILE    = os.environ.get("GSC_SA_KEY_FILE", "scripts/cloudista-8ffbd7d429b1.json")
SITE_URL    = os.environ.get("GSC_SITE_URL", "sc-domain:cloudista.org")
BASE_URL    = os.environ.get("BASE_URL", "https://cloudista.org/blog/")
SCOPES      = ["https://www.googleapis.com/auth/webmasters.readonly"]
INSPECT_URL = "https://searchconsole.googleapis.com/v1/urlInspection/index:inspect"

DATE_PREFIX = re.compile(r"^\d{4}-\d{2}-")


def get_token():
    creds = service_account.Credentials.from_service_account_file(KEY_FILE, scopes=SCOPES)
    creds.refresh(GoogleRequest())
    return creds.token


def slug_from_path(path):
    name = path.rsplit("/", 1)[-1]
    if name.endswith(".txt"):
        name = name[:-4]
    return DATE_PREFIX.sub("", name)


def inspect(url, token):
    resp = requests.post(
        INSPECT_URL,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"inspectionUrl": url, "siteUrl": SITE_URL},
        timeout=20,
    )
    return resp.status_code, resp.json()


def main():
    paths = [line.strip() for line in sys.stdin if line.strip().startswith("blog/") and line.strip().endswith(".txt")]
    if not paths:
        print("No `blog/*.txt` changes detected — skipping GSC inspection.")
        return 0

    token = get_token()
    rows = []
    for p in paths:
        slug = slug_from_path(p)
        url = f"{BASE_URL}{slug}"
        code, body = inspect(url, token)
        if code != 200:
            err = body.get("error", {}).get("message", str(body))
            rows.append((slug, url, "?", f"error: {code}", "-", err))
        else:
            idx = body.get("inspectionResult", {}).get("indexStatusResult", {})
            rows.append((
                slug,
                url,
                idx.get("verdict", "?"),
                idx.get("coverageState", "?"),
                idx.get("lastCrawlTime", "") or "-",
                "",
            ))
        time.sleep(0.3)

    out = ["## GSC index status for changed posts", ""]
    out.append("| Slug | Verdict | Coverage state | Last crawl |")
    out.append("|---|---|---|---|")
    for slug, url, verdict, cov, last, _err in rows:
        out.append(f"| [{slug}]({url}) | {verdict} | {cov} | {last} |")
    out.append("")
    out.append(
        "_If a post is not yet present, Google has not seen the new URL — "
        "this is normal until the sitemap is re-fetched._"
    )
    sys.stdout.write("\n".join(out) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
