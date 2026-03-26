"""Tests for scripts/localize_images.py — pure functions and download logic."""
from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

# Stub psycopg2 before importing
_psycopg2 = types.ModuleType("psycopg2")
_psycopg2.connect = MagicMock()
_psycopg2_extras = types.ModuleType("psycopg2.extras")
_psycopg2_extras.RealDictCursor = object
_psycopg2.extras = _psycopg2_extras
sys.modules.setdefault("psycopg2", _psycopg2)
sys.modules.setdefault("psycopg2.extras", _psycopg2_extras)

sys.path.insert(0, str(Path(__file__).parent.parent))

import localize_images as li  # noqa: E402


class TestIsExternal:
    def test_https_url(self):
        assert li.is_external("https://example.com/img.jpg") is True

    def test_http_url(self):
        assert li.is_external("http://example.com/img.jpg") is True

    def test_local_path(self):
        assert li.is_external("/images/posts/foo.jpg") is False

    def test_relative_path(self):
        assert li.is_external("images/posts/foo.jpg") is False


class TestDetectExt:
    def test_png_magic(self):
        data = b"\x89PNG" + b"\x00" * 100
        assert li.detect_ext(data) == ".png"

    def test_jpeg_magic(self):
        data = b"\xff\xd8\xff" + b"\x00" * 100
        assert li.detect_ext(data) == ".jpg"

    def test_webp_magic(self):
        data = b"RIFF" + b"\x00" * 100
        assert li.detect_ext(data) == ".webp"

    def test_gif_magic(self):
        data = b"GIF8" + b"\x00" * 100
        assert li.detect_ext(data) == ".gif"

    def test_falls_back_to_content_type(self):
        data = b"\x00\x00\x00\x00"  # unknown magic
        assert li.detect_ext(data, "image/png") == ".png"

    def test_defaults_to_jpg(self):
        data = b"\x00\x00\x00\x00"
        assert li.detect_ext(data, "") == ".jpg"


class TestExtForUrl:
    def test_jpg(self):
        assert li.ext_for_url("https://cdn.example.com/photo.jpg?w=900") == ".jpg"

    def test_jpeg_normalised(self):
        assert li.ext_for_url("https://cdn.example.com/photo.jpeg") == ".jpg"

    def test_png(self):
        assert li.ext_for_url("https://cdn.example.com/photo.png") == ".png"

    def test_webp(self):
        assert li.ext_for_url("https://cdn.example.com/photo.webp") == ".webp"

    def test_no_extension_defaults_jpg(self):
        assert li.ext_for_url("https://images.unsplash.com/photo-123") == ".jpg"

    def test_unknown_extension_defaults_jpg(self):
        assert li.ext_for_url("https://example.com/photo.bmp") == ".jpg"


class TestDownload:
    def test_dry_run_returns_suffix(self, tmp_path):
        dest = tmp_path / "foo.jpg"
        result = li.download("https://example.com/img.jpg", dest, dry_run=True)
        assert result == ".jpg"
        assert not dest.exists()

    def test_successful_download(self, tmp_path):
        dest = tmp_path / "foo.jpg"
        fake_data = b"\xff\xd8\xff" + b"\x00" * 50  # JPEG magic

        class FakeResp:
            def read(self):
                return fake_data
            def __enter__(self):
                return self
            def __exit__(self, *a):
                pass
            headers = {"Content-Type": "image/jpeg"}

        with patch("urllib.request.urlopen", return_value=FakeResp()):
            result = li.download("https://example.com/img.jpg", dest, dry_run=False)

        assert result == ".jpg"
        assert dest.exists()
        assert dest.read_bytes() == fake_data

    def test_failed_download_returns_none(self, tmp_path):
        dest = tmp_path / "foo.jpg"
        with patch("urllib.request.urlopen", side_effect=OSError("timeout")):
            result = li.download("https://example.com/img.jpg", dest, dry_run=False)
        assert result is None
        assert not dest.exists()
