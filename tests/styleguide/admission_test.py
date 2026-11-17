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


@pytest.mark.parametrize(
    "url", ["file:///synthetic", "http://127.0.0.1/x", "https://foreign.invalid/x", "https://u:p@example.com/x"]
)
def test_derived_origin_refused_before_open(monkeypatch, settings, url):
    settings.CAST_STYLEGUIDE_IMAGE_SOURCE_URLS = ["https://example.com/gallery"]
    opened = []
    monkeypatch.setattr(safe_fetch, "open_url", lambda *a, **kw: opened.append(a) or Response(b"ok"))
    assert view._fetch_remote_html(url) is None
    assert not opened


def test_failed_gallery_attempts_are_bounded(monkeypatch, settings, user):
    settings.CAST_STYLEGUIDE_IMAGE_SOURCE_URLS = ["https://example.com/gallery"] * 2
    settings.CAST_STYLEGUIDE_IMAGE_LIMIT = 2
    monkeypatch.setattr(
        view,
        "_extract_image_urls",
        lambda *a: ["https://example.com/x.jpg"] * 2 + [f"https://example.com/{i}.jpg" for i in range(50)],
    )
    opened = []

    def fail(request, **kwargs):
        opened.append(request.full_url)
        if request.full_url.endswith("gallery"):
            return Response(b"gallery")
        raise OSError("synthetic timeout")

    monkeypatch.setattr(safe_fetch, "open_url", fail)
    assert view._fetch_styleguide_remote_gallery_media(user) == (None, None)
    assert len(opened) <= 24
    assert len(opened) == len(set(opened))


def test_remote_deadline_and_private_opt_in(monkeypatch, settings):
    settings.CAST_STYLEGUIDE_IMAGE_SOURCE_URLS = ["http://127.0.0.1/page"]
    monkeypatch.setattr(safe_fetch, "getaddrinfo", lambda *a, **kw: [(None, None, None, None, ("127.0.0.1", 80))])
    monkeypatch.setattr(safe_fetch, "open_url", lambda *a, **kw: Response(b"ok"))
    assert view._fetch_remote_html("http://127.0.0.1/page") is None
    settings.CAST_STYLEGUIDE_REMOTE_ALLOW_PRIVATE = True
    assert view._fetch_remote_html("http://127.0.0.1/page") == "ok"
    with view._remote_fetch_scope():
        monkeypatch.setattr(view, "monotonic", lambda: float("inf"))
        assert view._fetch_remote_html("http://127.0.0.1/page") is None
    assert view._remote_budget.get() is None


def test_video_destination_is_admitted(monkeypatch, settings):
    settings.CAST_STYLEGUIDE_VIDEO_SOURCE_URL = "https://example.com/video"
    monkeypatch.setattr(
        view,
        "_fetch_remote_html",
        lambda *a: '<video poster="file:///fake"><source src="https://example.com/a.mp4"></video>',
    )
    assert view._fetch_styleguide_remote_video_media() == (None, None)
