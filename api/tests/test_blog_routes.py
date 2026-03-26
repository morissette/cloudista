"""
Tests for blog API routes (/api/posts, /api/search, /api/tags, /api/categories).
DB dependency is mocked — no real PostgreSQL connection needed.
"""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

NOW = datetime(2026, 3, 25, 12, 0, 0, tzinfo=timezone.utc)

POST_ROW = {
    "id": 1,
    "uuid": "aaaaaaaa-0000-0000-0000-000000000001",
    "title": "Test Post",
    "slug": "test-post",
    "excerpt": "A test post excerpt.",
    "image_url": "/images/posts/test-post.jpg",
    "image_credit": None,
    "content_html": "<p>Hello world</p>",
    "author": "Marie H.",
    "published_at": NOW,
}

TAG_ROW = {"id": 1, "name": "Kubernetes", "slug": "kubernetes"}
CATEGORY_ROW = {"id": 1, "name": "DevOps", "slug": "devops", "description": None, "parent_id": None}


def _make_row(data: dict):
    """Return a MagicMock that behaves like an asyncpg Record for the given dict."""
    row = MagicMock()
    row.__getitem__ = lambda self, k: data[k]
    row.keys = lambda: data.keys()
    # Make dict(row) work
    row.__iter__ = lambda self: iter(data.keys())

    def _items():
        return data.items()

    # asyncpg Record supports dict(**row) via keys() + __getitem__
    # but FastAPI/Pydantic calls dict(row) which uses __iter__ + __getitem__
    # Simplest: make the mock quack like a mapping
    row._data = data
    return row


def _record(data: dict):
    """Build a minimal mapping-like object that works with dict(row)."""

    class _Rec:
        def __init__(self, d):
            self._d = d

        def __getitem__(self, k):
            return self._d[k]

        def keys(self):
            return self._d.keys()

        def items(self):
            return self._d.items()

        def __iter__(self):
            return iter(self._d)

    return _Rec(data)


@pytest.fixture(scope="module")
def blog_client():
    """TestClient wired up the same way as the subscriber route tests."""
    with patch("dependencies.init_pool", new_callable=AsyncMock), \
         patch("dependencies.close_pool", new_callable=AsyncMock):
        from dependencies import get_pg_conn
        from main import app

        mock_conn = AsyncMock()

        async def override():
            yield mock_conn

        app.dependency_overrides[get_pg_conn] = override
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c, mock_conn
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# _db_error() helper — unit tests (no routing needed)
# ---------------------------------------------------------------------------

class TestDbErrorHelper:
    def test_generic_error_returns_500(self):
        import asyncpg
        from blog_routes import _db_error
        exc = asyncpg.PostgresError("query error")
        result = _db_error(exc, "test")
        assert result.status_code == 500

    def test_transient_sqlstate_string_returns_503(self):
        import asyncpg
        from blog_routes import _db_error
        exc = asyncpg.PostgresError("too many connections")
        exc.sqlstate = "53300"
        result = _db_error(exc, "test")
        assert result.status_code == 503

    def test_transient_sqlstate_bytes_returns_503(self):
        import asyncpg
        from blog_routes import _db_error
        exc = asyncpg.PostgresError("connection failure")
        exc.sqlstate = b"08006"
        result = _db_error(exc, "test")
        assert result.status_code == 503

    def test_no_sqlstate_returns_500(self):
        import asyncpg
        from blog_routes import _db_error
        exc = asyncpg.PostgresError("unknown error")
        result = _db_error(exc, "test")
        assert result.status_code == 500


# ---------------------------------------------------------------------------
# /api/posts — list posts
# ---------------------------------------------------------------------------

