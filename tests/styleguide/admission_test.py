"""Remote reference inputs are admitted before decoding or persistence."""

import io
from datetime import timedelta

import pytest

from cast import safe_fetch
from cast.views import styleguide as view


class Response(io.BytesIO):
    status = 200
    headers: dict[str, str] = {}


@pytest.mark.parametrize("kind", ["html", "control", "image", "audio"])
@pytest.mark.parametrize("declared", [None, "1"])
def test_remote_body_cap(monkeypatch, kind, site, declared):
    from cast.models import Audio
    from tests.styleguide.media_fetch_test import _tiny_png_bytes

    limit = {"html": 2 * 1024**2, "control": 1024**2, "image": 20 * 1024**2, "audio": 100 * 1024**2}[kind]
    prefix = _tiny_png_bytes() if kind == "image" else b"{}" if kind == "control" else b"synthetic"
    response = Response(prefix + b" " * (limit + 1 - len(prefix)))
    response.headers = {} if declared is None else {"Content-Length": declared}
    monkeypatch.setattr(Audio, "_get_audio_duration", staticmethod(lambda *a: timedelta(seconds=1)))
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


@pytest.mark.parametrize(
    "payload",
    [
        b"[]",
        b'{"show": null}',
        b'{"show":"x"}',
        b'{"transcripts":"text"}',
        b'{"show":{},"show":{}}',
        b'{"transcripts":[1]}',
        b'{"transcripts":[{"start":0,"text":"x"}]}',
        b'{"version":NaN}',
        b'{"show":{"poster":1}}',
    ],
)
def test_podlove_invalid_control_refused(monkeypatch, payload):
    monkeypatch.setattr(safe_fetch, "open_url", lambda *a, **kw: Response(payload))
    assert view._fetch_podlove_data("https://example.com/control") is None


@pytest.mark.parametrize("kind", ["image", "audio"])
def test_remote_file_rollback_cleans_owned_output(monkeypatch, user, tmp_path, kind):
    from django.core.files.storage import FileSystemStorage
    from wagtail.images.models import Image

    from cast.models import Audio
    from tests.styleguide.media_fetch_test import _tiny_png_bytes

    model, field, fetch = (
        (Image, "file", view._get_or_create_remote_image)
        if kind == "image"
        else (Audio, "m4a", view._get_or_create_remote_audio)
    )
    storage = FileSystemStorage(location=tmp_path)
    monkeypatch.setattr(model._meta.get_field(field), "storage", storage)
    monkeypatch.setattr(safe_fetch, "open_url", lambda *a, **kw: Response(_tiny_png_bytes()))

    def fail(*a, **kw):
        raise RuntimeError("synthetic persistence failure")

    monkeypatch.setattr(model, "save" if kind == "image" else "create_duration", fail)
    with pytest.raises(RuntimeError, match="synthetic persistence failure"):
        fetch(f"https://example.com/{kind}.png", user)
    assert not [p for p in tmp_path.rglob("*") if p.is_file()]


def test_valid_podlove_control(monkeypatch):
    payload = b'{"version":1,"show":{"poster":"https://example.com/p.png"},"transcripts":[{"start":"0","end":"1","text":"Synthetic","speaker":"A","voice":"v"}]}'
    monkeypatch.setattr(safe_fetch, "open_url", lambda *a, **kw: Response(payload))
    assert view._fetch_podlove_data("https://example.com/control")["transcripts"][0]["text"] == "Synthetic"


def test_invalid_control_precedes_media_storage(monkeypatch, settings):
    settings.CAST_STYLEGUIDE_PODCAST_SOURCE_URL = "https://example.com/podcast"
    monkeypatch.setattr(
        view,
        "_fetch_remote_html",
        lambda *a: (
            '<meta name="twitter:player:stream" content="https://example.com/a.m4a"><podlove-player data-url="/api"></podlove-player>'
        ),
    )
    monkeypatch.setattr(view, "_fetch_podlove_data", lambda *a: None)
    monkeypatch.setattr(view, "_get_or_create_remote_audio", lambda *a: pytest.fail("unexpected storage"))
    assert view._fetch_styleguide_remote_podcast_media(object(), None) == (None, None, None, None)


