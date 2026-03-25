#!/usr/bin/env python3
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
    --fix-ext     Rename misnamed files (e.g. WebP saved as .jpg) and update DB
"""

from __future__ import annotations

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

# Map HTTP Content-Type to file extension
_MIME_EXT = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}

# Magic bytes to detect actual image format
_MAGIC = {
    b"RIFF": ".webp",   # WebP: RIFF....WEBP
    b"\x89PNG": ".png",
    b"\xff\xd8\xff": ".jpg",
    b"GIF8": ".gif",
}


def is_external(url: str) -> bool:
    return url.startswith("http://") or url.startswith("https://")


def detect_ext(data: bytes, content_type: str = "") -> str:
    """Detect image format from magic bytes, falling back to Content-Type."""
    for magic, ext in _MAGIC.items():
        if data[:len(magic)] == magic:
            return ext
    ct = content_type.split(";")[0].strip().lower()
    return _MIME_EXT.get(ct, ".jpg")


def ext_for_url(url: str) -> str:
    """Guess file extension from URL path, defaulting to .jpg."""
    path = url.split("?")[0].split("#")[0]
    suffix = Path(path).suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        return suffix if suffix != ".jpeg" else ".jpg"
    return ".jpg"


def download(url: str, dest: Path, dry_run: bool = False) -> str | None:
    """Download url to dest. Returns actual extension used (may differ from dest suffix)."""
    if dry_run:
        log.info("[dry-run] would download %s → %s", url, dest)
        return dest.suffix
    try:
        headers = {"User-Agent": "cloudista-image-localizer/1.0"}
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read()
            content_type = resp.headers.get("Content-Type", "")

        actual_ext = detect_ext(data, content_type)

        # If the actual format differs from the planned extension, use correct path
        if actual_ext != dest.suffix:
            correct_dest = dest.with_suffix(actual_ext)
            log.warning(
                "content is %s not %s — saving as %s",
                actual_ext, dest.suffix, correct_dest.name,
            )
            dest = correct_dest

        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        log.info("downloaded → %s (%d bytes)", dest, dest.stat().st_size)
        return actual_ext
    except Exception as exc:
        log.warning("failed to download %s: %s", url, exc)
        return None


def fix_extensions(images_dir: str, dry_run: bool, conn) -> None:
    """Rename files whose extension doesn't match their actual format and update DB."""
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    fixed = 0
    for f in sorted(Path(images_dir).glob("*")):
        if not f.is_file():
            continue
        data = f.read_bytes()
        if not data:
            continue
        actual_ext = detect_ext(data)
        if actual_ext == f.suffix.lower():
            continue

        new_path = f.with_suffix(actual_ext)
        new_db_path = f"/images/posts/{new_path.name}"
        old_db_path = f"/images/posts/{f.name}"

        log.info("fix: %s → %s", f.name, new_path.name)
        if not dry_run:
            f.rename(new_path)
            cur.execute(
                "UPDATE posts SET image_url = %s, updated_at = NOW() WHERE image_url = %s",
                (new_db_path, old_db_path),
            )
            log.info("  DB: %s → %s (rows: %d)", old_db_path, new_db_path, cur.rowcount)
        fixed += 1

    if not dry_run:
        conn.commit()
    log.info("fix-ext done — %d files renamed", fixed)


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

        # Skip if already on disk (idempotent) — but verify extension is correct
        if dest.exists():
            data = dest.read_bytes()
            actual_ext = detect_ext(data)
            if actual_ext != dest.suffix.lower():
                # File exists but has wrong extension — fix it
                correct_dest = dest.with_suffix(actual_ext)
                new_db_path = f"/images/posts/{correct_dest.name}"
                log.warning("fixing ext: %s → %s", dest.name, correct_dest.name)
                if not dry_run:
                    dest.rename(correct_dest)
                    cur.execute(
                        "UPDATE posts SET image_url = %s, updated_at = NOW() WHERE slug = %s",
                        (new_db_path, slug_val),
                    )
            else:
                local_db_path = f"/images/posts/{local_filename}"
                log.info("skip %s — already on disk", slug_val)
                if not dry_run:
                    cur.execute(
                        "UPDATE posts SET image_url = %s, updated_at = NOW() WHERE slug = %s",
                        (local_db_path, slug_val),
                    )
            skip += 1
            continue

        actual_ext = download(url, dest, dry_run=dry_run)
        if actual_ext is not None:
            correct_name = f"{slug_val}{actual_ext}"
            local_db_path = f"/images/posts/{correct_name}"
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
    parser.add_argument("--fix-ext", action="store_true",
                        help="Scan images-dir, rename files with wrong extension, update DB")
    args = parser.parse_args()

    if args.fix_ext:
        conn = psycopg2.connect(DB_DSN)
        conn.autocommit = False
        fix_extensions(args.images_dir, args.dry_run, conn)
        conn.close()
    else:
        localize(slug=args.slug, dry_run=args.dry_run, images_dir=args.images_dir)


if __name__ == "__main__":
    main()
