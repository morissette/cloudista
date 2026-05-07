#!/usr/bin/env python3
"""
Walk every URL in the cloudista.org sitemap, call Search Console
URL Inspection API, write a status report.

Outputs:
    scripts/.gsc_status_history.json  — full inspection results, machine-readable
    docs/gsc-status.md                — human-readable summary table

Env vars:
    GSC_SA_KEY_FILE   path to service-account JSON (default: scripts/cloudista-8ffbd7d429b1.json)
    GSC_SITE_URL      property identifier (default: sc-domain:cloudista.org)
    GSC_LIMIT         optional max URLs to inspect (default: all)

Usage:
    python3 scripts/gsc_status.py
"""

import datetime as dt
import json
import os
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import requests
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import service_account

KEY_FILE      = os.environ.get("GSC_SA_KEY_FILE", "scripts/cloudista-8ffbd7d429b1.json")
SITE_URL      = os.environ.get("GSC_SITE_URL", "sc-domain:cloudista.org")
SITEMAP_URL   = os.environ.get("GSC_SITEMAP_URL", "https://cloudista.org/sitemap.xml")
LIMIT         = int(os.environ.get("GSC_LIMIT", "0")) or None
SCOPES        = ["https://www.googleapis.com/auth/webmasters.readonly"]
INSPECT_URL   = "https://searchconsole.googleapis.com/v1/urlInspection/index:inspect"
HISTORY_FILE  = Path("scripts/.gsc_status_history.json")
REPORT_FILE   = Path("docs/gsc-status.md")
DELAY_S       = 0.4


def get_token():
    creds = service_account.Credentials.from_service_account_file(KEY_FILE, scopes=SCOPES)
    creds.refresh(GoogleRequest())
    return creds.token


def fetch_sitemap_urls():
    resp = requests.get(SITEMAP_URL, timeout=15)
    resp.raise_for_status()
    root = ET.fromstring(resp.text)
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    return [loc.text.strip() for loc in root.findall(".//sm:loc", ns) if loc.text]


def inspect(url, token):
    resp = requests.post(
        INSPECT_URL,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"inspectionUrl": url, "siteUrl": SITE_URL},
        timeout=20,
    )
    return resp.status_code, resp.json()


def load_history():
    if HISTORY_FILE.exists():
        try:
            return json.loads(HISTORY_FILE.read_text())
        except json.JSONDecodeError:
            return {"runs": []}
    return {"runs": []}


def main():
    urls = fetch_sitemap_urls()
    if LIMIT:
        urls = urls[:LIMIT]
    print(f"Inspecting {len(urls)} URLs against {SITE_URL}...", flush=True)

    token = get_token()
    today = dt.date.today().isoformat()
    results = []
    counts = {}

    for i, url in enumerate(urls, 1):
        code, body = inspect(url, token)
        if code != 200:
            err = body.get("error", {}).get("message", str(body))
            print(f"  [{i:3}/{len(urls)}] {code} {url}  -- {err}", flush=True)
            results.append({"url": url, "error": f"{code}: {err}"})
            counts["error"] = counts.get("error", 0) + 1
            time.sleep(DELAY_S)
            continue
        idx = body.get("inspectionResult", {}).get("indexStatusResult", {})
        verdict = idx.get("verdict", "?")
        coverage = idx.get("coverageState", "?")
        last_crawl = idx.get("lastCrawlTime", "")
        first_seen_discovered = None
        if "Discovered" in coverage:
            history = load_history()
            for run in reversed(history.get("runs", [])):
                for r in run.get("results", []):
                    if r["url"] == url and "Discovered" in r.get("coverageState", ""):
                        first_seen_discovered = run["date"]
                        break
                if first_seen_discovered:
                    break
            first_seen_discovered = first_seen_discovered or today
        results.append({
            "url": url,
            "verdict": verdict,
            "coverageState": coverage,
            "lastCrawlTime": last_crawl,
            "firstSeenDiscovered": first_seen_discovered,
        })
        counts[coverage] = counts.get(coverage, 0) + 1
        print(f"  [{i:3}/{len(urls)}] {verdict:7} {coverage}  {url}", flush=True)
        time.sleep(DELAY_S)

    history = load_history()
    history["runs"] = (history.get("runs", []) + [{"date": today, "results": results}])[-30:]
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_FILE.write_text(json.dumps(history, indent=2))
    print(f"\nWrote {HISTORY_FILE}")

    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with REPORT_FILE.open("w") as f:
        f.write("# GSC Index Status — cloudista.org\n\n")
        f.write(f"_Last run: {today} • {len(urls)} URLs inspected_\n\n")
        f.write("## Summary\n\n")
        f.write("| Coverage state | Count |\n|---|---|\n")
        for state, n in sorted(counts.items(), key=lambda x: -x[1]):
            f.write(f"| {state} | {n} |\n")
        f.write("\n## Discovered — currently not indexed\n\n")
        stuck = [r for r in results if "Discovered" in r.get("coverageState", "")]
        if stuck:
            f.write("| URL | First seen Discovered | Last crawl |\n|---|---|---|\n")
            for r in sorted(stuck, key=lambda x: x.get("firstSeenDiscovered", "")):
                f.write(f"| {r['url']} | {r.get('firstSeenDiscovered','-')} | {r.get('lastCrawlTime','-') or '-'} |\n")
        else:
            f.write("_None._\n")
        f.write("\n## Crawled — currently not indexed\n\n")
        crawled = [r for r in results if r.get("coverageState", "") == "Crawled - currently not indexed"]
        if crawled:
            f.write("| URL | Last crawl |\n|---|---|\n")
            for r in crawled:
                f.write(f"| {r['url']} | {r.get('lastCrawlTime','-') or '-'} |\n")
        else:
            f.write("_None._\n")
        errors = [r for r in results if "error" in r]
        if errors:
            f.write("\n## Errors\n\n")
            for r in errors:
                f.write(f"- {r['url']} — {r['error']}\n")
    print(f"Wrote {REPORT_FILE}")


if __name__ == "__main__":
    sys.exit(main() or 0)
