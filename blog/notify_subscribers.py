#!/usr/bin/env python3
"""
Send new-post notifications to cloudista.org subscribers.

Modes:
  --mode immediate  Send each newly published post to subscribers who want
                    immediate delivery. Marks posts notified_at when done.
  --mode digest     Send a weekly digest to subscribers whose last_digest_at
                    is NULL or older than 7 days.

Usage:
  POPULATE_DB_DSN="postgresql://..." python3 notify_subscribers.py --mode immediate
  POPULATE_DB_DSN="postgresql://..." python3 notify_subscribers.py --mode digest --dry-run
"""

from __future__ import annotations

import argparse
import logging
import os
from typing import Any

import boto3
import psycopg2
import psycopg2.extras
from email_template import build_digest_email, build_immediate_email

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

_DEFAULT_DSN = "postgresql://cloudista:cloudista_dev@localhost:5433/cloudista"
DB_DSN = os.environ.get("POPULATE_DB_DSN", _DEFAULT_DSN)
if DB_DSN == _DEFAULT_DSN:
    log.warning("Using default dev DSN — set POPULATE_DB_DSN for production")

FROM_EMAIL = os.environ.get("FROM_EMAIL", "noreply@cloudista.org")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
SITE_URL = os.environ.get("SITE_URL", "https://cloudista.org")


def _ses_client() -> Any:
    return boto3.client("ses", region_name=AWS_REGION)


def _send(ses: Any, to_email: str, subject: str, html: str, text: str, dry_run: bool) -> bool:
    if dry_run:
        log.info("[dry-run] Would send %r to %s", subject, to_email)
        return True
    try:
        ses.send_email(
            Source=FROM_EMAIL,
            Destination={"ToAddresses": [to_email]},
            Message={
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {
                    "Html": {"Data": html, "Charset": "UTF-8"},
                    "Text": {"Data": text, "Charset": "UTF-8"},
                },
            },
        )
        return True
    except Exception as exc:
        log.error("SES send failed to %s: %s", to_email, exc)
        return False


def run_immediate(conn: Any, ses: Any, dry_run: bool) -> None:
    """Send each unnotified published post to immediate-frequency subscribers."""
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    cur.execute("""
        SELECT id, slug, title, excerpt, image_url, published_at
        FROM posts
        WHERE status = 'published'
          AND published_at <= now()
          AND notified_at IS NULL
        ORDER BY published_at ASC
    """)
    posts = cur.fetchall()

    if not posts:
        log.info("No unnotified posts — nothing to send")
        return

    cur.execute("""
        SELECT email, token, prefs_token
        FROM subscribers
        WHERE status = 'confirmed' AND frequency = 'immediate'
    """)
    subscribers = cur.fetchall()

    if not subscribers:
        log.info("No immediate-frequency subscribers")
        # Still mark posts notified so they don't pile up forever
        for post in posts:
            if not dry_run:
                cur.execute("UPDATE posts SET notified_at = now() WHERE id = %s", (post["id"],))
        if not dry_run:
            conn.commit()
        return

    for post in posts:
        log.info("Notifying %d subscriber(s) of post: %s", len(subscribers), post["slug"])
        sent = 0
        for sub in subscribers:
            unsub_url = f"{SITE_URL}/api/unsubscribe/{sub['token']}"
            prefs_url = f"{SITE_URL}/api/preferences/{sub['prefs_token']}" if sub["prefs_token"] else ""
            subject, html, text = build_immediate_email(dict(post), unsub_url, prefs_url)
            if _send(ses, sub["email"], subject, html, text, dry_run):
                sent += 1
        log.info("  Sent %d/%d for %s", sent, len(subscribers), post["slug"])
        if not dry_run:
            cur.execute("UPDATE posts SET notified_at = now() WHERE id = %s", (post["id"],))
            conn.commit()


def run_digest(conn: Any, ses: Any, dry_run: bool) -> None:
    """Send weekly digest to subscribers whose last_digest_at is due."""
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    cur.execute("""
        SELECT id, email, token, prefs_token, last_digest_at
        FROM subscribers
        WHERE status = 'confirmed'
          AND frequency = 'weekly'
          AND (last_digest_at IS NULL OR last_digest_at < now() - INTERVAL '7 days')
    """)
    subscribers = cur.fetchall()

    if not subscribers:
        log.info("No subscribers due for digest")
        return

    log.info("Sending digest to %d subscriber(s)", len(subscribers))

    for sub in subscribers:
        since = sub["last_digest_at"]
        if since is None:
            # First digest — send last 5 posts
            cur.execute("""
                SELECT slug, title, excerpt, image_url, published_at
                FROM posts
                WHERE status = 'published' AND published_at <= now()
                ORDER BY published_at DESC
                LIMIT 5
            """)
        else:
            cur.execute("""
                SELECT slug, title, excerpt, image_url, published_at
                FROM posts
                WHERE status = 'published'
                  AND published_at <= now()
                  AND published_at > %s
                ORDER BY published_at DESC
                LIMIT 5
            """, (since,))

        posts = cur.fetchall()
        if not posts:
            log.info("  No new posts for %s since last digest — skipping", sub["email"])
            continue

        unsub_url = f"{SITE_URL}/api/unsubscribe/{sub['token']}"
        prefs_url = f"{SITE_URL}/api/preferences/{sub['prefs_token']}" if sub["prefs_token"] else ""
        subject, html, text = build_digest_email([dict(p) for p in posts], unsub_url, prefs_url)

        if _send(ses, sub["email"], subject, html, text, dry_run):
            log.info("  Digest sent to %s (%d posts)", sub["email"], len(posts))
            if not dry_run:
                cur.execute("UPDATE subscribers SET last_digest_at = now() WHERE id = %s", (sub["id"],))
                conn.commit()
        else:
            log.warning("  Failed to send digest to %s", sub["email"])


def main() -> None:
    parser = argparse.ArgumentParser(description="Send cloudista.org subscriber notifications")
    parser.add_argument("--mode", choices=["immediate", "digest"], required=True)
    parser.add_argument("--dry-run", action="store_true", help="Print what would be sent without sending")
    args = parser.parse_args()

    conn = psycopg2.connect(DB_DSN)
    ses = _ses_client()

    try:
        if args.mode == "immediate":
            run_immediate(conn, ses, args.dry_run)
        else:
            run_digest(conn, ses, args.dry_run)
    finally:
        conn.close()

    log.info("Done.")


if __name__ == "__main__":
    main()
