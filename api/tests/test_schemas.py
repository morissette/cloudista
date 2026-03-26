"""Tests for Pydantic schemas — validation rules and edge cases."""
import pytest
from pydantic import ValidationError
from schemas import HealthOut, MessageOut, SubscribeIn, SubscribeSource

# ── SubscribeIn ────────────────────────────────────────────────────────────────

class TestSubscribeIn:
    def test_valid_minimal(self):
        s = SubscribeIn(email="user@example.com")
        assert s.email == "user@example.com"
        assert s.source == SubscribeSource.COMING_SOON
        assert s.cf_turnstile_token is None

    def test_valid_full(self):
        s = SubscribeIn(
            email="user@example.com",
            source="blog",
            cf_turnstile_token="tok123",
        )
        assert s.source == SubscribeSource.BLOG
        assert s.cf_turnstile_token == "tok123"

    def test_invalid_email(self):
        with pytest.raises(ValidationError) as exc_info:
            SubscribeIn(email="not-an-email")
        assert "email" in str(exc_info.value).lower()

    def test_empty_email(self):
        with pytest.raises(ValidationError):
            SubscribeIn(email="")

    def test_invalid_source_rejected(self):
        with pytest.raises(ValidationError):
            SubscribeIn(email="a@b.com", source="unknown_source")

    def test_all_valid_sources_accepted(self):
        for src in SubscribeSource:
            s = SubscribeIn(email="a@b.com", source=src.value)
            assert s.source == src

    def test_turnstile_token_max_length(self):
        with pytest.raises(ValidationError):
            SubscribeIn(email="a@b.com", cf_turnstile_token="x" * 2049)

    def test_turnstile_token_at_max_length(self):
        s = SubscribeIn(email="a@b.com", cf_turnstile_token="x" * 2048)
        assert len(s.cf_turnstile_token) == 2048

    def test_email_domain_normalised_lowercase(self):
        """EmailStr normalises the domain to lowercase (local-part case is preserved)."""
        s = SubscribeIn(email="User@Example.COM")
        assert s.email.endswith("@example.com")


# ── HealthOut ──────────────────────────────────────────────────────────────────

class TestHealthOut:
    def test_ok_no_error(self):
        h = HealthOut(status="ok", db="ok")
        assert h.db_error is None

    def test_ok_with_db_error(self):
        h = HealthOut(status="ok", db="unavailable", db_error="Connection failed")
        assert h.db_error == "Connection failed"

    def test_invalid_status(self):
        with pytest.raises(ValidationError):
            HealthOut(status="error", db="ok")

    def test_invalid_db(self):
        with pytest.raises(ValidationError):
            HealthOut(status="ok", db="degraded")


# ── MessageOut ─────────────────────────────────────────────────────────────────

class TestMessageOut:
    def test_basic(self):
        m = MessageOut(message="hello")
        assert m.message == "hello"

    def test_empty_message(self):
        m = MessageOut(message="")
        assert m.message == ""

    def test_missing_message(self):
        with pytest.raises(ValidationError):
            MessageOut()
