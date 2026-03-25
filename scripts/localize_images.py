#!/usr/bin/env python3
from __future__ import annotations

"""
Download external (CDN) post images to /www/cloudista.org/images/posts/ and
update the DB to use the local path.

Run on the server after populate_images.py has filled image_url for all posts:

    DB_PASS=$(grep BLOG_DB_PASSWORD /www/cloudista.org/api/.env | cut -d= -f2)
    POPULATE_DB_DSN="postgresql://cloudista:${DB_PASS}@localhost:5433/cloudista" \
      python3 localize_images.py

Options:
    --slug SLUG   Only process a single post
    --dry-run     Print what would be done without changing anything
    --images-dir  Override the local images directory (default: /www/cloudista.org/images/posts)
"""

import argparse
import logging
import os
import sys
import time
import urllib.request
from pathlib import Path

import psycopg2
import psycopg2.extras

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

_DEFAULT_DSN = "postgresql://cloudista:cloudista_dev@localhost:5433/cloudista"
DB_DSN = os.environ.get("POPULATE_DB_DSN", _DEFAULT_DSN)
DEFAULT_IMAGES_DIR = "/www/cloudista.org/images/posts"


def is_external(url: str) -> bool:
    return url.startswith("http://") or url.startswith("https://")


def ext_for_url(url: str) -> str:
    """Guess file extension from URL path, defaulting to .jpg."""
    path = url.split("?")[0].split("#")[0]
    suffix = Path(path).suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        return suffix if suffix != ".jpeg" else ".jpg"
    return ".jpg"


def download(url: str, dest: Path, dry_run: bool = False) -> bool:
    if dry_run:
        log.info("[dry-run] would download %s → %s", url, dest)
        return True
    try:
        headers = {"User-Agent": "cloudista-image-localizer/1.0"}
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(resp.read())
        log.info("downloaded %s → %s (%d bytes)", url, dest, dest.stat().st_size)
        return True
    except Exception as exc:
        log.warning("failed to download %s: %s", url, exc)
        return False


def localize(slug: str | None = None, dry_run: bool = False, images_dir: str = DEFAULT_IMAGES_DIR) -> None:
    conn = psycopg2.connect(DB_DSN)
    conn.autocommit = False
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    if slug:
        cur.execute(
            "SELECT slug, image_url FROM posts WHERE slug = %s",
            (slug,),
        )
    else:
        cur.execute(
            "SELECT slug, image_url FROM posts "
            "WHERE status = 'published' AND image_url IS NOT NULL "
            "ORDER BY slug"
        )

    rows = cur.fetchall()
    external = [r for r in rows if r["image_url"] and is_external(r["image_url"])]
    log.info("%d posts with external image_url to localize", len(external))

    ok = 0
    skip = 0
    fail = 0

    for row in external:
        slug_val = row["slug"]
        url = row["image_url"]
        ext = ext_for_url(url)
        local_filename = f"{slug_val}{ext}"
        dest = Path(images_dir) / local_filename
        local_db_path = f"/images/posts/{local_filename}"

        # Skip if already on disk (idempotent)
        if dest.exists():
            log.info("skip %s — already on disk", slug_val)
            if not dry_run:
                cur.execute(
                    "UPDATE posts SET image_url = %s, updated_at = NOW() WHERE slug = %s",
                    (local_db_path, slug_val),
                )
            skip += 1
            continue

        if download(url, dest, dry_run=dry_run):
            if not dry_run:
                cur.execute(
                    "UPDATE posts SET image_url = %s, updated_at = NOW() WHERE slug = %s",
                    (local_db_path, slug_val),
                )
                log.info("updated DB: %s → %s", slug_val, local_db_path)
            ok += 1
            time.sleep(0.2)  # gentle rate limiting
        else:
            fail += 1

    if not dry_run:
        conn.commit()
    conn.close()

    log.info("done — localized: %d, already local: %d, failed: %d", ok, skip, fail)
    if fail > 0:
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Localize external post images to disk")
    parser.add_argument("--slug", help="Process a single post slug")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without executing")
    parser.add_argument("--images-dir", default=DEFAULT_IMAGES_DIR, help="Local images directory")
    args = parser.parse_args()

    localize(slug=args.slug, dry_run=args.dry_run, images_dir=args.images_dir)


if __name__ == "__main__":
    main()
