# ruff: noqa: F401,F811,I001
import json
from contextlib import nullcontext
from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.core.files.base import ContentFile
from django.test import RequestFactory

from cast.devdata import create_audio, create_blog, create_gallery, create_image, create_podcast, create_user
from cast.models import Audio, Post
from cast.views import styleguide as styleguide_view
from cast.views.styleguide import StyleguideRemoteFile, StyleguideRemoteVideo


class DummyResponse:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self) -> bytes:
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def _find_block_types(value, target_type: str) -> bool:
    if isinstance(value, dict):
        if value.get("type") == target_type:
            return True
        return any(_find_block_types(child, target_type) for child in value.values())
    if isinstance(value, list):
        return any(_find_block_types(child, target_type) for child in value)
    return False


def _tiny_png_bytes() -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00"
        b"\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
        b"\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc````"
        b"\x00\x00\x00\x05\x00\x01\xa5\xf6E@\x00\x00"
        b"\x00\x00IEND\xaeB`\x82"
    )


def test_styleguide_fetch_remote_transcript_media_updates_transcript_and_cover(monkeypatch):
    cover_image = object()
    transcript_html = (
        '<meta property="og:image" content="https://example.com/transcript-cover.jpg">'
        '<section class="transcript-segment"><time>00:01</time><p class="transcript-text">Hi</p></section>'
    )

    monkeypatch.setattr(styleguide_view, "_fetch_remote_html", lambda _url: transcript_html)
    monkeypatch.setattr(
        styleguide_view,
        "_get_or_create_remote_image",
        lambda _url, _user: cover_image,
    )

    transcript_data, result_cover = styleguide_view._fetch_styleguide_remote_transcript_media(
        object(),
        transcript_url="https://example.com/transcript/",
        transcript_data={"version": 1, "transcripts": []},
        cover_image=None,
    )
    assert transcript_data == {
        "version": 1,
        "transcripts": [{"end": "", "speaker": "", "start": "00:01", "text": "Hi", "voice": ""}],
    }
    assert result_cover is cover_image


@pytest.mark.django_db
def test_styleguide_get_or_create_remote_image_and_audio(monkeypatch):
    user = create_user(name="remote-user", password="remote-user")
    png_bytes = _tiny_png_bytes()

    def fake_urlopen(_request, timeout=0):
        return DummyResponse(png_bytes)

    monkeypatch.setattr(styleguide_view, "urlopen", fake_urlopen)
    image = styleguide_view._get_or_create_remote_image("https://example.com/image.png", user)
    assert image is not None
    existing = styleguide_view._get_or_create_remote_image("https://example.com/image.png", user)
    assert existing.pk == image.pk

    monkeypatch.setattr(Audio, "_get_audio_duration", staticmethod(lambda _url: timedelta(seconds=1)))
    audio = styleguide_view._get_or_create_remote_audio("https://example.com/audio.m4a", user)
    assert audio is not None


@pytest.mark.django_db
def test_styleguide_get_or_create_remote_image_errors(monkeypatch):
    user = create_user(name="remote-image-error", password="remote-image-error")

    def fake_urlopen_error(_request, timeout=0):
        raise OSError("boom")

    monkeypatch.setattr(styleguide_view, "urlopen", fake_urlopen_error)
    assert styleguide_view._get_or_create_remote_image("https://example.com/image.png", user) is None

    def fake_urlopen_bad(_request, timeout=0):
        return DummyResponse(b"not-an-image")

    monkeypatch.setattr(styleguide_view, "urlopen", fake_urlopen_bad)
    monkeypatch.setattr(styleguide_view.PilImage, "open", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError()))
    assert styleguide_view._get_or_create_remote_image("https://example.com/bad.png", user) is None


@pytest.mark.django_db
def test_styleguide_get_or_create_remote_audio_existing_and_error(monkeypatch):
    user = create_user(name="remote-audio-error", password="remote-audio-error")

    def fake_urlopen(_request, timeout=0):
        return DummyResponse(b"audio-bytes")

    monkeypatch.setattr(styleguide_view, "urlopen", fake_urlopen)
    monkeypatch.setattr(Audio, "_get_audio_duration", staticmethod(lambda _url: timedelta(seconds=1)))
    audio = styleguide_view._get_or_create_remote_audio("https://example.com/audio.m4a", user)
    assert audio is not None
    existing = styleguide_view._get_or_create_remote_audio("https://example.com/audio.m4a", user)
    assert existing.pk == audio.pk

    def fake_urlopen_error(_request, timeout=0):
        raise OSError("boom")

    monkeypatch.setattr(styleguide_view, "urlopen", fake_urlopen_error)
    assert styleguide_view._get_or_create_remote_audio("https://example.com/missing.m4a", user) is None