@pytest.mark.django_db(transaction=True)
def test_remote_file_preserves_committed_callback_failure(monkeypatch, user, tmp_path, site):
    from django.core.files.storage import FileSystemStorage
    from django.db import transaction
    from wagtail.images.models import Image

    from tests.styleguide.media_fetch_test import _tiny_png_bytes

    storage = FileSystemStorage(location=tmp_path)
    monkeypatch.setattr(Image._meta.get_field("file"), "storage", storage)
    original = Image.save

    def fail_after_commit(image, *args, **kwargs):
        original(image, *args, **kwargs)
        transaction.on_commit(lambda: (_ for _ in ()).throw(RuntimeError("committed callback")))

    monkeypatch.setattr(Image, "save", fail_after_commit)
    monkeypatch.setattr(safe_fetch, "open_url", lambda *a, **kw: Response(_tiny_png_bytes()))
    with pytest.raises(RuntimeError, match="committed callback"):
        view._get_or_create_remote_image("https://example.com/p.png", user)
    image = Image.objects.get(title="Styleguide source: https://example.com/p.png")
    assert storage.exists(image.file.name)


def test_remote_file_cleanup_failure_is_secondary(monkeypatch, user, tmp_path, caplog):
    from django.core.files.storage import FileSystemStorage
    from wagtail.images.models import Image

    storage = FileSystemStorage(location=tmp_path)
    monkeypatch.setattr(Image._meta.get_field("file"), "storage", storage)
    monkeypatch.setattr(storage, "delete", lambda *a: (_ for _ in ()).throw(OSError("cleanup")))
    image = Image(title="synthetic", width=1, height=1)
    with pytest.raises(RuntimeError, match="primary"):
        with view._remote_file_save(image, "file", "p.png", b"synthetic"):
            raise RuntimeError("primary")
    assert "Could not compensate" in caplog.text


@pytest.mark.parametrize("kind", ["image", "audio"])
@pytest.mark.parametrize("status,headers", [(206, {}), (200, {"Content-Range": "bytes 0-2/100"})])
def test_partial_media_creates_no_row_or_file(monkeypatch, kind, status, headers, user, site, tmp_path):
    from django.core.files.storage import FileSystemStorage
    from wagtail.images.models import Image

    from cast.models import Audio
    from tests.styleguide.media_fetch_test import _tiny_png_bytes

    model, field, fetch = (
        (Image, "file", view._get_or_create_remote_image)
        if kind == "image"
        else (Audio, "m4a", view._get_or_create_remote_audio)
    )
    response = Response(_tiny_png_bytes())
    response.status, response.headers = status, headers
    monkeypatch.setattr(safe_fetch, "open_url", lambda *a, **kw: response)
    monkeypatch.setattr(view, "urlopen", lambda *a, **kw: response, raising=False)
    monkeypatch.setattr(model._meta.get_field(field), "storage", FileSystemStorage(location=tmp_path))
    monkeypatch.setattr(Audio, "_get_audio_duration", staticmethod(lambda *a: timedelta(seconds=1)))
    before = model.objects.count()
    assert fetch("https://example.com/synthetic.png", user) is None
    assert model.objects.count() == before
    assert not [p for p in tmp_path.rglob("*") if p.is_file()]


@pytest.mark.parametrize("payload", [b'{"version":true}', b'{"transcripts":[{"start":"0","text":"x","end":null}]}'])
def test_control_field_types(monkeypatch, payload):
    monkeypatch.setattr(safe_fetch, "open_url", lambda *a, **kw: Response(payload))
    assert view._fetch_podlove_data("https://example.com/control") is None


def test_video_without_poster_and_empty_control(monkeypatch, settings):
    settings.CAST_STYLEGUIDE_VIDEO_SOURCE_URL = "https://example.com/video"
    settings.CAST_STYLEGUIDE_PODCAST_SOURCE_URL = "https://example.com/podcast"
    monkeypatch.setattr(
        view, "_fetch_remote_html", lambda *a: '<source src="/a.mp4"><podlove-player data-url="/api"></podlove-player>'
    )
    monkeypatch.setattr(view, "_fetch_podlove_data", lambda *a: {})
    assert view._fetch_styleguide_remote_video_media() == ("https://example.com/a.mp4", None)
    assert view._fetch_styleguide_remote_podcast_media(object(), None) == (
        None,
        None,
        None,
        "https://example.com/podcast/transcript/",
    )


@pytest.mark.django_db(transaction=True)
def test_remote_file_refuses_ambient_transaction_before_storage(user, site):
    from django.db import transaction
    from wagtail.images.models import Image

    image = Image(title="synthetic", width=1, height=1)
    with transaction.atomic(), pytest.raises(RuntimeError, match="durable atomic block"):
        with view._remote_file_save(image, "file", "synthetic.png", b"synthetic"):
            pytest.fail("ambient transaction admitted")


@pytest.mark.parametrize("payload,accepted", [(b'{"unused":1e999}', False), (b'{"unused":1.5}', True)])
def test_control_numbers_are_finite(monkeypatch, payload, accepted):
    monkeypatch.setattr(safe_fetch, "open_url", lambda *a, **kw: Response(payload))
    assert (view._fetch_podlove_data("https://example.com/control") is not None) is accepted
