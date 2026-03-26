"""
Tests for GET /api/posts/{slug}/revisions
and POST /api/posts/{slug}/revisions/{id}/restore
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    with patch("dependencies.init_pool", new_callable=AsyncMock), \
         patch("dependencies.close_pool", new_callable=AsyncMock):
        from dependencies import get_pg_conn
        from main import app

        mock_conn = AsyncMock()

        async def override_get_pg_conn():
            yield mock_conn

        app.dependency_overrides[get_pg_conn] = override_get_pg_conn
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c, mock_conn
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# GET /api/posts/{slug}/revisions
# ---------------------------------------------------------------------------

class TestListRevisions:
    def test_returns_revisions(self, client):
        c, conn = client
        conn.fetchrow = AsyncMock(return_value={"id": 1})
        conn.fetch = AsyncMock(return_value=[_revision_row()])

        resp = c.get("/api/posts/my-post/revisions")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["id"] == 1
        assert data[0]["title"] == "Old Title"

    def test_unknown_slug_returns_404(self, client):
        c, conn = client
        conn.fetchrow = AsyncMock(return_value=None)

        resp = c.get("/api/posts/no-such-post/revisions")
        assert resp.status_code == 404

    def test_no_revisions_returns_empty_list(self, client):
        c, conn = client
        conn.fetchrow = AsyncMock(return_value={"id": 1})
        conn.fetch = AsyncMock(return_value=[])

        resp = c.get("/api/posts/new-post/revisions")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_db_error_returns_500(self, client):
        import sys
        asyncpg_mod = sys.modules["asyncpg"]
        c, conn = client
        conn.fetchrow = AsyncMock(side_effect=asyncpg_mod.PostgresError())

        resp = c.get("/api/posts/error-post/revisions")
        assert resp.status_code == 500


# ---------------------------------------------------------------------------
# POST /api/posts/{slug}/revisions/{id}/restore
# ---------------------------------------------------------------------------

class TestRestoreRevision:
    def test_restore_success_returns_200(self, client):
        c, conn = client
        conn.fetchrow = AsyncMock(side_effect=[{"id": 1}, _revision_row(with_content=True)])
        conn.execute = AsyncMock(return_value=None)
        conn.transaction = MagicMock(return_value=_async_cm())

        with patch("blog_routes.settings") as mock_settings:
            mock_settings.admin_key = "secret"
            resp = c.post(
                "/api/posts/my-post/revisions/1/restore",
                headers={"X-Admin-Key": "secret"},
            )
        assert resp.status_code == 200
        assert "restored" in resp.json()["message"].lower()

    def test_missing_admin_key_returns_403(self, client):
        c, conn = client
        with patch("blog_routes.settings") as mock_settings:
            mock_settings.admin_key = "secret"
            resp = c.post("/api/posts/my-post/revisions/1/restore")
        assert resp.status_code == 403

    def test_wrong_admin_key_returns_403(self, client):
        c, conn = client
        with patch("blog_routes.settings") as mock_settings:
            mock_settings.admin_key = "secret"
            resp = c.post(
                "/api/posts/my-post/revisions/1/restore",
                headers={"X-Admin-Key": "wrong"},
            )
        assert resp.status_code == 403

    def test_admin_key_not_configured_returns_403(self, client):
        c, conn = client
        with patch("blog_routes.settings") as mock_settings:
            mock_settings.admin_key = ""
            resp = c.post(
                "/api/posts/my-post/revisions/1/restore",
                headers={"X-Admin-Key": "anything"},
            )
        assert resp.status_code == 403

    def test_unknown_slug_returns_404(self, client):
        c, conn = client
        conn.fetchrow = AsyncMock(return_value=None)

        with patch("blog_routes.settings") as mock_settings:
            mock_settings.admin_key = "secret"
            resp = c.post(
                "/api/posts/no-such-post/revisions/1/restore",
                headers={"X-Admin-Key": "secret"},
            )
        assert resp.status_code == 404

    def test_unknown_revision_returns_404(self, client):
        c, conn = client
        conn.fetchrow = AsyncMock(side_effect=[{"id": 1}, None])

        with patch("blog_routes.settings") as mock_settings:
            mock_settings.admin_key = "secret"
            resp = c.post(
                "/api/posts/my-post/revisions/999/restore",
                headers={"X-Admin-Key": "secret"},
            )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _revision_row(with_content: bool = False, **kwargs):
    from datetime import datetime, timezone
    defaults = {
        "id": 1,
        "title": "Old Title",
        "excerpt": "Old excerpt",
        "revised_at": datetime(2026, 3, 1, tzinfo=timezone.utc),
    }
    if with_content:
        defaults.update({
            "content_md": "# Old content",
            "content_html": "<h1>Old content</h1>",
        })
    defaults.update(kwargs)
    return defaults


class _AsyncCM:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


def _async_cm():
    return _AsyncCM()