@pytest.mark.django_db
def test_styleguide_get_or_create_remote_audio_legacy_title_migration(monkeypatch):
    monkeypatch.setattr(Audio, "_get_audio_duration", staticmethod(lambda _url: timedelta(seconds=1)))
    user = create_user(name="remote-audio-legacy", password="remote-audio-legacy")
    url = "https://example.com/audio.m4a"
    legacy_title = f"Styleguide source: {url}"
    audio = Audio(user=user, title=legacy_title)
    audio.m4a.save("audio.m4a", ContentFile(b"audio-bytes"), save=True)
    audio.save()

    result = styleguide_view._get_or_create_remote_audio(url, user)
    assert result is not None
    assert result.pk == audio.pk
    assert result.title == "Podcast Episode (audio)"
    assert result.data["styleguide_source_url"] == url


@pytest.mark.django_db
def test_styleguide_backfill_skips_non_url_titles(monkeypatch):
    """Backfill only migrates titles where the suffix is a URL, not arbitrary text."""
    monkeypatch.setattr(Audio, "_get_audio_duration", staticmethod(lambda _url: timedelta(seconds=1)))
    user = create_user(name="remote-audio-nonurl", password="remote-audio-nonurl")
    audio = Audio(user=user, title="Styleguide source: not a url")
    audio.m4a.save("safe.m4a", ContentFile(b"audio-bytes"), save=True)
    audio.save()

    styleguide_view._backfill_legacy_styleguide_audio_titles(user)
    audio.refresh_from_db()
    assert audio.title == "Styleguide source: not a url"  # unchanged
    assert "styleguide_source_url" not in audio.data


@pytest.mark.django_db
def test_styleguide_get_or_create_remote_audio_updates_stale_title(monkeypatch):
    """When an existing audio is found by URL but has an outdated title, it gets updated."""
    monkeypatch.setattr(Audio, "_get_audio_duration", staticmethod(lambda _url: timedelta(seconds=1)))
    user = create_user(name="remote-audio-stale", password="remote-audio-stale")
    url = "https://example.com/audio.m4a"
    audio = Audio(user=user, title="Old Title", data={"styleguide_source_url": url})
    audio.m4a.save("audio.m4a", ContentFile(b"audio-bytes"), save=True)
    audio.save()

    result = styleguide_view._get_or_create_remote_audio(url, user)
    assert result is not None
    assert result.pk == audio.pk
    assert result.title == "Podcast Episode (audio)"


@pytest.mark.django_db
def test_styleguide_get_or_create_remote_audio_adopts_transitional_row(monkeypatch):
    """A row with clean title but no URL in data (from prior patch) is adopted, not duplicated."""
    monkeypatch.setattr(Audio, "_get_audio_duration", staticmethod(lambda _url: timedelta(seconds=1)))
    user = create_user(name="remote-audio-trans", password="remote-audio-trans")
    url = "https://example.com/audio.m4a"
    # Simulate transitional state: clean title, no styleguide_source_url in data
    audio = Audio(user=user, title="Podcast Episode (audio)", data={})
    audio.m4a.save("audio.m4a", ContentFile(b"audio-bytes"), save=True)
    audio.save()

    result = styleguide_view._get_or_create_remote_audio(url, user)
    assert result is not None
    assert result.pk == audio.pk  # same row, not a duplicate
    assert result.data["styleguide_source_url"] == url


