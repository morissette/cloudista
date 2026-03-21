"""Tests for email_template.py — no external deps required."""
from email_template import build_verification_email

CONFIRM_URL = "https://cloudista.org/api/confirm/abc123"
UNSUB_URL = "https://cloudista.org/api/unsubscribe/abc123"


# ── Happy path ─────────────────────────────────────────────────────────────────

def test_returns_three_parts():
    result = build_verification_email(CONFIRM_URL, UNSUB_URL)
    assert len(result) == 3


def test_subject():
    subject, _, _ = build_verification_email(CONFIRM_URL, UNSUB_URL)
    assert "Confirm" in subject
    assert "Cloudista" in subject


def test_html_contains_confirm_url():
    _, html, _ = build_verification_email(CONFIRM_URL, UNSUB_URL)
    assert CONFIRM_URL in html


def test_html_contains_unsubscribe_url():
    _, html, _ = build_verification_email(CONFIRM_URL, UNSUB_URL)
    assert UNSUB_URL in html


def test_text_contains_confirm_url():
    _, _, text = build_verification_email(CONFIRM_URL, UNSUB_URL)
    assert CONFIRM_URL in text


def test_text_contains_unsubscribe_url():
    _, _, text = build_verification_email(CONFIRM_URL, UNSUB_URL)
    assert UNSUB_URL in text


def test_html_is_valid_doctype():
    _, html, _ = build_verification_email(CONFIRM_URL, UNSUB_URL)
    assert html.strip().startswith("<!DOCTYPE html>")


def test_html_mentions_72_hours():
    _, html, _ = build_verification_email(CONFIRM_URL, UNSUB_URL)
    assert "72" in html


def test_text_mentions_72_hours():
    _, _, text = build_verification_email(CONFIRM_URL, UNSUB_URL)
    assert "72" in text


# ── Edge cases ─────────────────────────────────────────────────────────────────

def test_special_characters_in_url_survive():
    """URLs with query strings and special chars should appear verbatim."""
    url = "https://cloudista.org/api/confirm/tok%2Bwith+special&chars=1"
    _, html, text = build_verification_email(url, UNSUB_URL)
    assert url in html
    assert url in text


def test_different_confirm_and_unsub_tokens():
    confirm = "https://cloudista.org/api/confirm/token-A"
    unsub = "https://cloudista.org/api/unsubscribe/token-A"
    _, html, text = build_verification_email(confirm, unsub)
    assert confirm in html
    assert unsub in html
    assert confirm in text
    assert unsub in text
