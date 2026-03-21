#!/usr/bin/env python3
"""
verify_pending.py — send verification emails to all pending subscribers.

Usage:
    python3 verify_pending.py            # live run
    python3 verify_pending.py --dry-run  # preview only, no emails sent

The script reads credentials from /www/cloudista.org/api/.env by default.
Override with --env-file path/to/.env

Rate: SES account limit is 14 emails/sec; script sends at ≤10/sec to stay safe.
"""

import argparse
import logging
import os
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Load .env before importing app modules
# ---------------------------------------------------------------------------
DEFAULT_ENV = Path("/www/cloudista.org/api/.env")

parser = argparse.ArgumentParser(description="Send verification emails to pending subscribers.")
parser.add_argument("--dry-run",  action="store_true", help="Preview without sending")
parser.add_argument("--env-file", default=str(DEFAULT_ENV), help="Path to .env file")
parser.add_argument("--limit",    type=int, default=0,  help="Max emails to send (0 = all)")
args = parser.parse_args()

env_path = Path(args.env_file)
if not env_path.exists():
    sys.exit(f"ERROR: env file not found: {env_path}")

# Manual .env parse (no python-dotenv dependency needed in scripts/)
with env_path.open() as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip())

# ---------------------------------------------------------------------------
# Imports (after env is set)
# .env must be loaded before these modules are imported so they pick up the
# correct environment variables — E402 is intentional here.
# ---------------------------------------------------------------------------
import boto3  # noqa: E402
import pymysql  # noqa: E402
import pymysql.cursors  # noqa: E402
from botocore.exceptions import BotoCoreError, ClientError  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent.parent / "api"))
from email_template import build_verification_email  # noqa: E402

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("verify_pending")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DB_CONFIG = {
    "host":        os.environ["DB_HOST"],
    "port":        int(os.environ.get("DB_PORT", 3306)),
    "user":        os.environ["DB_USER"],
    "password":    os.environ["DB_PASSWORD"],
    "database":    os.environ["DB_NAME"],
    "charset":     "utf8mb4",
    "cursorclass": pymysql.cursors.DictCursor,
}

AWS_REGION       = os.environ.get("AWS_REGION",       "us-east-1")
FROM_EMAIL       = os.environ.get("FROM_EMAIL",       "noreply@cloudista.org")
CONFIRM_BASE_URL = os.environ.get("CONFIRM_BASE_URL", "https://cloudista.org/api/confirm")

SEND_RATE = 10  # emails per second (SES quota is 14/s — keep margin)

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    mode_label = "[DRY RUN] " if args.dry_run else ""
    log.info("%sStarting verification email run", mode_label)

    # --- Fetch pending subscribers ---
    conn = pymysql.connect(**DB_CONFIG)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, email, token
                     FROM subscribers
                    WHERE status = 'pending'
                    ORDER BY created_at ASC"""
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    if not rows:
        log.info("No pending subscribers found — nothing to do.")
        return

    total = len(rows)
    limit = args.limit if args.limit > 0 else total
    rows  = rows[:limit]

    log.info(
        "Found %d pending subscriber(s). Will process %d. dry_run=%s",
        total, len(rows), args.dry_run,
    )

    # --- SES client ---
    ses = boto3.client("ses", region_name=AWS_REGION)

    sent = skipped = failed = 0

    for i, row in enumerate(rows, start=1):
        email = row["email"]
        token = row["token"]
        confirm_url = f"{CONFIRM_BASE_URL}/{token}"

        if args.dry_run:
            log.info("[%d/%d] WOULD SEND → %s  (%s)", i, len(rows), email, confirm_url)
            sent += 1
            continue

        subject, html, text = build_verification_email(confirm_url)
        try:
            ses.send_email(
                Source=FROM_EMAIL,
                Destination={"ToAddresses": [email]},
                Message={
                    "Subject": {"Data": subject, "Charset": "UTF-8"},
                    "Body": {
                        "Html": {"Data": html,  "Charset": "UTF-8"},
                        "Text": {"Data": text, "Charset": "UTF-8"},
                    },
                },
            )
            log.info("[%d/%d] Sent → %s", i, len(rows), email)
            sent += 1

        except (BotoCoreError, ClientError) as exc:
            log.error("[%d/%d] FAILED → %s : %s", i, len(rows), email, exc)
            failed += 1

        # Respect SES send rate
        if i < len(rows):
            time.sleep(1 / SEND_RATE)

    # --- Summary ---
    log.info(
        "%sComplete. sent=%d  skipped=%d  failed=%d",
        mode_label, sent, skipped, failed,
    )
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
