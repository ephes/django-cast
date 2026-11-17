"""Remote reference inputs are admitted before decoding or persistence."""

import io

import pytest

from cast import safe_fetch
from cast.views import styleguide as view


class Response(io.BytesIO):
    status = 200
    headers: dict[str, str] = {}


@pytest.mark.parametrize("kind", ["html", "control", "image", "audio"])
def test_remote_body_cap(monkeypatch, kind, db):
    response = Response(
        b"x" * ({"html": 2 * 1024**2, "control": 1024**2, "image": 20 * 1024**2, "audio": 100 * 1024**2}[kind] + 1)
    )
    monkeypatch.setattr(safe_fetch, "open_url", lambda *a, **kw: response)
    monkeypatch.setattr(view, "urlopen", lambda *a, **kw: response, raising=False)
    if kind == "html":
        assert view._fetch_remote_html("https://example.com/page") is None
    elif kind == "control":
        assert view._fetch_podlove_data("https://example.com/api") is None
    else:
        from cast.devdata import create_user

        user = create_user(name="bounded", password="unused")
        fetch = view._get_or_create_remote_image if kind == "image" else view._get_or_create_remote_audio
        assert fetch("https://example.com/file", user) is None


@pytest.mark.parametrize("status,headers", [(206, {}), (200, {"Content-Range": "bytes 0-2/100"})])
def test_unsolicited_partial_is_refused(monkeypatch, status, headers):
    response = Response(b"ok")
    response.status, response.headers = status, headers
    monkeypatch.setattr(safe_fetch, "open_url", lambda *a, **kw: response)
    monkeypatch.setattr(view, "urlopen", lambda *a, **kw: response, raising=False)
    assert view._fetch_remote_html("https://example.com/page") is None