class TestListPosts:
    def _setup_conn(self, mock_conn, rows=None, total=1):
        mock_conn.fetchval = AsyncMock(return_value=total)
        _rows = [POST_ROW] if rows is None else rows
        mock_conn.fetch = AsyncMock(return_value=[_record(r) for r in _rows])

    def test_returns_200_with_posts(self, blog_client):
        c, conn = blog_client
        self._setup_conn(conn)
        resp = c.get("/api/posts")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["page"] == 1
        assert len(data["posts"]) == 1
        assert data["posts"][0]["slug"] == "test-post"

    def test_pagination_defaults(self, blog_client):
        c, conn = blog_client
        self._setup_conn(conn, total=0, rows=[])
        resp = c.get("/api/posts")
        assert resp.status_code == 200
        data = resp.json()
        assert data["per_page"] == 20
        assert data["pages"] == 0

    def test_custom_page_and_per_page(self, blog_client):
        c, conn = blog_client
        self._setup_conn(conn, total=50)
        resp = c.get("/api/posts?page=2&per_page=10")
        assert resp.status_code == 200
        data = resp.json()
        assert data["page"] == 2
        assert data["per_page"] == 10

    def test_filter_by_category(self, blog_client):
        c, conn = blog_client
        self._setup_conn(conn)
        resp = c.get("/api/posts?category=devops")
        assert resp.status_code == 200

    def test_filter_by_tag(self, blog_client):
        c, conn = blog_client
        self._setup_conn(conn)
        resp = c.get("/api/posts?tag=kubernetes")
        assert resp.status_code == 200

    def test_db_error_returns_500(self, blog_client):
        import asyncpg
        c, conn = blog_client
        conn.fetchval = AsyncMock(side_effect=asyncpg.PostgresError("boom"))
        resp = c.get("/api/posts")
        assert resp.status_code == 500


    def test_empty_result(self, blog_client):
        c, conn = blog_client
        self._setup_conn(conn, rows=[], total=0)
        resp = c.get("/api/posts")
        assert resp.status_code == 200
        data = resp.json()
        assert data["posts"] == []
        assert data["total"] == 0
        assert data["pages"] == 0

    def test_per_page_max_100(self, blog_client):
        c, conn = blog_client
        self._setup_conn(conn)
        resp = c.get("/api/posts?per_page=200")
        assert resp.status_code == 422  # validation error

    def test_page_min_1(self, blog_client):
        c, conn = blog_client
        self._setup_conn(conn)
        resp = c.get("/api/posts?page=0")
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# /api/posts/{slug} — single post
# ---------------------------------------------------------------------------

class TestGetPost:
    def _setup_conn(self, mock_conn, row=None, tags=None, categories=None, missing=False):
        mock_conn.fetchrow = AsyncMock(return_value=None if missing else _record(row or POST_ROW))
        mock_conn.fetch = AsyncMock(side_effect=[
            [_record({"slug": t}) for t in (tags or [])],
            [_record({"slug": cat}) for cat in (categories or [])],
        ])

    def test_returns_post(self, blog_client):
        c, conn = blog_client
        self._setup_conn(conn, tags=["kubernetes"], categories=["devops"])
        resp = c.get("/api/posts/test-post")
        assert resp.status_code == 200
        data = resp.json()
        assert data["slug"] == "test-post"
        assert data["tags"] == ["kubernetes"]
        assert data["categories"] == ["devops"]

    def test_missing_slug_returns_404(self, blog_client):
        c, conn = blog_client
        self._setup_conn(conn, missing=True)
        resp = c.get("/api/posts/no-such-post")
        assert resp.status_code == 404

    def test_post_with_no_tags_or_categories(self, blog_client):
        c, conn = blog_client
        self._setup_conn(conn, tags=[], categories=[])
        resp = c.get("/api/posts/test-post")
        assert resp.status_code == 200
        data = resp.json()
        assert data["tags"] == []
        assert data["categories"] == []

    def test_db_error_returns_500(self, blog_client):
        import asyncpg
        c, conn = blog_client
        conn.fetchrow = AsyncMock(side_effect=asyncpg.PostgresError("db failure"))
        resp = c.get("/api/posts/test-post")
        assert resp.status_code == 500

    def test_content_html_present(self, blog_client):
        c, conn = blog_client
        self._setup_conn(conn)
        resp = c.get("/api/posts/test-post")
        assert resp.status_code == 200
        assert "<p>Hello world</p>" in resp.json()["content_html"]