@pytest.mark.django_db
def test_styleguide_get_or_create_remote_audio_does_not_adopt_other_users_row(monkeypatch):
    """Must not reuse or mutate another user's audio row."""
    monkeypatch.setattr(Audio, "_get_audio_duration", staticmethod(lambda _url: timedelta(seconds=1)))
    other_user = create_user(name="other-user", password="other-user")
    styleguide_user = create_user(name="sg-user", password="sg-user")
    url = "https://example.com/audio.m4a"
    # other_user owns an audio with the same clean title but no marker
    other_audio = Audio(user=other_user, title="Podcast Episode (audio)", data={})
    other_audio.m4a.save("audio.m4a", ContentFile(b"audio-bytes"), save=True)
    other_audio.save()

    def fake_urlopen(_request, timeout=0):
        return DummyResponse(b"new-audio-bytes")

    monkeypatch.setattr(styleguide_view, "urlopen", fake_urlopen)
    result = styleguide_view._get_or_create_remote_audio(url, styleguide_user)
    assert result is not None
    assert result.pk != other_audio.pk  # must be a new row
    assert result.user == styleguide_user
    # other_user's row must be untouched
    other_audio.refresh_from_db()
    assert "styleguide_source_url" not in other_audio.data


@pytest.mark.django_db
def test_styleguide_get_or_create_remote_audio_same_filename_different_urls(monkeypatch):
    """Two different URLs with the same filename must create different Audio records."""
    monkeypatch.setattr(Audio, "_get_audio_duration", staticmethod(lambda _url: timedelta(seconds=1)))
    user = create_user(name="remote-audio-same-fn", password="remote-audio-same-fn")

    def fake_urlopen(_request, timeout=0):
        return DummyResponse(b"audio-bytes")

    monkeypatch.setattr(styleguide_view, "urlopen", fake_urlopen)
    url_a = "https://example.com/path-one/audio.m4a"
    url_b = "https://another.example.org/path-two/audio.m4a"
    audio_a = styleguide_view._get_or_create_remote_audio(url_a, user)
    audio_b = styleguide_view._get_or_create_remote_audio(url_b, user)
    assert audio_a is not None
    assert audio_b is not None
    assert audio_a.pk != audio_b.pk
    assert audio_a.data["styleguide_source_url"] == url_a
    assert audio_b.data["styleguide_source_url"] == url_b


@pytest.mark.django_db
def test_styleguide_fetch_remote_media_disabled(settings):
    settings.CAST_STYLEGUIDE_REMOTE_MEDIA = False
    user = create_user(name="remote-disabled", password="remote-disabled")
    data = styleguide_view._fetch_styleguide_remote_media(user)
    assert data.gallery_images is None
    assert data.gallery_blocks is None
    assert data.cover_image is None
    assert data.audio is None
    assert data.transcript_data is None
    assert data.video_url is None
    assert data.video_poster_url is None


@pytest.mark.django_db
def test_styleguide_fetch_remote_media_enabled(monkeypatch, settings):
    settings.CAST_STYLEGUIDE_REMOTE_MEDIA = True
    settings.CAST_STYLEGUIDE_IMAGE_SOURCE_URLS = [
        "https://example.com/images/",
        "https://example.com/missing/",
        "",
    ]
    settings.CAST_STYLEGUIDE_VIDEO_SOURCE_URL = "https://example.com/video/"
    settings.CAST_STYLEGUIDE_PODCAST_SOURCE_URL = "https://example.com/podcast/"
    settings.CAST_STYLEGUIDE_TRANSCRIPT_SOURCE_URL = "https://example.com/podcast/transcript/"
    settings.CAST_STYLEGUIDE_IMAGE_LIMIT = 1

    user = create_user(name="remote-enabled", password="remote-enabled")

    html_by_url = {
        "https://example.com/images/": (
            '<div data-full="https://d2.cloudfront.net/original_images/one.jpg"></div>'
            '<div data-full="https://d2.cloudfront.net/original_images/two.jpg"></div>'
            "<image-gallery-bs4>gallery</image-gallery-bs4>"
        ),
        "https://example.com/video/": '<video poster="poster.jpg"><source src="/video.mp4"></video>',
        "https://example.com/podcast/": (
            '<meta name="twitter:player:stream" content="https://example.com/audio.m4a">'
            '<podlove-player data-url="https://example.com/api/audios/podlove/1"></podlove-player>'
            '<meta property="og:image" content="https://example.com/poster.jpg">'
        ),
        "https://example.com/podcast/transcript/": (
            '<section class="transcript-segment"><time>00:00</time><p class="transcript-text">Hello</p></section>'
        ),
    }

    monkeypatch.setattr(styleguide_view, "_fetch_remote_html", lambda url: html_by_url.get(url))
    monkeypatch.setattr(styleguide_view, "_get_or_create_remote_image", lambda _url, _user: create_image())
    monkeypatch.setattr(
        styleguide_view,
        "_get_or_create_remote_audio",
        lambda _url, _user: create_audio(user=_user, unique_filenames=True),
    )
    monkeypatch.setattr(
        styleguide_view,
        "_fetch_podlove_data",
        lambda _url: {"version": 1, "show": {"poster": "https://example.com/poster.jpg"}, "transcripts": [1, 2]},
    )

    data = styleguide_view._fetch_styleguide_remote_media(user)
    assert data.gallery_images is not None
    assert len(data.gallery_images) == 1
    assert data.gallery_blocks == ["<image-gallery-bs4>gallery</image-gallery-bs4>"]
    assert data.audio is not None
    assert data.video_url == "https://example.com/video.mp4"
    assert data.video_poster_url == "https://example.com/video/poster.jpg"
    assert data.transcript_data is not None
    assert data.cover_image is not None


