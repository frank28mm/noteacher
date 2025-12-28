import sys
from types import SimpleNamespace

import pytest

from homework_agent.utils.url_image_helpers import (
    _download_as_data_uri,
    _first_public_image_url,
    _is_provider_image_fetch_issue,
    _is_public_url,
    _normalize_public_url,
    _probe_url_head,
    _strip_base64_prefix,
)


def test_is_public_url_rejects_localhost_and_non_http():
    assert _is_public_url("https://example.com/a.jpg") is True
    assert _is_public_url("http://example.com/a.jpg") is True
    assert _is_public_url("file:///tmp/a.jpg") is False
    assert _is_public_url("http://127.0.0.1/a.jpg") is False
    assert _is_public_url("https://localhost/a.jpg") is False


def test_normalize_public_url_strips_trailing_question_mark_and_whitespace():
    assert (
        _normalize_public_url("  https://example.com/a.jpg?  ")
        == "https://example.com/a.jpg"
    )
    assert _normalize_public_url("") is None
    assert _normalize_public_url(None) is None


def test_strip_base64_prefix_removes_data_url_prefix():
    assert _strip_base64_prefix("data:image/png;base64,ABC123") == "ABC123"
    assert _strip_base64_prefix("ABC123") == "ABC123"


def test_first_public_image_url_handles_dict_and_object():
    class ImgObj:
        def __init__(self, url: str):
            self.url = url

    imgs = [{"url": "https://a/b.jpg"}, ImgObj("https://c/d.jpg")]
    assert _first_public_image_url(imgs) == "https://a/b.jpg"


def test_is_provider_image_fetch_issue_detects_common_patterns():
    assert (
        _is_provider_image_fetch_issue(Exception("Timeout while fetching image_url"))
        is True
    )
    assert _is_provider_image_fetch_issue(Exception("20040 image_url")) is True
    assert _is_provider_image_fetch_issue(Exception("something else")) is False


def test_probe_url_head_uses_httpx_and_formats_output(monkeypatch: pytest.MonkeyPatch):
    class FakeResp:
        status_code = 200
        headers = {"content-type": "image/jpeg", "content-length": "123"}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def head(self, url: str):
            assert url == "https://example.com/a.jpg"
            return FakeResp()

    fake_httpx = SimpleNamespace(Client=FakeClient)
    monkeypatch.setitem(sys.modules, "httpx", fake_httpx)

    out = _probe_url_head("https://example.com/a.jpg")
    assert "status=200" in (out or "")
    assert "content-type=image/jpeg" in (out or "")


def test_download_as_data_uri_happy_path(monkeypatch: pytest.MonkeyPatch):
    class FakeResp:
        status_code = 200
        headers = {"content-type": "image/png"}
        content = b"\x89PNG\r\n\x1a\n"

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def get(self, url: str):
            assert url == "https://example.com/a.png"
            return FakeResp()

    fake_httpx = SimpleNamespace(Client=FakeClient)
    monkeypatch.setitem(sys.modules, "httpx", fake_httpx)

    out = _download_as_data_uri("https://example.com/a.png")
    assert out is not None
    assert out.startswith("data:image/png;base64,")


def test_download_as_data_uri_rejects_non_200(monkeypatch: pytest.MonkeyPatch):
    class FakeResp:
        status_code = 403
        headers = {"content-type": "image/jpeg"}
        content = b""

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def get(self, url: str):
            return FakeResp()

    fake_httpx = SimpleNamespace(Client=FakeClient)
    monkeypatch.setitem(sys.modules, "httpx", fake_httpx)
    assert _download_as_data_uri("https://example.com/forbidden.jpg") is None
