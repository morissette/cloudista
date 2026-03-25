"""
Blog API Routes
---------------
GET /api/blog/posts              – paginated list of published posts
GET /api/blog/posts/{slug}       – single post by slug
GET /api/blog/tags               – all tags
GET /api/blog/categories         – all categories
"""

import datetime as _dt
import html as _html
import json as _json
import logging
from email.utils import format_datetime as _fmt_dt

import asyncpg
from config import settings
from dependencies import get_pg_conn, limiter
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response
from schemas import CategoryOut, MessageOut, PostDetail, PostList, PostRevisionOut, PostSummary, TagOut

log = logging.getLogger(__name__)


# ── Router ────────────────────────────────────────────────────────────────────

router = APIRouter(prefix="/api", tags=["blog"])


@router.get("/search", response_model=PostList)
@limiter.limit("30/minute")
async def search_posts(
    request: Request,
    q: str = Query(..., min_length=2, max_length=200),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    conn: asyncpg.Connection = Depends(get_pg_conn),
):
    """Full-text search across post titles and excerpts."""
    offset = (page - 1) * per_page
    term = f"%{q}%"

    try:
        total = await conn.fetchval(
            "SELECT COUNT(*) FROM posts p JOIN authors a ON a.id = p.author_id"
            " WHERE p.status = 'published' AND p.published_at <= NOW()"
            " AND (p.title ILIKE $1 OR p.excerpt ILIKE $1 OR p.slug ILIKE $1)",
            term,
        )
        rows = await conn.fetch(
            "SELECT p.id, p.uuid::text, p.title, p.slug, p.excerpt,"
            " p.image_url, a.name AS author, p.published_at"
            " FROM posts p JOIN authors a ON a.id = p.author_id"
            " WHERE p.status = 'published' AND p.published_at <= NOW()"
            " AND (p.title ILIKE $1 OR p.excerpt ILIKE $1 OR p.slug ILIKE $1)"
            " ORDER BY p.published_at DESC LIMIT $2 OFFSET $3",
            term,
            per_page,
            offset,
        )
    except asyncpg.PostgresError as exc:
        log.error("search_posts error: %s", exc)
        raise HTTPException(status_code=500, detail="Search failed.")

    return PostList(
        posts=[PostSummary(**dict(row)) for row in rows],
        total=total,
        page=page,
        per_page=per_page,
        pages=(-(-total // per_page)),
    )


@router.get("/posts", response_model=PostList)
async def list_posts(
    response: Response,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    tag: str | None = Query(default=None),
    category: str | None = Query(default=None),
    conn: asyncpg.Connection = Depends(get_pg_conn),
):
    """
    Return a paginated list of published posts, newest first.
    Optionally filter by ?tag=slug or ?category=slug.
    """
    response.headers["Cache-Control"] = "public, max-age=60, stale-while-revalidate=300"
    offset = (page - 1) * per_page

    base_select = """
        SELECT p.id, p.uuid::text, p.title, p.slug, p.excerpt,
               p.image_url, a.name AS author, p.published_at
        FROM   posts p
        JOIN   authors a ON a.id = p.author_id
    """
    base_count = "SELECT COUNT(*) FROM posts p JOIN authors a ON a.id = p.author_id"

    filters = ["p.status = 'published'", "p.published_at <= NOW()"]
    join_extra = ""
    params: list = []
    n = 0

    if tag:
        n += 1
        join_extra += " JOIN post_tags pt ON pt.post_id = p.id JOIN tags t ON t.id = pt.tag_id"
        filters.append(f"t.slug = ${n}")
        params.append(tag)

    if category:
        n += 1
        join_extra += (
            " JOIN post_categories pc ON pc.post_id = p.id"
            " JOIN categories c ON c.id = pc.category_id"
        )
        filters.append(f"c.slug = ${n}")
        params.append(category)

    where = " WHERE " + " AND ".join(filters)

    try:
        total = await conn.fetchval(base_count + join_extra + where, *params)
        rows = await conn.fetch(
            base_select + join_extra + where
            + f" ORDER BY p.published_at DESC LIMIT ${n + 1} OFFSET ${n + 2}",
            *params,
            per_page,
            offset,
        )
    except asyncpg.PostgresError as exc:
        log.error("list_posts error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to fetch posts.")

    return PostList(
        posts=[PostSummary(**dict(row)) for row in rows],
        total=total,
        page=page,
        per_page=per_page,
        pages=(-(-total // per_page)),  # ceiling division
    )


@router.get("/posts/{slug}", response_model=PostDetail)
async def get_post(slug: str, conn: asyncpg.Connection = Depends(get_pg_conn)):
    """Return a single published post with full HTML content, tags, and categories."""
    try:
        row = await conn.fetchrow(
            "SELECT p.id, p.uuid::text, p.title, p.slug, p.excerpt,"
            " p.image_url, p.image_credit, p.content_html,"
            " a.name AS author, p.published_at"
            " FROM posts p JOIN authors a ON a.id = p.author_id"
            " WHERE p.slug = $1 AND p.status = 'published' AND p.published_at <= NOW()",
            slug,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Post not found.")

        tags = [
            r["slug"]
            for r in await conn.fetch(
                "SELECT t.slug FROM tags t JOIN post_tags pt ON pt.tag_id = t.id"
                " WHERE pt.post_id = $1 ORDER BY t.name",
                row["id"],
            )
        ]
        categories = [
            r["slug"]
            for r in await conn.fetch(
                "SELECT c.slug FROM categories c JOIN post_categories pc ON pc.category_id = c.id"
                " WHERE pc.post_id = $1 ORDER BY c.name",
                row["id"],
            )
        ]

    except HTTPException:
        raise
    except asyncpg.PostgresError as exc:
        log.error("get_post(%s) error: %s", slug, exc)
        raise HTTPException(status_code=500, detail="Failed to fetch post.")

    return PostDetail(**dict(row), tags=tags, categories=categories)


@router.get("/posts/{slug}/related", response_model=list[PostSummary])
async def related_posts(
    slug: str,
    limit: int = Query(default=4, ge=1, le=10),
    conn: asyncpg.Connection = Depends(get_pg_conn),
):
    """Return up to `limit` published posts most related to the given slug,
    ranked by shared category + tag overlap."""
    try:
        post = await conn.fetchrow(
            "SELECT id FROM posts WHERE slug = $1 AND status = 'published' AND published_at <= NOW()",
            slug,
        )
        if not post:
            raise HTTPException(status_code=404, detail="Post not found.")
        post_id = post["id"]

        rows = await conn.fetch(
            """
            SELECT p.id, p.uuid::text, p.title, p.slug, p.excerpt,
                   p.image_url, a.name AS author, p.published_at
            FROM   posts p
            JOIN   authors a ON a.id = p.author_id
            LEFT JOIN post_categories pc2
                   ON pc2.post_id = p.id
                  AND pc2.category_id IN (
                        SELECT category_id FROM post_categories WHERE post_id = $1
                      )
            LEFT JOIN post_tags pt2
                   ON pt2.post_id = p.id
                  AND pt2.tag_id IN (
                        SELECT tag_id FROM post_tags WHERE post_id = $2
                      )
            WHERE  p.status = 'published'
              AND  p.published_at <= NOW()
              AND  p.id != $3
              AND  (pc2.category_id IS NOT NULL OR pt2.tag_id IS NOT NULL)
            GROUP  BY p.id, p.uuid, p.title, p.slug, p.excerpt, p.image_url, a.name, p.published_at
            ORDER  BY COUNT(DISTINCT pc2.category_id) + COUNT(DISTINCT pt2.tag_id) DESC,
                      p.published_at DESC
            LIMIT  $4
            """,
            post_id,
            post_id,
            post_id,
            limit,
        )
    except HTTPException:
        raise
    except asyncpg.PostgresError as exc:
        log.error("related_posts(%s) error: %s", slug, exc)
        raise HTTPException(status_code=500, detail="Failed to fetch related posts.")

    return [PostSummary(**dict(r)) for r in rows]


@router.get("/posts/{slug}/revisions", response_model=list[PostRevisionOut])
async def list_revisions(slug: str, conn: asyncpg.Connection = Depends(get_pg_conn)):
    """Return revision history for a post (newest first). Empty list if no revisions exist."""
    try:
        post = await conn.fetchrow("SELECT id FROM posts WHERE slug = $1", slug)
        if not post:
            raise HTTPException(status_code=404, detail="Post not found.")
        rows = await conn.fetch(
            "SELECT id, title, excerpt, revised_at FROM post_revisions"
            " WHERE post_id = $1 ORDER BY revised_at DESC",
            post["id"],
        )
    except HTTPException:
        raise
    except asyncpg.PostgresError as exc:
        log.error("list_revisions(%s) error: %s", slug, exc)
        raise HTTPException(status_code=500, detail="Failed to fetch revisions.")
    return [PostRevisionOut(**dict(r)) for r in rows]


@router.post("/posts/{slug}/revisions/{revision_id}/restore", response_model=MessageOut)
async def restore_revision(
    slug: str,
    revision_id: int,
    request: Request,
    conn: asyncpg.Connection = Depends(get_pg_conn),
):
    """Restore a previous revision. Snapshots the current version before overwriting."""
    if not settings.admin_key:
        raise HTTPException(status_code=503, detail="Revert not configured.")
    if request.headers.get("X-Admin-Key") != settings.admin_key:
        raise HTTPException(status_code=403, detail="Forbidden.")
    try:
        post = await conn.fetchrow("SELECT id FROM posts WHERE slug = $1", slug)
        if not post:
            raise HTTPException(status_code=404, detail="Post not found.")
        rev = await conn.fetchrow(
            "SELECT id, title, content_md, content_html, excerpt FROM post_revisions"
            " WHERE id = $1 AND post_id = $2",
            revision_id,
            post["id"],
        )
        if not rev:
            raise HTTPException(status_code=404, detail="Revision not found.")
        async with conn.transaction():
            await conn.execute(
                "INSERT INTO post_revisions (post_id, title, content_md, content_html, excerpt)"
                " SELECT id, title, content_md, content_html, excerpt FROM posts WHERE id = $1",
                post["id"],
            )
            await conn.execute(
                "UPDATE posts SET title=$1, content_md=$2, content_html=$3, excerpt=$4,"
                " updated_at=NOW() WHERE id=$5",
                rev["title"], rev["content_md"], rev["content_html"], rev["excerpt"], post["id"],
            )
    except HTTPException:
        raise
    except asyncpg.PostgresError as exc:
        log.error("restore_revision(%s, %d) error: %s", slug, revision_id, exc)
        raise HTTPException(status_code=500, detail="Failed to restore revision.")
    return MessageOut(message="Revision restored.")


@router.get("/tags", response_model=list[TagOut])
async def list_tags(conn: asyncpg.Connection = Depends(get_pg_conn)):
    """Return all tags that have at least one published post."""
    try:
        rows = await conn.fetch(
            """
            SELECT DISTINCT t.id, t.name, t.slug
            FROM   tags t
            JOIN   post_tags pt ON pt.tag_id = t.id
            JOIN   posts p      ON p.id = pt.post_id
            WHERE  p.status = 'published' AND p.published_at <= NOW()
            ORDER  BY t.name
            """
        )
        return [TagOut(**dict(r)) for r in rows]
    except asyncpg.PostgresError as exc:
        log.error("list_tags error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to fetch tags.")


@router.get("/categories", response_model=list[CategoryOut])
async def list_categories(response: Response, conn: asyncpg.Connection = Depends(get_pg_conn)):
    """Return all categories that have at least one published post."""
    response.headers["Cache-Control"] = "public, max-age=300, stale-while-revalidate=3600"
    try:
        rows = await conn.fetch(
            """
            SELECT DISTINCT c.id, c.name, c.slug, c.description, c.parent_id
            FROM   categories c
            JOIN   post_categories pc ON pc.category_id = c.id
            JOIN   posts p            ON p.id = pc.post_id
            WHERE  p.status = 'published' AND p.published_at <= NOW()
            ORDER  BY c.name
            """
        )
        return [CategoryOut(**dict(r)) for r in rows]
    except asyncpg.PostgresError as exc:
        log.error("list_categories error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to fetch categories.")


# ── Sitemap ────────────────────────────────────────────────────────────────────

_SITE_ROOT = "https://cloudista.org"

_SITEMAP_STATIC = [
    {"loc": f"{_SITE_ROOT}/", "priority": "1.0", "changefreq": "daily"},
]


def _xml_escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


@router.get("/sitemap.xml", include_in_schema=False)
async def sitemap(conn: asyncpg.Connection = Depends(get_pg_conn)):
    """Dynamically generate sitemap.xml from all published posts."""
    try:
        posts = await conn.fetch(
            "SELECT slug, published_at AS lastmod"
            " FROM posts WHERE status = 'published' AND published_at <= NOW()"
            " ORDER BY published_at DESC"
        )
    except asyncpg.PostgresError as exc:
        log.error("sitemap error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to generate sitemap.")

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]

    for entry in _SITEMAP_STATIC:
        lines.append("  <url>")
        lines.append(f"    <loc>{entry['loc']}</loc>")
        lines.append(f"    <changefreq>{entry['changefreq']}</changefreq>")
        lines.append(f"    <priority>{entry['priority']}</priority>")
        lines.append("  </url>")

    for row in posts:
        loc = f"{_SITE_ROOT}/blog/{_xml_escape(row['slug'])}"
        lastmod = row["lastmod"]
        lastmod_str = lastmod.strftime("%Y-%m-%d") if lastmod else ""
        lines.append("  <url>")
        lines.append(f"    <loc>{loc}</loc>")
        if lastmod_str:
            lines.append(f"    <lastmod>{lastmod_str}</lastmod>")
        lines.append("    <changefreq>monthly</changefreq>")
        lines.append("    <priority>0.7</priority>")
        lines.append("  </url>")

    lines.append("</urlset>")

    return Response(
        content="\n".join(lines),
        media_type="application/xml",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.get("/feed.xml", include_in_schema=False)
async def rss_feed(conn: asyncpg.Connection = Depends(get_pg_conn)):
    """RSS 2.0 feed of the 20 most recent published posts."""

    def _rfc2822(dt) -> str:
        if not dt:
            return ""
        if not isinstance(dt, _dt.datetime):
            dt = _dt.datetime(dt.year, dt.month, dt.day, tzinfo=_dt.timezone.utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_dt.timezone.utc)
        return _fmt_dt(dt, usegmt=True)

    try:
        posts = await conn.fetch(
            "SELECT slug, title, excerpt, published_at"
            " FROM posts WHERE status = 'published' AND published_at <= NOW()"
            " ORDER BY published_at DESC LIMIT 20"
        )
    except asyncpg.PostgresError as exc:
        log.error("rss_feed error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to generate RSS feed.")

    now_rfc = _rfc2822(_dt.datetime.now(_dt.timezone.utc))
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">',
        "  <channel>",
        "    <title>Cloudista</title>",
        f"    <link>{_SITE_ROOT}</link>",
        "    <description>Cloud infrastructure, DevOps, and platform engineering from the field.</description>",
        "    <language>en-us</language>",
        f"    <lastBuildDate>{now_rfc}</lastBuildDate>",
        f'    <atom:link href="{_SITE_ROOT}/feed.xml" rel="self" type="application/rss+xml"/>',
    ]
    for row in posts:
        link = f"{_SITE_ROOT}/blog/{_xml_escape(row['slug'])}"
        lines += [
            "    <item>",
            f"      <title>{_xml_escape(row['title'] or '')}</title>",
            f"      <link>{link}</link>",
            f"      <description>{_xml_escape(row['excerpt'] or '')}</description>",
            f"      <pubDate>{_rfc2822(row['published_at'])}</pubDate>",
            f'      <guid isPermaLink="true">{link}</guid>',
            "    </item>",
        ]
    lines += ["  </channel>", "</rss>"]

    return Response(
        content="\n".join(lines),
        media_type="application/rss+xml",
        headers={"Cache-Control": "public, max-age=1800"},
    )


# ── Server-rendered post pages (for SEO / Googlebot) ──────────────────────────

html_router = APIRouter(tags=["blog"])

_GOOGLE_FONTS_URL = (
    "https://fonts.googleapis.com/css2?family=Inter:opsz,wght"
    "@14..32,400;14..32,500;14..32,600;14..32,700;14..32,800;14..32,900"
    "&family=JetBrains+Mono:wght@500&display=optional"
)

_POST_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title_escaped} — Cloudista</title>
  <meta name="description" content="{desc_escaped}">
  <link rel="canonical" href="{post_url_escaped}">

  <meta property="og:type"        content="article">
  <meta property="og:url"         content="{post_url_escaped}">
  <meta property="og:title"       content="{title_escaped}">
  <meta property="og:description" content="{desc_escaped}">
  <meta property="og:image"       content="{og_image_escaped}">
  <meta name="twitter:card"        content="summary_large_image">
  <meta name="twitter:title"       content="{title_escaped}">
  <meta name="twitter:description" content="{desc_escaped}">
  <meta name="twitter:image"       content="{og_image_escaped}">

  <script type="application/ld+json">{json_ld}</script>

  <link rel="icon"             href="/favicon.svg"          type="image/svg+xml">
  <link rel="icon"             href="/favicon.ico"          sizes="any">
  <link rel="icon"             href="/favicon-32x32.png"    type="image/png" sizes="32x32">
  <link rel="apple-touch-icon" href="/apple-touch-icon.png" sizes="180x180">
  <link rel="manifest"         href="/site.webmanifest">

  <link rel="alternate" type="application/rss+xml" title="Cloudista RSS Feed" href="/feed.xml">
  <link rel="preload" as="style" href="/style.css">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link rel="preload" href="{google_fonts_url}" as="style" onload="this.onload=null;this.rel='stylesheet'">
  <noscript><link href="{google_fonts_url}" rel="stylesheet"></noscript>
  <link rel="stylesheet" href="/style.css">
  <!-- Privacy-friendly analytics by Plausible -->
  <script async src="https://plausible.io/js/pa-GZSLQ84Mu1WZS1xQ0tHRs.js"></script>
  <script>window.plausible=window.plausible||function(){{(plausible.q=plausible.q||[]).push(arguments)}},plausible.init=plausible.init||function(i){{plausible.o=i||{{}}}};plausible.init()</script>
</head>
<body>

  <div class="confirm-banner" id="confirm-banner" role="alert" aria-live="polite"></div>

  <header class="site-header">
    <div class="container site-header__inner">
      <a href="/" class="logo" aria-label="Cloudista — home">
        <div class="logo__mark" aria-hidden="true">
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none"
               stroke="currentColor" stroke-width="2.5"
               stroke-linecap="round" stroke-linejoin="round">
            <path d="M18 10h-1.26A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10z"/>
          </svg>
        </div>
        Cloudista
      </a>
      <nav class="site-nav" aria-label="Site navigation">
        <a href="/feed.xml" class="nav-rss" aria-label="RSS feed">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
            <circle cx="6.18" cy="17.82" r="2.18"/>
            <path d="M4 4.44v2.83c7.03 0 12.73 5.7 12.73 12.73h2.83
              c0-8.59-6.97-15.56-15.56-15.56zm0 5.66v2.83c3.9 0 7.07
              3.17 7.07 7.07h2.83c0-5.47-4.43-9.9-9.9-9.9z"/>
          </svg>
          RSS
        </a>
        <button class="nav-subscribe" id="subscribe-btn" type="button">Subscribe</button>
      </nav>
    </div>
  </header>

  <main class="post-page" id="main-content">
    <div class="container">

      <a href="/" class="post-back" aria-label="Back to Blog">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
             stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <polyline points="15 18 9 12 15 6"/>
        </svg>
        Blog
      </a>

      <div id="post-content" data-prerendered="true" data-slug="{slug_escaped}">
        <header class="post-header" id="post-header">
          <div class="post-header__meta" id="post-meta">
            <span>{pub_date_display_escaped}</span>
            <span aria-hidden="true">·</span>
            <span>{author_escaped}</span>
          </div>
          <h1 class="post-header__title" id="post-title">{title_escaped}</h1>
        </header>
        {hero_html}
        <article class="post-body" id="post-body">{content_html}</article>
        <aside class="related-posts" id="related-posts" hidden></aside>
      </div>

    </div>
  </main>

  <footer class="site-footer">
    <div class="container site-footer__inner">
      <p class="site-footer__copy">© 2026 Cloudista. All rights reserved.</p>
      <nav class="site-footer__links" aria-label="Footer links">
        <a href="mailto:admin@cloudista.org">Contact</a>
        <a href="/privacy.html" rel="noopener noreferrer">Privacy</a>
        <a href="/terms.html"   rel="noopener noreferrer">Terms</a>
      </nav>
    </div>
  </footer>

  <div class="subscribe-modal" id="subscribe-modal"
       role="dialog" aria-modal="true" aria-labelledby="modal-title" hidden>
    <div class="subscribe-modal__backdrop" id="modal-backdrop"></div>
    <div class="subscribe-modal__dialog">
      <button class="subscribe-modal__close" id="modal-close" aria-label="Close dialog">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none"
             stroke="currentColor" stroke-width="2.5"
             stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
        </svg>
      </button>
      <h2 class="subscribe-modal__title" id="modal-title">Stay in the loop</h2>
      <p class="subscribe-modal__desc">Get new posts delivered to your inbox. No spam, ever.</p>
      <form class="signup-form" id="subscribe-form" novalidate>
        <label for="subscribe-email" class="sr-only">Email address</label>
        <input type="email" id="subscribe-email" class="signup-form__input"
               placeholder="you@company.com" required autocomplete="email">
        <button type="submit" class="btn btn-primary" id="subscribe-submit">Subscribe</button>
        <div class="hp-field" aria-hidden="true">
          <label for="subscribe-website">Website</label>
          <input type="text" id="subscribe-website" name="website" tabindex="-1" autocomplete="off">
        </div>
      </form>
      <div id="subscribe-captcha-wrap" style="display:none;margin-top:.75rem;"></div>
      <div class="signup-success" id="subscribe-success" role="status" aria-live="polite">
        <span class="signup-success__icon" aria-hidden="true">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none"
               stroke="#059669" stroke-width="3"
               stroke-linecap="round" stroke-linejoin="round">
            <polyline points="20 6 9 17 4 12"/>
          </svg>
        </span>
        <span data-msg>Check your email — we've sent you a confirmation link.</span>
      </div>
      <p id="subscribe-error" style="display:none;margin-top:.5rem;font-size:.8rem;color:#dc2626;" role="alert"></p>
    </div>
  </div>

  <script src="/main.js" defer></script>
  <script src="/blog/blog.js" defer></script>
</body>
</html>"""


def _render_post_html(row: dict, tags: list, categories: list) -> str:
    e = _html.escape
    title = row.get("title") or ""
    slug = row.get("slug") or ""
    author = row.get("author") or "Marie H."
    excerpt = row.get("excerpt") or title
    c_html = row.get("content_html") or ""
    image = row.get("image_url") or ""
    credit = row.get("image_credit") or ""
    pub = row.get("published_at")

    post_url = f"https://cloudista.org/blog/{slug}"
    og_image = image if image else "https://cloudista.org/og-image.png"

    pub_date = pub.strftime("%Y-%m-%d") if pub else ""
    pub_date_display = f"{pub.strftime('%B')} {pub.day}, {pub.year}" if pub else ""

    json_ld = _json.dumps(
        {
            "@context": "https://schema.org",
            "@type": "BlogPosting",
            "headline": title,
            "description": excerpt,
            "datePublished": pub_date,
            "dateModified": pub_date,
            "author": {"@type": "Person", "name": author},
            "url": post_url,
            "publisher": {
                "@type": "Organization",
                "name": "Cloudista",
                "url": "https://cloudista.org",
            },
        },
        ensure_ascii=False,
    )

    if image:
        credit_html = (
            f'<p class="post-hero__credit" id="post-hero-credit">{credit}</p>'
            if credit
            else ""
        )
        hero_html = (
            f'<div class="post-hero" id="post-hero">'
            f'<img class="post-hero__img" id="post-hero-img"'
            f' src="{e(image)}" alt="{e(title)}" loading="eager" fetchpriority="high">'
            f"{credit_html}</div>"
        )
    else:
        hero_html = ""

    return _POST_HTML_TEMPLATE.format(
        title_escaped=e(title),
        desc_escaped=e(excerpt),
        post_url_escaped=e(post_url),
        og_image_escaped=e(og_image),
        slug_escaped=e(slug),
        pub_date_display_escaped=e(pub_date_display),
        author_escaped=e(author),
        json_ld=json_ld,
        hero_html=hero_html,
        content_html=c_html,
        google_fonts_url=_GOOGLE_FONTS_URL,
    )


@html_router.get("/blog/{slug}", response_class=HTMLResponse, include_in_schema=False)
async def render_post_page(slug: str, conn: asyncpg.Connection = Depends(get_pg_conn)):
    """Return a server-rendered HTML page for a blog post (SEO / crawlers)."""
    try:
        row = await conn.fetchrow(
            "SELECT p.id, p.title, p.slug, p.excerpt,"
            " p.image_url, p.image_credit, p.content_html,"
            " a.name AS author, p.published_at"
            " FROM posts p JOIN authors a ON a.id = p.author_id"
            " WHERE p.slug = $1 AND p.status = 'published' AND p.published_at <= NOW()",
            slug,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Post not found.")

        tags = [
            r["slug"]
            for r in await conn.fetch(
                "SELECT t.slug FROM tags t JOIN post_tags pt ON pt.tag_id = t.id"
                " WHERE pt.post_id = $1 ORDER BY t.name",
                row["id"],
            )
        ]
        categories = [
            r["slug"]
            for r in await conn.fetch(
                "SELECT c.slug FROM categories c JOIN post_categories pc ON pc.category_id = c.id"
                " WHERE pc.post_id = $1 ORDER BY c.name",
                row["id"],
            )
        ]

    except HTTPException:
        raise
    except asyncpg.PostgresError as exc:
        log.error("render_post_page(%s) error: %s", slug, exc)
        raise HTTPException(status_code=500)

    return HTMLResponse(
        content=_render_post_html(dict(row), tags, categories),
        headers={"Cache-Control": "public, max-age=600, must-revalidate"},
    )
