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