@pytest.mark.django_db
def test_styleguide_fetch_remote_media_sets_transcript_url(monkeypatch, settings):
    settings.CAST_STYLEGUIDE_REMOTE_MEDIA = True
    settings.CAST_STYLEGUIDE_IMAGE_SOURCE_URLS = ["https://example.com/images/"]
    settings.CAST_STYLEGUIDE_VIDEO_SOURCE_URL = None
    settings.CAST_STYLEGUIDE_PODCAST_SOURCE_URL = "https://example.com/podcast"
    settings.CAST_STYLEGUIDE_TRANSCRIPT_SOURCE_URL = None

    user = create_user(name="remote-transcript", password="remote-transcript")

    html_by_url = {
        "https://example.com/images/": "",
        "https://example.com/podcast": "<div>podcast</div>",
        "https://example.com/podcast/transcript/": (
            '<meta property="og:image" content="https://example.com/cover.jpg">'
            '<section class="transcript-segment">'
            '<time>00:01</time><p class="transcript-text">Hi</p>'
            "</section>"
        ),
    }

    monkeypatch.setattr(styleguide_view, "_fetch_remote_html", lambda url: html_by_url.get(url))
    monkeypatch.setattr(styleguide_view, "_get_or_create_remote_image", lambda _url, _user: create_image())

    data = styleguide_view._fetch_styleguide_remote_media(user)
    assert data.transcript_data is not None


@pytest.mark.django_db
def test_styleguide_fetch_remote_media_uses_podcast_cover(monkeypatch, settings):
    settings.CAST_STYLEGUIDE_REMOTE_MEDIA = True
    settings.CAST_STYLEGUIDE_IMAGE_SOURCE_URLS = []
    settings.CAST_STYLEGUIDE_VIDEO_SOURCE_URL = None
    settings.CAST_STYLEGUIDE_PODCAST_SOURCE_URL = "https://example.com/podcast/"
    settings.CAST_STYLEGUIDE_TRANSCRIPT_SOURCE_URL = None

    user = create_user(name="remote-cover", password="remote-cover")

    html_by_url = {
        "https://example.com/podcast/": '<meta property="og:image" content="https://example.com/cover.jpg">',
        "https://example.com/podcast/transcript/": None,
    }

    monkeypatch.setattr(styleguide_view, "_fetch_remote_html", lambda url: html_by_url.get(url))
    monkeypatch.setattr(styleguide_view, "_get_or_create_remote_image", lambda _url, _user: create_image())
    monkeypatch.setattr(styleguide_view, "_fetch_podlove_data", lambda _url: None)

    data = styleguide_view._fetch_styleguide_remote_media(user)
    assert data.cover_image is not None


@pytest.mark.django_db
def test_styleguide_fetch_remote_media_skips_missing_images(monkeypatch, settings):
    settings.CAST_STYLEGUIDE_REMOTE_MEDIA = True
    settings.CAST_STYLEGUIDE_IMAGE_SOURCE_URLS = ["https://example.com/images/"]
    settings.CAST_STYLEGUIDE_VIDEO_SOURCE_URL = None
    settings.CAST_STYLEGUIDE_PODCAST_SOURCE_URL = None
    settings.CAST_STYLEGUIDE_TRANSCRIPT_SOURCE_URL = None

    user = create_user(name="remote-missing-images", password="remote-missing-images")

    html_by_url = {
        "https://example.com/images/": "https://d2.cloudfront.net/original_images/one.jpg",
    }

    monkeypatch.setattr(styleguide_view, "_fetch_remote_html", lambda url: html_by_url.get(url))
    monkeypatch.setattr(styleguide_view, "_get_or_create_remote_image", lambda _url, _user: None)

    data = styleguide_view._fetch_styleguide_remote_media(user)
    assert data.gallery_images is None


