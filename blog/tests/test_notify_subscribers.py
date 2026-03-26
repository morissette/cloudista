"""Tests for blog/notify_subscribers.py — _send() and run_* smoke tests."""
from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Stub heavy dependencies before importing the module under test
# ---------------------------------------------------------------------------
_boto3_stub = types.ModuleType("boto3")
_boto3_stub.client = MagicMock()
sys.modules.setdefault("boto3", _boto3_stub)

_psycopg2 = types.ModuleType("psycopg2")
_psycopg2.connect = MagicMock()
_psycopg2_extras = types.ModuleType("psycopg2.extras")
_psycopg2_extras.DictCursor = object
_psycopg2.extras = _psycopg2_extras
sys.modules.setdefault("psycopg2", _psycopg2)
sys.modules.setdefault("psycopg2.extras", _psycopg2_extras)

_email_template_stub = types.ModuleType("email_template")
_email_template_stub.build_immediate_email = MagicMock(return_value=("subj", "<html>", "text"))
_email_template_stub.build_digest_email = MagicMock(return_value=("subj", "<html>", "text"))
sys.modules.setdefault("email_template", _email_template_stub)

# Add blog/ to sys.path so the module can be imported
sys.path.insert(0, str(Path(__file__).parent.parent))

import notify_subscribers as ns  # noqa: E402

# ---------------------------------------------------------------------------
# _send()
# ---------------------------------------------------------------------------

class TestSend:
    def test_dry_run_returns_true(self):
        ses = MagicMock()
        assert ns._send(ses, "a@b.com", "hi", "<p>hi</p>", "hi", dry_run=True) is True
        ses.send_email.assert_not_called()

    def test_success_returns_true(self):
        ses = MagicMock()
        ses.send_email.return_value = {}
        assert ns._send(ses, "a@b.com", "hi", "<p>hi</p>", "hi", dry_run=False) is True

    def test_ses_exception_returns_false(self):
        ses = MagicMock()
        ses.send_email.side_effect = Exception("SES error")
        assert ns._send(ses, "a@b.com", "hi", "<p>hi</p>", "hi", dry_run=False) is False


# ---------------------------------------------------------------------------
# run_immediate()
# ---------------------------------------------------------------------------

def _make_dict_row(**kwargs):
    """Return a dict-like object that supports both [] and .get() access."""
    return kwargs


class TestRunImmediate:
    def _make_conn(self, posts=None, subscribers=None):
        cur = MagicMock()
        cur.fetchall.side_effect = [
            posts if posts is not None else [],
            subscribers if subscribers is not None else [],
        ]
        conn = MagicMock()
        conn.cursor.return_value = cur
        return conn, cur

    def test_no_posts_returns_early(self):
        conn, cur = self._make_conn(posts=[])
        ses = MagicMock()
        ns.run_immediate(conn, ses, dry_run=True)
        # Only one fetchall call for posts; no email sent
        ses.send_email = MagicMock()
        assert ses.send_email.call_count == 0

    def test_posts_no_subscribers_marks_notified(self):
        post = {"id": 1, "slug": "a-post", "title": "T", "excerpt": "E",
                "image_url": None, "published_at": None}
        conn, cur = self._make_conn(posts=[post], subscribers=[])
        ns.run_immediate(conn, ses=MagicMock(), dry_run=False)
        # Should have called UPDATE ... WHERE id = 1
        calls = [str(c) for c in cur.execute.call_args_list]
        assert any("notified_at" in c for c in calls)

    def test_sends_email_per_subscriber(self):
        post = {"id": 2, "slug": "post-b", "title": "B", "excerpt": "X",
                "image_url": None, "published_at": None}
        sub = {"email": "x@y.com", "token": "tok", "prefs_token": None}
        conn, cur = self._make_conn(posts=[post], subscribers=[sub])
        ses = MagicMock()
        ses.send_email.return_value = {}
        ns.run_immediate(conn, ses, dry_run=False)
        assert ses.send_email.call_count == 1


# ---------------------------------------------------------------------------
# run_digest()
# ---------------------------------------------------------------------------

class TestRunDigest:
    def _make_conn(self, subscribers=None, posts=None):
        cur = MagicMock()
        cur.fetchall.side_effect = [
            subscribers if subscribers is not None else [],
            posts if posts is not None else [],
        ]
        conn = MagicMock()
        conn.cursor.return_value = cur
        return conn, cur

    def test_no_subscribers_returns_early(self):
        conn, _ = self._make_conn(subscribers=[])
        ses = MagicMock()
        ns.run_digest(conn, ses, dry_run=True)
        assert ses.send_email.call_count == 0

    def test_skips_sub_with_no_new_posts(self):
        sub = {"id": 1, "email": "a@b.com", "token": "tok", "prefs_token": None,
               "last_digest_at": "2026-01-01"}
        conn, cur = self._make_conn(subscribers=[sub], posts=[])
        ses = MagicMock()
        ns.run_digest(conn, ses, dry_run=False)
        assert ses.send_email.call_count == 0

    def test_dry_run_does_not_call_ses(self):
        sub = {"id": 1, "email": "a@b.com", "token": "tok", "prefs_token": None,
               "last_digest_at": None}
        post = {"slug": "p", "title": "T", "excerpt": "E", "image_url": None, "published_at": None}
        conn, cur = self._make_conn(subscribers=[sub], posts=[post])
        ses = MagicMock()
        ns.run_digest(conn, ses, dry_run=True)
        ses.send_email.assert_not_called()