# ---------------------------------------------------------------------------
# /api/search
# ---------------------------------------------------------------------------

class TestSearchPosts:
    def _setup_conn(self, mock_conn, rows=None, total=1):
        mock_conn.fetchval = AsyncMock(return_value=total)
        _rows = [POST_ROW] if rows is None else rows
        mock_conn.fetch = AsyncMock(return_value=[_record(r) for r in _rows])

    def test_basic_search(self, blog_client):
        c, conn = blog_client
        self._setup_conn(conn)
        resp = c.get("/api/search?q=kubernetes")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1

    def test_query_too_short_returns_422(self, blog_client):
        c, conn = blog_client
        resp = c.get("/api/search?q=k")
        assert resp.status_code == 422

    def test_query_required(self, blog_client):
        c, conn = blog_client
        resp = c.get("/api/search")
        assert resp.status_code == 422

    def test_empty_results(self, blog_client):
        c, conn = blog_client
        self._setup_conn(conn, rows=[], total=0)
        resp = c.get("/api/search?q=nothing")
        assert resp.status_code == 200
        assert resp.json()["posts"] == []

    def test_db_error_returns_500(self, blog_client):
        import asyncpg
        c, conn = blog_client
        conn.fetchval = AsyncMock(side_effect=asyncpg.PostgresError("boom"))
        resp = c.get("/api/search?q=kubernetes")
        assert resp.status_code == 500

    def test_pagination(self, blog_client):
        c, conn = blog_client
        self._setup_conn(conn, total=30)
        resp = c.get("/api/search?q=terraform&page=2&per_page=10")
        assert resp.status_code == 200
        data = resp.json()
        assert data["page"] == 2
        assert data["per_page"] == 10


# ---------------------------------------------------------------------------
# /api/tags
# ---------------------------------------------------------------------------

class TestListTags:
    def test_returns_tags(self, blog_client):
        c, conn = blog_client
        conn.fetch = AsyncMock(return_value=[_record(TAG_ROW)])
        resp = c.get("/api/tags")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["slug"] == "kubernetes"

    def test_empty_tags(self, blog_client):
        c, conn = blog_client
        conn.fetch = AsyncMock(return_value=[])
        resp = c.get("/api/tags")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_db_error_returns_500(self, blog_client):
        import asyncpg
        c, conn = blog_client
        conn.fetch = AsyncMock(side_effect=asyncpg.PostgresError("boom"))
        resp = c.get("/api/tags")
        assert resp.status_code == 500


# ---------------------------------------------------------------------------
# /api/categories
# ---------------------------------------------------------------------------

class TestListCategories:
    def test_returns_categories(self, blog_client):
        c, conn = blog_client
        conn.fetch = AsyncMock(return_value=[_record(CATEGORY_ROW)])
        resp = c.get("/api/categories")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["slug"] == "devops"

    def test_empty_categories(self, blog_client):
        c, conn = blog_client
        conn.fetch = AsyncMock(return_value=[])
        resp = c.get("/api/categories")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_db_error_returns_500(self, blog_client):
        import asyncpg
        c, conn = blog_client
        conn.fetch = AsyncMock(side_effect=asyncpg.PostgresError("boom"))
        resp = c.get("/api/categories")
        assert resp.status_code == 500


# ---------------------------------------------------------------------------
# /api/posts/{slug}/related
# ---------------------------------------------------------------------------

class TestRelatedPosts:
    def test_returns_related(self, blog_client):
        c, conn = blog_client
        conn.fetchrow = AsyncMock(return_value=_record({"id": 1}))
        conn.fetch = AsyncMock(return_value=[_record(POST_ROW)])
        resp = c.get("/api/posts/test-post/related")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_missing_post_returns_404(self, blog_client):
        c, conn = blog_client
        conn.fetchrow = AsyncMock(return_value=None)
        resp = c.get("/api/posts/no-such-post/related")
        assert resp.status_code == 404

    def test_limit_param(self, blog_client):
        c, conn = blog_client
        conn.fetchrow = AsyncMock(return_value=_record({"id": 1}))
        conn.fetch = AsyncMock(return_value=[])
        resp = c.get("/api/posts/test-post/related?limit=2")
        assert resp.status_code == 200

    def test_limit_max_10(self, blog_client):
        c, conn = blog_client
        resp = c.get("/api/posts/test-post/related?limit=99")
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# _is_bot() and _country() — unit tests (no routing needed)
# ---------------------------------------------------------------------------