@pytest.mark.django_db
def test_styleguide_fetch_remote_media_missing_sources(monkeypatch, settings):
    settings.CAST_STYLEGUIDE_REMOTE_MEDIA = True
    settings.CAST_STYLEGUIDE_IMAGE_SOURCE_URLS = ["", "https://example.com/empty/"]
    settings.CAST_STYLEGUIDE_VIDEO_SOURCE_URL = None
    settings.CAST_STYLEGUIDE_PODCAST_SOURCE_URL = "https://example.com/podcast/"
    settings.CAST_STYLEGUIDE_TRANSCRIPT_SOURCE_URL = "https://example.com/transcript/"

    user = create_user(name="remote-missing", password="remote-missing")

    def fake_fetch(url):
        return None

    monkeypatch.setattr(styleguide_view, "_fetch_remote_html", fake_fetch)
    data = styleguide_view._fetch_styleguide_remote_media(user)
    assert data.video_url is None
    assert data.audio is None
    assert data.transcript_data is None


@pytest.mark.django_db
def test_styleguide_fetch_remote_media_skips_empty_video_source(monkeypatch, settings):
    settings.CAST_STYLEGUIDE_REMOTE_MEDIA = True
    settings.CAST_STYLEGUIDE_IMAGE_SOURCE_URLS = []
    settings.CAST_STYLEGUIDE_VIDEO_SOURCE_URL = None
    settings.CAST_STYLEGUIDE_PODCAST_SOURCE_URL = None
    settings.CAST_STYLEGUIDE_TRANSCRIPT_SOURCE_URL = None

    user = create_user(name="remote-empty-video-source", password="remote-empty-video-source")

    monkeypatch.setattr(styleguide_view, "_styleguide_image_source_urls", lambda: [""])
    monkeypatch.setattr(styleguide_view, "_fetch_remote_html", lambda _url: None)

    data = styleguide_view._fetch_styleguide_remote_media(user)
    assert data.video_url is None


@pytest.mark.django_db
def test_styleguide_fetch_remote_media_podlove_without_poster(monkeypatch, settings):
    settings.CAST_STYLEGUIDE_REMOTE_MEDIA = True
    settings.CAST_STYLEGUIDE_IMAGE_SOURCE_URLS = []
    settings.CAST_STYLEGUIDE_VIDEO_SOURCE_URL = None
    settings.CAST_STYLEGUIDE_PODCAST_SOURCE_URL = "https://example.com/podcast/"
    settings.CAST_STYLEGUIDE_TRANSCRIPT_SOURCE_URL = None

    user = create_user(name="remote-podlove", password="remote-podlove")

    html_by_url = {
        "https://example.com/podcast/": (
            '<podlove-player data-url="https://example.com/api/audios/podlove/1"></podlove-player>'
        ),
        "https://example.com/podcast/transcript/": None,
    }

    monkeypatch.setattr(styleguide_view, "_fetch_remote_html", lambda url: html_by_url.get(url))
    monkeypatch.setattr(styleguide_view, "_fetch_podlove_data", lambda _url: {"version": 1, "show": {}})

    data = styleguide_view._fetch_styleguide_remote_media(user)
    assert data.cover_image is None
    assert data.transcript_data is None


