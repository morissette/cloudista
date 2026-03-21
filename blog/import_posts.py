#!/usr/bin/env python3
"""
Import all .txt blog posts into the cloudista PostgreSQL database.

Each .txt file has a metadata header followed by a separator line,
then Markdown body content. Converts Markdown → HTML using Python-Markdown
with fenced_code, codehilite, tables, and extra extensions.
"""

import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import markdown
import psycopg2

# ── Config ────────────────────────────────────────────────────────────────────

BLOG_DIR = Path(__file__).parent
_DEFAULT_DSN = "postgresql://cloudista:cloudista_dev@localhost:5433/cloudista"
DB_DSN = os.environ.get("POPULATE_DB_DSN", _DEFAULT_DSN)
if DB_DSN == _DEFAULT_DSN:
    print("Warning: using default dev DSN — set POPULATE_DB_DSN for production", file=sys.stderr)

MD_EXTENSIONS = [
    "fenced_code",
    "codehilite",
    "tables",
    "extra",
    "nl2br",
    "sane_lists",
    "toc",
]

MD_EXTENSION_CONFIGS = {
    "codehilite": {
        "css_class": "highlight",
        "linenums": False,
        "guess_lang": False,
    },
    "toc": {
        "toc_depth": "2-4",
    },
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def parse_post_file(path: Path):
    """
    Parse a .txt post file into a dict with keys:
    title, author, date, original_url, slug, content_md, content_html, excerpt
    """
    text = path.read_text(encoding="utf-8")

    # Split header from body at the separator line
    sep = "=" * 60
    if sep in text:
        header_block, body = text.split(sep, 1)
    else:
        # No separator — treat everything as body, pull title from first line
        header_block = ""
        body = text

    # Parse header key: value pairs
    header = {}
    for line in header_block.splitlines():
        if ":" in line:
            key, _, val = line.partition(":")
            header[key.strip().lower()] = val.strip()

    title        = header.get("title", path.stem.replace("-", " ").title())
    author_name  = header.get("author", "Marie H.")
    date_str     = header.get("date", "")
    original_url = header.get("url", "")
    image_url    = header.get("image", "") or None

    # Parse date
    published_at = None
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%B %d, %Y"):
        try:
            published_at = datetime.strptime(date_str, fmt).replace(
                tzinfo=timezone.utc
            )
            break
        except ValueError:
            pass

    # Build slug from filename (strip leading date portion if present)
    # e.g. "2014-08-bash-loops" → "bash-loops"
    filename_stem = path.stem
    slug_match = re.match(r"^\d{4}-\d{2}-(.+)$", filename_stem)
    slug = slug_match.group(1) if slug_match else filename_stem

    # Clean body: strip leading/trailing whitespace
    content_md = body.strip()

    # Convert to HTML
    md = markdown.Markdown(
        extensions=MD_EXTENSIONS,
        extension_configs=MD_EXTENSION_CONFIGS,
    )
    content_html = md.convert(content_md)

    # Excerpt: first non-empty, non-heading paragraph (up to 300 chars)
    excerpt = _extract_excerpt(content_md)

    return {
        "title":        title,
        "author_name":  author_name,
        "slug":         slug,
        "content_md":   content_md,
        "content_html": content_html,
        "excerpt":      excerpt,
        "original_url": original_url or None,
        "image_url":    image_url,
        "published_at": published_at,
        "status":       "published" if published_at else "draft",
    }


def _extract_excerpt(md_text: str, max_len: int = 300) -> str:
    """Pull the first prose paragraph, stripping Markdown syntax."""
    for line in md_text.splitlines():
        line = line.strip()
        # Skip headings, code fences, blank lines, list markers, blockquotes
        if not line:
            continue
        if re.match(r"^(#+|```|>|\*\*|[-*]|\d+\.)", line):
            continue
        # Strip inline markdown
        clean = re.sub(r"[`*_\[\]()!]", "", line)
        clean = re.sub(r"https?://\S+", "", clean).strip()
        if len(clean) > 20:
            return clean[:max_len].rstrip() + ("…" if len(clean) > max_len else "")
    return ""


# ── Import ────────────────────────────────────────────────────────────────────

def import_posts(blog_dir: Path, dsn: str, dry_run: bool = False):
    txt_files = sorted(blog_dir.glob("*.txt"))
    print(f"Found {len(txt_files)} post files")

    conn = psycopg2.connect(dsn)
    cur  = conn.cursor()

    # Cache author_id map
    cur.execute("SELECT name, id FROM authors")
    author_map = {row[0]: row[1] for row in cur.fetchall()}

    inserted = 0
    updated  = 0
    errors   = []

    for path in txt_files:
        try:
            post = parse_post_file(path)
        except Exception as e:
            errors.append((path.name, str(e)))
            continue

        author_id = author_map.get(post["author_name"])
        if author_id is None:
            # Insert unknown author on the fly
            cur.execute(
                "INSERT INTO authors (name, email) VALUES (%s, %s) RETURNING id",
                (post["author_name"], f"{post['author_name'].lower().replace(' ', '.')}@cloudista.org"),
            )
            author_id = cur.fetchone()[0]
            author_map[post["author_name"]] = author_id

        if dry_run:
            print(f"  [dry] {path.name} → slug={post['slug']!r}")
            continue

        try:
            cur.execute(
                """
                INSERT INTO posts
                    (title, slug, content_md, content_html, excerpt,
                     author_id, status, original_url, image_url, published_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (slug) DO UPDATE SET
                    title        = EXCLUDED.title,
                    content_md   = EXCLUDED.content_md,
                    content_html = EXCLUDED.content_html,
                    excerpt      = EXCLUDED.excerpt,
                    original_url = EXCLUDED.original_url,
                    image_url    = EXCLUDED.image_url,
                    published_at = EXCLUDED.published_at,
                    status       = EXCLUDED.status,
                    updated_at   = NOW()
                RETURNING (xmax = 0) AS is_insert
                """,
                (
                    post["title"],
                    post["slug"],
                    post["content_md"],
                    post["content_html"],
                    post["excerpt"],
                    author_id,
                    post["status"],
                    post["original_url"],
                    post["image_url"],
                    post["published_at"],
                ),
            )
            row = cur.fetchone()
            conn.commit()
            if row[0]:
                inserted += 1
                print(f"  + {path.name}")
            else:
                updated += 1
                print(f"  ~ {path.name} (updated)")
        except Exception as e:
            conn.rollback()
            errors.append((path.name, str(e)))
            print(f"  ✗ {path.name}: {e}", file=sys.stderr)
            continue

    cur.close()
    conn.close()

    print(f"\n{'─'*50}")
    print(f"Inserted : {inserted}")
    print(f"Updated  : {updated}")
    if errors:
        print(f"Errors   : {len(errors)}")
        for name, msg in errors:
            print(f"  {name}: {msg}")
    return len(errors) == 0


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    ok = import_posts(BLOG_DIR, DB_DSN, dry_run=dry_run)
    sys.exit(0 if ok else 1)
