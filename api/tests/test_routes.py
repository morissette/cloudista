"""
Integration-style tests for API routes using FastAPI's TestClient.
The database dependency is mocked so no real PostgreSQL connection is needed.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# App bootstrap — patch pool init so no real DB is needed at import time
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client():
    """TestClient with DB pool dependency overridden to return a mock connection."""
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
# Health
# ---------------------------------------------------------------------------

class TestHealth:
    def test_always_200(self, client):
        c, _ = client
        with patch("dependencies._pg_pool", None):
            resp = c.get("/api/health")
        assert resp.status_code == 200

    def test_db_unavailable_when_pool_none(self, client):
        c, _ = client
        with patch("dependencies._pg_pool", None):
            resp = c.get("/api/health")
        data = resp.json()
        assert data["db"] == "unavailable"
        assert data["status"] == "ok"

    def test_response_has_required_fields(self, client):
        c, _ = client
        with patch("dependencies._pg_pool", None):
            resp = c.get("/api/health")
        data = resp.json()
        assert "status" in data
        assert "db" in data


# ---------------------------------------------------------------------------
# Prometheus metrics endpoint
# ---------------------------------------------------------------------------

class TestMetrics:
    def test_metrics_returns_200(self, client):
        c, _ = client
        resp = c.get("/metrics")
        assert resp.status_code == 200

    def test_metrics_content_type_is_text(self, client):
        c, _ = client
        resp = c.get("/metrics")
        assert "text/plain" in resp.headers["content-type"]

    def test_metrics_contains_http_requests_counter(self, client):
        c, _ = client
        resp = c.get("/metrics")
        assert "http_requests" in resp.text or "http_request" in resp.text

    def test_metrics_contains_post_gauges(self, client):
        c, _ = client
        resp = c.get("/metrics")
        assert "cloudista_posts_published_total" in resp.text
        assert "cloudista_posts_unlisted_total" in resp.text
        assert "cloudista_posts_total" in resp.text

    def test_metrics_contains_post_views_db_gauge(self, client):
        c, _ = client
        resp = c.get("/metrics")
        assert "cloudista_post_views_db_total" in resp.text

    def test_seed_post_view_metrics_increments_counter(self):
        """_seed_post_view_metrics pre-seeds the counter from DB rows."""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch

        from blog_routes import _counter_post_views
        from main import _seed_post_view_metrics

        fake_rows = [
            {"slug": "my-post", "country": "US", "is_bot": False, "total": 42},
            {"slug": "my-post", "country": "CA", "is_bot": True,  "total": 3},
        ]
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(side_effect=[fake_rows, []])  # seed query, then gauge query
        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_conn),
            __aexit__=AsyncMock(return_value=False),
        ))

        with patch("main._pg_pool", mock_pool, create=True), \
             patch("dependencies._pg_pool", mock_pool):
            asyncio.run(_seed_post_view_metrics())

        val = _counter_post_views.labels(slug="my-post", country="US", is_bot="False")._value.get()
        assert val >= 42


# ---------------------------------------------------------------------------
# Subscribe — pass paths
# ---------------------------------------------------------------------------

class TestSubscribePass:
    def test_new_subscriber_returns_201(self, client):
        c, conn = client
        conn.fetchrow = AsyncMock(return_value=None)
        conn.execute = AsyncMock(return_value=None)
        conn.transaction = MagicMock(return_value=_async_cm())

        with patch("main._try_send_verification", new_callable=AsyncMock):
            resp = c.post("/api/subscribe", json={"email": "new@example.com"})
        assert resp.status_code == 201
        assert "Check your email" in resp.json()["message"]

    def test_already_confirmed_returns_200(self, client):
        c, conn = client
        conn.fetchrow = AsyncMock(return_value=_row(status="confirmed"))
        conn.transaction = MagicMock(return_value=_async_cm())

        resp = c.post("/api/subscribe", json={"email": "confirmed@example.com"})
        assert resp.status_code == 200
        assert "confirmed" in resp.json()["message"].lower()

    def test_pending_resend_returns_200(self, client):
        c, conn = client
        conn.fetchrow = AsyncMock(return_value=_row(status="pending", token="tok"))
        conn.execute = AsyncMock(return_value=None)
        conn.transaction = MagicMock(return_value=_async_cm())

        with patch("main._try_send_verification", new_callable=AsyncMock):
            resp = c.post("/api/subscribe", json={"email": "pending@example.com"})
        assert resp.status_code == 200
        assert "resent" in resp.json()["message"].lower()

    def test_unsubscribed_resubscribe_returns_200(self, client):
        c, conn = client
        conn.fetchrow = AsyncMock(return_value=_row(status="unsubscribed", token="tok"))
        conn.execute = AsyncMock(return_value=None)
        conn.transaction = MagicMock(return_value=_async_cm())

        with patch("main._try_send_verification", new_callable=AsyncMock):
            resp = c.post("/api/subscribe", json={"email": "unsub@example.com"})
        assert resp.status_code == 200
        assert "re-subscribed" in resp.json()["message"].lower()


# ---------------------------------------------------------------------------
# Subscribe — fail paths
# ---------------------------------------------------------------------------

class TestSubscribeFail:
    def test_missing_email_returns_422(self, client):
        c, _ = client
        resp = c.post("/api/subscribe", json={})
        assert resp.status_code == 422

    def test_invalid_email_returns_422(self, client):
        c, _ = client
        resp = c.post("/api/subscribe", json={"email": "not-an-email"})
        assert resp.status_code == 422

    def test_invalid_source_returns_422(self, client):
        c, _ = client
        resp = c.post("/api/subscribe", json={"email": "a@b.com", "source": "unknown_source"})
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Turnstile CAPTCHA
# ---------------------------------------------------------------------------

class TestTurnstile:
    def test_invalid_token_returns_400(self, client):
        c, _ = client
        import main as _main
        with patch("main._verify_turnstile", new_callable=AsyncMock) as mock_verify, \
             patch.object(_main.settings, "turnstile_secret", "test-secret"):
            mock_verify.return_value = _main.TurnstileResult.INVALID
            resp = c.post(
                "/api/subscribe",
                json={"email": "a@b.com", "cf_turnstile_token": "bad-token"},
            )
        assert resp.status_code == 400
        assert "CAPTCHA" in resp.json()["detail"]

    def test_unavailable_captcha_allows_subscribe(self, client):
        c, conn = client
        conn.fetchrow = AsyncMock(return_value=None)
        conn.execute = AsyncMock(return_value=None)
        conn.transaction = MagicMock(return_value=_async_cm())

        import main as _main
        with patch("main._verify_turnstile", new_callable=AsyncMock) as mock_verify, \
             patch.object(_main.settings, "turnstile_secret", "test-secret"), \
             patch("main._try_send_verification", new_callable=AsyncMock):
            mock_verify.return_value = _main.TurnstileResult.UNAVAILABLE
            resp = c.post(
                "/api/subscribe",
                json={"email": "a@b.com", "cf_turnstile_token": "some-token"},
                headers={"X-Real-IP": "10.0.0.99"},
            )
        assert resp.status_code == 201

    def test_no_token_skips_captcha(self, client):
        c, conn = client
        conn.fetchrow = AsyncMock(return_value=None)
        conn.execute = AsyncMock(return_value=None)
        conn.transaction = MagicMock(return_value=_async_cm())

        with patch("main._try_send_verification", new_callable=AsyncMock):
            resp = c.post(
                "/api/subscribe",
                json={"email": "a@b.com"},
                headers={"X-Real-IP": "10.0.0.98"},
            )
        assert resp.status_code == 201


# ---------------------------------------------------------------------------
# Confirm
# ---------------------------------------------------------------------------

class TestConfirm:
    def test_valid_token_redirects_confirmed_true(self, client):
        c, conn = client
        from datetime import datetime, timedelta, timezone
        conn.fetchrow = AsyncMock(return_value=_row(
            status="pending",
            token_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        ))
        conn.execute = AsyncMock(return_value=None)
        conn.transaction = MagicMock(return_value=_async_cm())

        resp = c.get("/api/confirm/validtoken", follow_redirects=False)
        assert resp.status_code == 302
        assert "confirmed=1" in resp.headers["location"]

    def test_unknown_token_redirects_invalid(self, client):
        c, conn = client
        conn.fetchrow = AsyncMock(return_value=None)

        resp = c.get("/api/confirm/unknowntoken", follow_redirects=False)
        assert resp.status_code == 302
        assert "confirmed=invalid" in resp.headers["location"]

    def test_already_confirmed_redirects_already(self, client):
        c, conn = client
        conn.fetchrow = AsyncMock(return_value=_row(status="confirmed"))

        resp = c.get("/api/confirm/confirmedtoken", follow_redirects=False)
        assert resp.status_code == 302
        assert "confirmed=already" in resp.headers["location"]

    def test_expired_token_redirects_expired(self, client):
        c, conn = client
        from datetime import datetime, timedelta, timezone
        conn.fetchrow = AsyncMock(return_value=_row(
            status="pending",
            token_expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
        ))

        resp = c.get("/api/confirm/expiredtoken", follow_redirects=False)
        assert resp.status_code == 302
        assert "confirmed=expired" in resp.headers["location"]


# ---------------------------------------------------------------------------
# Unsubscribe
# ---------------------------------------------------------------------------

class TestUnsubscribe:
    def test_valid_token_redirects_true(self, client):
        c, conn = client
        conn.fetchrow = AsyncMock(return_value=_row(status="confirmed"))
        conn.execute = AsyncMock(return_value=None)
        conn.transaction = MagicMock(return_value=_async_cm())

        resp = c.get("/api/unsubscribe/validtoken", follow_redirects=False)
        assert resp.status_code == 302
        assert "unsubscribed=true" in resp.headers["location"]

    def test_unknown_token_redirects_invalid(self, client):
        c, conn = client
        conn.fetchrow = AsyncMock(return_value=None)

        resp = c.get("/api/unsubscribe/badtoken", follow_redirects=False)
        assert resp.status_code == 302
        assert "unsubscribed=invalid" in resp.headers["location"]

    def test_already_unsubscribed_redirects_already(self, client):
        c, conn = client
        conn.fetchrow = AsyncMock(return_value=_row(status="unsubscribed"))

        resp = c.get("/api/unsubscribe/token", follow_redirects=False)
        assert resp.status_code == 302
        assert "unsubscribed=already" in resp.headers["location"]


# ---------------------------------------------------------------------------
# SES webhook
# ---------------------------------------------------------------------------

class TestSesWebhook:
    def test_subscription_confirmation(self, client):
        c, _ = client
        with patch("main._verify_sns_signature", return_value=True), \
             patch("urllib.request.urlopen"):
            resp = c.post("/api/ses-webhook", json={
                "Type": "SubscriptionConfirmation",
                "SubscribeURL": "https://sns.us-east-1.amazonaws.com/confirm?token=abc",
                "TopicArn": "arn:aws:sns:us-east-1:123:cloudista-ses",
            })
        assert resp.status_code == 200
        assert resp.json()["status"] == "confirmed"

    def test_permanent_bounce_marks_unsubscribed(self, client):
        import json
        c, conn = client
        conn.execute = AsyncMock(return_value=None)
        conn.transaction = MagicMock(return_value=_async_cm())

        message = json.dumps({
            "notificationType": "Bounce",
            "bounce": {
                "bounceType": "Permanent",
                "bouncedRecipients": [{"emailAddress": "bounce@example.com"}],
            },
        })
        with patch("main._verify_sns_signature", return_value=True):
            resp = c.post("/api/ses-webhook", json={
                "Type": "Notification",
                "Message": message,
            })
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_complaint_marks_unsubscribed(self, client):
        import json
        c, conn = client
        conn.execute = AsyncMock(return_value=None)
        conn.transaction = MagicMock(return_value=_async_cm())

        message = json.dumps({
            "notificationType": "Complaint",
            "complaint": {
                "complainedRecipients": [{"emailAddress": "spam@example.com"}],
            },
        })
        with patch("main._verify_sns_signature", return_value=True):
            resp = c.post("/api/ses-webhook", json={
                "Type": "Notification",
                "Message": message,
            })
        assert resp.status_code == 200

    def test_transient_bounce_ignored(self, client):
        import json
        c, conn = client
        conn.execute.reset_mock()  # clear calls from earlier tests in this fixture scope
        message = json.dumps({
            "notificationType": "Bounce",
            "bounce": {
                "bounceType": "Transient",
                "bouncedRecipients": [{"emailAddress": "temp@example.com"}],
            },
        })
        with patch("main._verify_sns_signature", return_value=True):
            resp = c.post("/api/ses-webhook", json={
                "Type": "Notification",
                "Message": message,
            })
        assert resp.status_code == 200
        # No DB call for transient bounces
        conn.execute.assert_not_called()

    def test_invalid_signature_returns_400(self, client):
        c, _ = client
        with patch("main._verify_sns_signature", return_value=False):
            resp = c.post("/api/ses-webhook", json={
                "Type": "Notification",
                "Message": "{}",
            })
        assert resp.status_code == 400

    def test_invalid_json_returns_400(self, client):
        c, _ = client
        resp = c.post(
            "/api/ses-webhook",
            content=b"not json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 400

    def test_unknown_type_returns_ignored(self, client):
        c, _ = client
        # Signature is verified first; patch it so we can test the type-branch logic.
        with patch("main._verify_sns_signature", return_value=True):
            resp = c.post("/api/ses-webhook", json={"Type": "Unknown"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "ignored"


# ---------------------------------------------------------------------------
# Request-ID middleware
# ---------------------------------------------------------------------------

class TestRequestId:
    def test_returns_x_request_id_header(self, client):
        c, _ = client
        with patch("dependencies._pg_pool", None):
            resp = c.get("/api/health")
        assert "x-request-id" in resp.headers

    def test_echoes_provided_request_id(self, client):
        c, _ = client
        with patch("dependencies._pg_pool", None):
            resp = c.get("/api/health", headers={"X-Request-ID": "test-id-123"})
        assert resp.headers.get("x-request-id") == "test-id-123"


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

class TestSearch:
    def test_search_returns_results(self, client):
        c, conn = client
        conn.fetchval = AsyncMock(return_value=1)
        conn.fetch = AsyncMock(return_value=[_post_row()])

        resp = c.get("/api/search?q=kubernetes")
        assert resp.status_code == 200
        data = resp.json()
        assert "posts" in data
        assert data["total"] == 1

    def test_search_query_too_short_returns_422(self, client):
        c, _ = client
        resp = c.get("/api/search?q=a")
        assert resp.status_code == 422

    def test_search_query_too_long_returns_422(self, client):
        c, _ = client
        resp = c.get("/api/search?q=" + "x" * 201)
        assert resp.status_code == 422

    def test_search_empty_results(self, client):
        c, conn = client
        conn.fetchval = AsyncMock(return_value=0)
        conn.fetch = AsyncMock(return_value=[])

        resp = c.get("/api/search?q=nomatch")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0
        assert resp.json()["posts"] == []

    def test_search_pagination(self, client):
        c, conn = client
        conn.fetchval = AsyncMock(return_value=50)
        conn.fetch = AsyncMock(return_value=[_post_row()])

        resp = c.get("/api/search?q=devops&page=2&per_page=10")
        assert resp.status_code == 200
        data = resp.json()
        assert data["page"] == 2
        assert data["per_page"] == 10

    def test_search_db_error_returns_500(self, client):
        import sys
        asyncpg_mod = sys.modules["asyncpg"]
        c, conn = client
        conn.fetchval = AsyncMock(side_effect=asyncpg_mod.PostgresError())

        resp = c.get("/api/search?q=trigger-error")
        assert resp.status_code == 500


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

class TestRateLimiting:
    def test_subscribe_rate_limit_enforced(self, client):
        """6th request in the same minute should be rate-limited."""
        c, conn = client
        conn.fetchrow = AsyncMock(return_value=None)
        conn.execute = AsyncMock(return_value=None)
        conn.transaction = MagicMock(return_value=_async_cm())

        with patch("main._try_send_verification", new_callable=AsyncMock):
            responses = []
            for i in range(6):
                resp = c.post(
                    "/api/subscribe",
                    json={"email": f"rateuser{i}@example.com"},
                    headers={"X-Real-IP": "10.0.0.1"},
                )
                responses.append(resp.status_code)

        assert 429 in responses

    def test_search_rate_limit_enforced(self, client):
        """31st request in the same minute should be rate-limited."""
        c, conn = client
        conn.fetchval = AsyncMock(return_value=0)
        conn.fetch = AsyncMock(return_value=[])

        responses = []
        for _ in range(31):
            resp = c.get("/api/search?q=test", headers={"X-Real-IP": "10.0.0.2"})
            responses.append(resp.status_code)

        assert 429 in responses


# ---------------------------------------------------------------------------
# Preferences
# ---------------------------------------------------------------------------

class TestPreferences:
    def test_get_valid_token_returns_200(self, client):
        c, conn = client
        conn.fetchrow = AsyncMock(return_value=_prefs_row())

        resp = c.get("/api/preferences/validprefstoken")
        assert resp.status_code == 200
        assert "preferences" in resp.text.lower()

    def test_get_unknown_token_returns_error_page(self, client):
        c, conn = client
        conn.fetchrow = AsyncMock(return_value=None)

        resp = c.get("/api/preferences/badtoken")
        assert resp.status_code == 200  # HTML page, not 404
        assert "not found" in resp.text.lower()

    def test_post_valid_frequency_redirects(self, client):
        c, conn = client
        conn.execute = AsyncMock(return_value="UPDATE 1")

        resp = c.post(
            "/api/preferences/validtoken",
            data={"frequency": "immediate"},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert "saved=1" in resp.headers["location"]

    def test_post_weekly_frequency_redirects(self, client):
        c, conn = client
        conn.execute = AsyncMock(return_value="UPDATE 1")

        resp = c.post(
            "/api/preferences/validtoken",
            data={"frequency": "weekly"},
            follow_redirects=False,
        )
        assert resp.status_code == 303

    def test_post_invalid_frequency_returns_422(self, client):
        c, _ = client
        resp = c.post(
            "/api/preferences/validtoken",
            data={"frequency": "never"},
        )
        assert resp.status_code == 422

    def test_get_expired_token_returns_error_page(self, client):
        from datetime import datetime, timedelta, timezone
        c, conn = client
        conn.fetchrow = AsyncMock(return_value=_prefs_row(
            prefs_token_expires_at=datetime.now(timezone.utc) - timedelta(days=1),
        ))

        resp = c.get("/api/preferences/expiredtoken")
        assert resp.status_code == 200
        assert "expired" in resp.text.lower()

    def test_post_not_found_returns_404(self, client):
        c, conn = client
        conn.execute = AsyncMock(return_value="UPDATE 0")

        resp = c.post(
            "/api/preferences/unknowntoken",
            data={"frequency": "weekly"},
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# _mask_email helper
# ---------------------------------------------------------------------------

class TestMaskEmail:
    def test_normal_email(self):
        from main import _mask_email
        assert _mask_email("john@example.com") == "jo***@example.com"

    def test_short_local_part(self):
        from main import _mask_email
        assert _mask_email("a@example.com") == "a***@example.com"

    def test_invalid_email_returns_stars(self):
        from main import _mask_email
        assert _mask_email("notanemail") == "***"

    def test_preserves_domain(self):
        from main import _mask_email
        result = _mask_email("user@sub.domain.org")
        assert result.endswith("@sub.domain.org")
        assert "***" in result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _row(**kwargs):
    """Build a mock asyncpg Record-like dict with sensible defaults."""
    defaults = {
        "id": 1,
        "status": "pending",
        "token": "abc123def456",
        "token_expires_at": None,
        "prefs_token": "prefstoken123",
    }
    defaults.update(kwargs)
    return defaults


def _prefs_row(**kwargs):
    from datetime import datetime, timedelta, timezone
    defaults = {
        "id": 1,
        "email": "test@example.com",
        "frequency": "weekly",
        "token": "abc123def456",
        "prefs_token_expires_at": datetime.now(timezone.utc) + timedelta(days=365),
    }
    defaults.update(kwargs)
    return defaults


def _post_row(**kwargs):
    """Build a mock post row for blog route tests."""
    from datetime import datetime, timezone
    defaults = {
        "id": 1,
        "uuid": "00000000-0000-0000-0000-000000000001",
        "title": "Test Post",
        "slug": "test-post",
        "excerpt": "A test excerpt",
        "image_url": "https://images.unsplash.com/photo-test",
        "author": "Marie H.",
        "published_at": datetime(2026, 3, 20, tzinfo=timezone.utc),
    }
    defaults.update(kwargs)
    return defaults


class _AsyncCM:
    """Minimal async context manager for mocking conn.transaction()."""
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


def _async_cm():
    return _AsyncCM()