@pytest.mark.django_db
def test_styleguide_fetch_remote_media_podlove_fetch_failure(monkeypatch, settings):
    settings.CAST_STYLEGUIDE_REMOTE_MEDIA = True
    settings.CAST_STYLEGUIDE_IMAGE_SOURCE_URLS = []
    settings.CAST_STYLEGUIDE_VIDEO_SOURCE_URL = None
    settings.CAST_STYLEGUIDE_PODCAST_SOURCE_URL = "https://example.com/podcast/"
    settings.CAST_STYLEGUIDE_TRANSCRIPT_SOURCE_URL = None

    user = create_user(name="remote-podlove-fail", password="remote-podlove-fail")

    html_by_url = {
        "https://example.com/podcast/": (
            '<podlove-player data-url="https://example.com/api/audios/podlove/1"></podlove-player>'
        ),
        "https://example.com/podcast/transcript/": None,
    }

    monkeypatch.setattr(styleguide_view, "_fetch_remote_html", lambda url: html_by_url.get(url))
    monkeypatch.setattr(styleguide_view, "_fetch_podlove_data", lambda _url: None)

    data = styleguide_view._fetch_styleguide_remote_media(user)
    assert data.audio is None


@pytest.mark.django_db
def test_styleguide_fetch_remote_media_transcript_without_cover(monkeypatch, settings):
    settings.CAST_STYLEGUIDE_REMOTE_MEDIA = True
    settings.CAST_STYLEGUIDE_IMAGE_SOURCE_URLS = []
    settings.CAST_STYLEGUIDE_VIDEO_SOURCE_URL = None
    settings.CAST_STYLEGUIDE_PODCAST_SOURCE_URL = None
    settings.CAST_STYLEGUIDE_TRANSCRIPT_SOURCE_URL = "https://example.com/transcript/"

    user = create_user(name="remote-transcript-no-cover", password="remote-transcript-no-cover")

    transcript_html = (
        '<section class="transcript-segment"><time>00:01</time><p class="transcript-text">Hi</p></section>'
    )
    monkeypatch.setattr(styleguide_view, "_fetch_remote_html", lambda _url: transcript_html)

    data = styleguide_view._fetch_styleguide_remote_media(user)
    assert data.transcript_data is not None
    assert data.cover_image is None


@pytest.mark.django_db
def test_styleguide_context_uses_remote_video_and_pagination_object_list(settings):
    settings.CAST_ENABLE_STYLEGUIDE = True
    factory = RequestFactory()
    request = factory.get("/cast/styleguide/")

    data = styleguide_view._build_styleguide_data(request)
    data.video_url = "https://example.com/video.mp4"
    data.video_poster_url = "https://example.com/poster.jpg"
    data.blog_repository.pagination_context = {"object_list": data.posts[:1]}

    context = styleguide_view._styleguide_context(data, request, "plain")
    assert isinstance(context["styleguide_video"], StyleguideRemoteVideo)
    assert context["styleguide_media_post"].pk == data.posts[0].pk


@pytest.mark.django_db
def test_styleguide_context_generates_and_refreshes_media_post_renditions(settings, monkeypatch):
    settings.CAST_ENABLE_STYLEGUIDE = True
    factory = RequestFactory()
    request = factory.get("/cast/styleguide/")

    data = styleguide_view._build_styleguide_data(request)
    called = {}
    refreshed = {123: ["sentinel"]}

    def fake_create(posts):
        called["posts"] = list(posts)

    monkeypatch.setattr(styleguide_view, "create_missing_renditions_for_posts", fake_create)
    monkeypatch.setattr(
        styleguide_view.Post,
        "get_all_renditions_from_queryset",
        staticmethod(lambda _posts: refreshed),
    )

    context = styleguide_view._styleguide_context(data, request, "plain")
    assert called["posts"] == [context["styleguide_media_post"]]
    assert data.blog_repository.renditions_for_posts[123] == ["sentinel"]


@pytest.mark.django_db
def test_styleguide_context_skips_empty_renditions_refresh(settings, monkeypatch):
    settings.CAST_ENABLE_STYLEGUIDE = True
    factory = RequestFactory()
    request = factory.get("/cast/styleguide/")

    data = styleguide_view._build_styleguide_data(request)
    called = {}

    class TrackingDict(dict):
        def update(self, *args, **kwargs):
            called["update"] = True
            return super().update(*args, **kwargs)

    data.blog_repository.renditions_for_posts = TrackingDict(data.blog_repository.renditions_for_posts)

    monkeypatch.setattr(styleguide_view, "create_missing_renditions_for_posts", lambda _posts: None)
    monkeypatch.setattr(
        styleguide_view.Post,
        "get_all_renditions_from_queryset",
        staticmethod(lambda _posts: {}),
    )

    styleguide_view._styleguide_context(data, request, "plain")
    assert "update" not in called