class TestIsBotHelper:
    def test_known_bot_ua_returns_true(self):
        from blog_routes import _is_bot
        from fastapi.testclient import TestClient
        from unittest.mock import MagicMock

        req = MagicMock()
        req.headers.get = lambda k, d="": {
            "user-agent": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
        }.get(k, d)
        assert _is_bot(req) is True

    def test_gptbot_returns_true(self):
        from blog_routes import _is_bot
        from unittest.mock import MagicMock
        req = MagicMock()
        req.headers.get = lambda k, d="": {"user-agent": "GPTBot/1.0"}.get(k, d)
        assert _is_bot(req) is True

    def test_browser_ua_returns_false(self):
        from blog_routes import _is_bot
        from unittest.mock import MagicMock
        req = MagicMock()
        req.headers.get = lambda k, d="": {
            "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        }.get(k, d)
        assert _is_bot(req) is False

    def test_empty_ua_returns_false(self):
        from blog_routes import _is_bot
        from unittest.mock import MagicMock
        req = MagicMock()
        req.headers.get = lambda k, d="": d
        assert _is_bot(req) is False


class TestCountryHelper:
    def test_valid_country_code(self):
        from blog_routes import _country
        from unittest.mock import MagicMock
        req = MagicMock()
        req.headers.get = lambda k, d="XX": {"CF-IPCountry": "US"}.get(k, d)
        assert _country(req) == "US"

    def test_lowercase_is_uppercased(self):
        from blog_routes import _country
        from unittest.mock import MagicMock
        req = MagicMock()
        req.headers.get = lambda k, d="XX": {"CF-IPCountry": "gb"}.get(k, d)
        assert _country(req) == "GB"

    def test_missing_header_defaults_xx(self):
        from blog_routes import _country
        from unittest.mock import MagicMock
        req = MagicMock()
        req.headers.get = lambda k, d="XX": d
        assert _country(req) == "XX"

    def test_invalid_code_defaults_xx(self):
        from blog_routes import _country
        from unittest.mock import MagicMock
        req = MagicMock()
        req.headers.get = lambda k, d="XX": {"CF-IPCountry": "123"}.get(k, d)
        assert _country(req) == "XX"

    def test_too_long_code_defaults_xx(self):
        from blog_routes import _country
        from unittest.mock import MagicMock
        req = MagicMock()
        req.headers.get = lambda k, d="XX": {"CF-IPCountry": "USA"}.get(k, d)
        assert _country(req) == "XX"


# ---------------------------------------------------------------------------
# /api/posts/{slug}/stats — per-post view stats (admin only)
# ---------------------------------------------------------------------------

TOTALS_ROW = {"views_7d": 50, "views_30d": 150, "views_all": 500, "bot_views_all": 20}
DAILY_ROW  = {"viewed_on": __import__("datetime").date(2026, 3, 25), "views": 10, "bot_views": 1}
COUNTRY_ROW = {"country": "US", "views": 300}
POST_ID_ROW = {"id": 1, "title": "Test Post"}


class TestGetPostStats:
    def _setup_conn(self, mock_conn, missing=False):
        mock_conn.fetchrow = AsyncMock(side_effect=[
            None if missing else _record(POST_ID_ROW),
            _record(TOTALS_ROW),
        ])
        mock_conn.fetch = AsyncMock(side_effect=[
            [_record(DAILY_ROW)],
            [_record(COUNTRY_ROW)],
        ])

    def test_returns_stats(self, blog_client):
        c, conn = blog_client
        self._setup_conn(conn)
        resp = c.get("/api/posts/test-post/stats", headers={"X-Admin-Key": "test-admin-key"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["slug"] == "test-post"
        assert data["views_7d"] == 50
        assert data["views_all"] == 500
        assert data["bot_views_all"] == 20
        assert len(data["daily"]) == 1
        assert data["daily"][0]["views"] == 10
        assert len(data["top_countries"]) == 1
        assert data["top_countries"][0]["country"] == "US"

    def test_missing_post_returns_404(self, blog_client):
        c, conn = blog_client
        self._setup_conn(conn, missing=True)
        resp = c.get("/api/posts/no-such-post/stats", headers={"X-Admin-Key": "test-admin-key"})
        assert resp.status_code == 404

    def test_no_admin_key_returns_403(self, blog_client):
        c, conn = blog_client
        resp = c.get("/api/posts/test-post/stats")
        assert resp.status_code == 403

    def test_wrong_admin_key_returns_403(self, blog_client):
        c, conn = blog_client
        resp = c.get("/api/posts/test-post/stats", headers={"X-Admin-Key": "wrong-key"})
        assert resp.status_code == 403

    def test_db_error_returns_503_or_500(self, blog_client):
        import asyncpg
        c, conn = blog_client
        conn.fetchrow = AsyncMock(side_effect=asyncpg.PostgresError("boom"))
        resp = c.get("/api/posts/test-post/stats", headers={"X-Admin-Key": "test-admin-key"})
        assert resp.status_code in (500, 503)


# ---------------------------------------------------------------------------
# /api/stats — blog-wide view summary (admin only)
# ---------------------------------------------------------------------------

STATS_ROW = {
    "slug": "test-post", "title": "Test Post",
    "views_7d": 50, "views_30d": 150, "views_all": 500, "bot_views_all": 20,
}


class TestGetBlogStats:
    def _setup_conn(self, mock_conn, rows=None):
        _rows = [STATS_ROW] if rows is None else rows
        mock_conn.fetch = AsyncMock(return_value=[_record(r) for r in _rows])

    def test_returns_stats_list(self, blog_client):
        c, conn = blog_client
        self._setup_conn(conn)
        resp = c.get("/api/stats", headers={"X-Admin-Key": "test-admin-key"})
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert data[0]["slug"] == "test-post"
        assert data[0]["views_all"] == 500

    def test_no_admin_key_returns_403(self, blog_client):
        c, conn = blog_client
        resp = c.get("/api/stats")
        assert resp.status_code == 403

    def test_invalid_period_returns_422(self, blog_client):
        c, conn = blog_client
        resp = c.get("/api/stats?period=bad", headers={"X-Admin-Key": "test-admin-key"})
        assert resp.status_code == 422

    def test_period_7d(self, blog_client):
        c, conn = blog_client
        self._setup_conn(conn)
        resp = c.get("/api/stats?period=7d", headers={"X-Admin-Key": "test-admin-key"})
        assert resp.status_code == 200

    def test_period_all(self, blog_client):
        c, conn = blog_client
        self._setup_conn(conn)
        resp = c.get("/api/stats?period=all", headers={"X-Admin-Key": "test-admin-key"})
        assert resp.status_code == 200

    def test_include_bots_flag(self, blog_client):
        c, conn = blog_client
        self._setup_conn(conn)
        resp = c.get("/api/stats?include_bots=true", headers={"X-Admin-Key": "test-admin-key"})
        assert resp.status_code == 200

    def test_empty_result(self, blog_client):
        c, conn = blog_client
        self._setup_conn(conn, rows=[])
        resp = c.get("/api/stats", headers={"X-Admin-Key": "test-admin-key"})
        assert resp.status_code == 200
        assert resp.json() == []

    def test_limit_validation(self, blog_client):
        c, conn = blog_client
        resp = c.get("/api/stats?limit=0", headers={"X-Admin-Key": "test-admin-key"})
        assert resp.status_code == 422

    def test_db_error_returns_500_or_503(self, blog_client):
        import asyncpg
        c, conn = blog_client
        conn.fetch = AsyncMock(side_effect=asyncpg.PostgresError("boom"))
        resp = c.get("/api/stats", headers={"X-Admin-Key": "test-admin-key"})
        assert resp.status_code in (500, 503)
