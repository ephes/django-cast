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


def test_styleguide_remote_video_mime_type():
    assert StyleguideRemoteVideo(StyleguideRemoteFile("https://example.com/video.mp4")).get_mime_type() == "video/mp4"
    assert (
        StyleguideRemoteVideo(StyleguideRemoteFile("https://example.com/video.mov")).get_mime_type()
        == "video/quicktime"
    )
    assert (
        StyleguideRemoteVideo(StyleguideRemoteFile("https://example.com/video.avi")).get_mime_type()
        == "video/x-msvideo"
    )
    assert StyleguideRemoteVideo(StyleguideRemoteFile("https://example.com/video")).get_mime_type() == "video/mp4"
    assert (
        StyleguideRemoteVideo(StyleguideRemoteFile("https://example.com/video.unknown")).get_mime_type() == "video/mp4"
    )


def test_styleguide_setting_helpers(settings):
    settings.CAST_STYLEGUIDE_IMAGE_SOURCE_URLS = ["one", None, "", "two"]
    assert styleguide_view._styleguide_setting_list("CAST_STYLEGUIDE_IMAGE_SOURCE_URLS") == ["one", "two"]
    assert styleguide_view._styleguide_image_source_urls() == ["one", "two"]

    settings.CAST_STYLEGUIDE_IMAGE_SOURCE_URLS = "single"
    assert styleguide_view._styleguide_setting_list("CAST_STYLEGUIDE_IMAGE_SOURCE_URLS") == ["single"]

    settings.CAST_STYLEGUIDE_IMAGE_SOURCE_URLS = None
    assert styleguide_view._styleguide_setting_list("CAST_STYLEGUIDE_IMAGE_SOURCE_URLS") == []

    settings.CAST_STYLEGUIDE_IMAGE_SOURCE_URLS = 123
    assert styleguide_view._styleguide_setting_list("CAST_STYLEGUIDE_IMAGE_SOURCE_URLS") == []

    settings.CAST_STYLEGUIDE_PODCAST_SOURCE_URL = "https://example.com/podcast"
    assert styleguide_view._styleguide_podcast_source_url() == "https://example.com/podcast"

    settings.CAST_STYLEGUIDE_TRANSCRIPT_SOURCE_URL = "https://example.com/transcript"
    assert styleguide_view._styleguide_transcript_source_url() == "https://example.com/transcript"

    settings.CAST_STYLEGUIDE_VIDEO_SOURCE_URL = "https://example.com/video"
    assert styleguide_view._styleguide_video_source_url() == "https://example.com/video"

    settings.CAST_STYLEGUIDE_REMOTE_TIMEOUT = 12
    assert styleguide_view._styleguide_remote_timeout() == 12.0

    settings.CAST_STYLEGUIDE_IMAGE_LIMIT = 3
    assert styleguide_view._styleguide_remote_image_limit() == 3

    settings.CAST_STYLEGUIDE_GENERATE_RENDITIONS = True
    assert styleguide_view._styleguide_generate_renditions() is True

    settings.CAST_STYLEGUIDE_TRANSCRIPT_MAX_SEGMENTS = 5
    assert styleguide_view._styleguide_transcript_max_segments() == 5


def test_styleguide_request_sets_user_agent():
    request = styleguide_view._styleguide_request("https://example.com")
    assert request.headers.get("User-agent") == styleguide_view.STYLEGUIDE_USER_AGENT


def test_styleguide_fetch_remote_html_success_and_failure(monkeypatch):
    def fake_urlopen(_request, timeout=0):
        return DummyResponse(b"<html>ok</html>")

    monkeypatch.setattr(styleguide_view, "urlopen", fake_urlopen)
    assert styleguide_view._fetch_remote_html("https://example.com") == "<html>ok</html>"

    def fake_error(_request, timeout=0):
        raise OSError("boom")

    monkeypatch.setattr(styleguide_view, "urlopen", fake_error)
    assert styleguide_view._fetch_remote_html("https://example.com") is None


def test_styleguide_extract_helpers():
    html = "<image-gallery-bs5>one</image-gallery-bs5><image-gallery-bs4>two</image-gallery-bs4>"
    assert len(styleguide_view._extract_gallery_blocks(html)) == 2

    video_html = '<video poster="poster.jpg"><source src="/media/video.mp4"></video>'
    video_url, poster_url = styleguide_view._extract_video_data(video_html, "https://example.com/page/")
    assert video_url == "https://example.com/media/video.mp4"
    assert poster_url == "https://example.com/page/poster.jpg"

    fallback_html = "https://example.com/assets/movie.mp4"
    video_url, poster_url = styleguide_view._extract_video_data(fallback_html, "https://example.com/page/")
    assert video_url == "https://example.com/assets/movie.mp4"
    assert poster_url is None

    meta_html = '<meta property="og:image" content="/images/cover.jpg">'
    assert (
        styleguide_view._extract_cover_image_url(meta_html, "https://example.com/page/")
        == "https://example.com/images/cover.jpg"
    )

    reversed_meta_html = '<meta content="/images/tw.jpg" name="twitter:image">'
    assert (
        styleguide_view._extract_cover_image_url(reversed_meta_html, "https://example.com/page/")
        == "https://example.com/images/tw.jpg"
    )

    image_html = """
        <a class="cast-gallery-link" href="https://d2.cloudfront.net/original_images/one.jpg">x</a>
        <a class="cast-gallery-link" href="https://example.com/not-allowed.jpg">x</a>
        <div data-full="https://d2.cloudfront.net/original_images/two.jpg"></div>
        https://d2.cloudfront.net/original_images/three.jpg
        //d2.cloudfront.net/original_images/four.jpg
        /original_images/five.jpg
    """
    urls = styleguide_view._extract_original_image_urls(image_html, "https://d2.cloudfront.net/page/")
    assert "https://d2.cloudfront.net/original_images/one.jpg" in urls
    assert "https://d2.cloudfront.net/original_images/two.jpg" in urls
    assert "https://d2.cloudfront.net/original_images/three.jpg" in urls
    assert "https://d2.cloudfront.net/original_images/four.jpg" in urls
    assert "https://d2.cloudfront.net/original_images/five.jpg" in urls
    assert all("cloudfront.net" in url for url in urls)

    picked = styleguide_view._pick_largest_width_urls(
        [
            "https://example.com/image.width-100.jpg",
            "https://example.com/image.width-200.jpg",
            "https://example.com/other.jpg",
        ]
    )
    assert "https://example.com/image.width-200.jpg" in picked
    assert "https://example.com/other.jpg" in picked

    picked_smaller = styleguide_view._pick_largest_width_urls(
        [
            "https://example.com/image.width-200.jpg",
            "https://example.com/image.width-100.jpg",
        ]
    )
    assert "https://example.com/image.width-200.jpg" in picked_smaller

    audio_html = '<meta name="twitter:player:stream" content="https://example.com/audio.m4a">'
    assert styleguide_view._extract_audio_url(audio_html) == "https://example.com/audio.m4a"

    audio_fallback_html = "https://example.com/other.m4a"
    assert styleguide_view._extract_audio_url(audio_fallback_html) == "https://example.com/other.m4a"

    podlove_html = (
        '<podlove-player data-url="https://example.com/api/audios/podlove/123"></podlove-player>'
        '<podlove-player data-url="/api/audios/alt"></podlove-player>'
    )
    assert (
        styleguide_view._extract_podlove_player_api_url(podlove_html, "https://example.com/page/")
        == "https://example.com/api/audios/podlove/123"
    )

    fallback_podlove_html = '<podlove-player data-url="/api/audios/alt"></podlove-player>'
    assert (
        styleguide_view._extract_podlove_player_api_url(fallback_podlove_html, "https://example.com/page/")
        == "https://example.com/api/audios/alt"
    )


def test_styleguide_extract_original_image_urls_dedup_and_filter():
    html = """
        <div data-full="https://d2.cloudfront.net/original_images/one.jpg"></div>
        <div data-full="https://d2.cloudfront.net/original_images/one.jpg"></div>
        <div data-full="https://example.com/not-allowed.jpg"></div>
        <a class="cast-gallery-link" href="https://d2.cloudfront.net/original_images/one.jpg">dup</a>
        https://example.com/original_images/bad.gif
        https://d2.cloudfront.net/original_images/two.jpg
    """
    urls = styleguide_view._extract_original_image_urls(html, "https://d2.cloudfront.net/page/")
    assert urls.count("https://d2.cloudfront.net/original_images/one.jpg") == 1
    assert "https://example.com/original_images/bad.gif" not in urls


def test_styleguide_is_styleguide_image_url_invalid_extension():
    assert styleguide_view._is_styleguide_image_url("https://d2.cloudfront.net/original_images/invalid.gif") is False


def test_styleguide_image_parser_collects_urls():
    parser = styleguide_view._StyleguideImageParser("https://example.com/base/")
    html = """
        <a class="cast-gallery-link" href="/original_images/one.jpg">link</a>
        <img src="https://d2.cloudfront.net/original_images/two.jpg"
             srcset="/original_images/three.jpg 1w, https://d2.cloudfront.net/original_images/four.jpg 2w">
    """
    parser.feed(html)
    assert "https://example.com/original_images/one.jpg" in parser.urls
    assert "https://d2.cloudfront.net/original_images/two.jpg" in parser.urls
    assert "https://example.com/original_images/three.jpg" in parser.urls
    assert "https://d2.cloudfront.net/original_images/four.jpg" in parser.urls


def test_styleguide_image_parser_ignores_data_and_non_img_tags():
    parser = styleguide_view._StyleguideImageParser("https://example.com/base/")
    html = """
        <source srcset="/original_images/ignored.jpg 1w">
        <img src="data:image/png;base64,AAAA">
        <img src="/original_images/one.jpg">
    """
    parser.feed(html)
    assert "https://example.com/original_images/one.jpg" in parser.urls
    assert all(not url.startswith("data:") for url in parser.urls)


def test_styleguide_image_parser_handles_missing_src_and_empty_srcset():
    parser = styleguide_view._StyleguideImageParser("https://example.com/base/")
    html = """
        <a href="/original_images/ignored.jpg">no class</a>
        <img srcset=" , /original_images/one.jpg 1w">
    """
    parser.feed(html)
    assert parser.urls == ["https://example.com/original_images/one.jpg"]


def test_styleguide_transcript_parser_extracts_segments():
    parser = styleguide_view._StyleguideTranscriptParser()
    parser.handle_endtag("div")
    html = """
        <section class="transcript-segment">
            <section class="transcript-segment">
                <time>00:00</time>
                <p class="transcript-text">Hello <span>world</span></p>
            </section>
        </section>
    """
    parser.feed(html)
    assert parser.segments[0]["start"] == "00:00"
    assert parser.segments[0]["text"] == "Hello world"

    assert styleguide_view._extract_transcript_data("<div>no segments</div>") is None
    data = styleguide_view._extract_transcript_data(html)
    assert data["transcripts"][0]["text"] == "Hello world"


def test_styleguide_transcript_parser_ignores_empty_text():
    parser = styleguide_view._StyleguideTranscriptParser()
    html = """
        <section class="transcript-segment">
            <time>00:01</time>
            <p class="transcript-text">   </p>
        </section>
    """
    parser.feed(html)
    assert parser.segments == []


def test_styleguide_transcript_parser_nested_section_depth():
    parser = styleguide_view._StyleguideTranscriptParser()
    html = """
        <section class="transcript-segment">
            <section>
                <time>00:02</time>
                <p class="transcript-text">Nested</p>
            </section>
        </section>
    """
    parser.feed(html)
    assert parser.segments[0]["text"] == "Nested"


def test_styleguide_should_refresh_body_variants():
    class Body:
        def __init__(self, data):
            self.stream_data = data

    class PageWithBody:
        def __init__(self, data):
            self.body = Body(data)

    class PageWithoutBody:
        pass

    assert styleguide_view._styleguide_should_refresh_body(PageWithoutBody(), "[]") is True
    assert styleguide_view._styleguide_should_refresh_body(PageWithBody([]), "not-json") is True
    assert styleguide_view._styleguide_should_refresh_body(PageWithBody(["a"]), json.dumps(["a"])) is False
    assert styleguide_view._styleguide_should_refresh_body(PageWithBody(["a"]), json.dumps(["b"])) is True


@pytest.mark.django_db
def test_styleguide_create_styleguide_galleries(settings):
    settings.CAST_STYLEGUIDE_GALLERY_CHUNK_SIZE = 1
    user = create_user(name="gallery-user", password="gallery-user")
    images = [create_image(), create_image()]
    galleries = styleguide_view._create_styleguide_galleries(images, user)
    assert len(galleries) == 2

    fallback = styleguide_view._create_styleguide_galleries(None, user)
    assert len(fallback) == 2


@pytest.mark.django_db
def test_styleguide_create_styleguide_media_branches():
    user = create_user(name="media-user", password="media-user")
    media = styleguide_view._create_styleguide_media(gallery=None, gallery_images=[], audio=None, user=user)
    assert media.audio is not None
    assert media.gallery is not None

    images = [create_image(), create_image()]
    media_from_images = styleguide_view._create_styleguide_media(
        gallery=None,
        gallery_images=images,
        audio=None,
        user=user,
    )
    assert {image.pk for image in media_from_images.gallery.images.all()} == {image.pk for image in images}
    assert media_from_images.image.pk == images[0].pk

    gallery = create_gallery(images=[create_image()])
    audio = create_audio(user=user, unique_filenames=True)
    media_existing = styleguide_view._create_styleguide_media(
        gallery=gallery,
        gallery_images=None,
        audio=audio,
        user=user,
    )
    assert media_existing.gallery.pk == gallery.pk
    assert media_existing.audio.pk == audio.pk


@pytest.mark.django_db
def test_styleguide_build_body_video_and_no_video():
    user = create_user(name="body-user", password="body-user")
    media = styleguide_view._create_styleguide_media(gallery=None, gallery_images=[], audio=None, user=user)

    body_with_video = styleguide_view._build_styleguide_body(
        media=media,
        include_media=True,
        galleries=[media.gallery],
        include_video=True,
    )
    assert _find_block_types(body_with_video, "video")

    body_no_video = styleguide_view._build_styleguide_body(
        media=media,
        include_media=True,
        galleries=[media.gallery],
        include_video=False,
    )
    assert not _find_block_types(body_no_video, "video")

    body_no_media = styleguide_view._build_styleguide_body(
        media=None,
        include_media=False,
        galleries=[media.gallery],
        include_video=True,
    )
    assert not _find_block_types(body_no_media, "audio")


def test_styleguide_transcript_excerpt(settings):
    settings.CAST_STYLEGUIDE_TRANSCRIPT_EXCERPT_SEGMENTS = 1
    data = {"transcripts": [1, 2, 3], "version": 1}
    excerpt = styleguide_view._styleguide_transcript_excerpt(data)
    assert excerpt["transcripts"] == [1]


@pytest.mark.django_db
def test_styleguide_ensure_cover_image_branches():
    image = create_image()

    class DummyPage:
        def __init__(self):
            self.cover_image = None
            self.cover_alt_text = ""
            self.saved = False

        @property
        def cover_image_id(self):
            return self.cover_image.pk if self.cover_image else None

        def save(self):
            self.saved = True

    class NoCover:
        def __init__(self):
            self.saved = False

        def save(self):
            self.saved = True

    no_cover = NoCover()
    styleguide_view._ensure_cover_image(no_cover, image, "alt")
    assert no_cover.saved is False

    page = DummyPage()
    styleguide_view._ensure_cover_image(page, image, "alt")
    assert page.cover_image.pk == image.pk
    assert page.cover_alt_text == "alt"
    assert page.saved is True

    page.saved = False
    styleguide_view._ensure_cover_image(page, image, "alt")
    assert page.saved is False


@pytest.mark.django_db
def test_styleguide_apply_cover_images_with_and_without_posts():
    image = create_image()

    class DummyPage:
        def __init__(self):
            self.cover_image = None
            self.cover_alt_text = ""
            self.saved = False

        @property
        def cover_image_id(self):
            return self.cover_image.pk if self.cover_image else None

        def save(self):
            self.saved = True

    blog = DummyPage()
    podcast = DummyPage()
    episode = DummyPage()
    post = DummyPage()

    styleguide_view._apply_styleguide_cover_images(
        blog=blog,
        podcast=podcast,
        posts=[],
        episode=episode,
        image=image,
    )
    assert blog.saved is True
    assert podcast.saved is True
    assert episode.saved is True

    post.saved = False
    styleguide_view._apply_styleguide_cover_images(
        blog=blog,
        podcast=podcast,
        posts=[post],
        episode=episode,
        image=image,
    )
    assert post.saved is True


@pytest.mark.django_db
def test_styleguide_ensure_podlove_transcript_updates():
    user = create_user(name="podlove-user", password="podlove-user")
    audio = create_audio(user=user, unique_filenames=True)
    data = styleguide_view._styleguide_transcript_data()
    transcript = styleguide_view._ensure_podlove_transcript(audio, data)
    assert transcript.podlove is not None

    transcript_again = styleguide_view._ensure_podlove_transcript(audio, data)
    assert transcript_again.pk == transcript.pk


@pytest.mark.django_db
def test_styleguide_gallery_repository_and_blocks(monkeypatch):
    image = create_image()
    repository = SimpleNamespace(renditions_for_posts={})
    created = {}

    def fake_missing(_images):
        return [], ["missing"]

    def fake_create_missing(missing):
        created["missing"] = missing

    monkeypatch.setattr(styleguide_view, "get_obsolete_and_missing_rendition_strings", fake_missing)
    monkeypatch.setattr(styleguide_view, "create_missing_renditions_for_images", fake_create_missing)

    styleguide_view._styleguide_gallery_repository(repository, [image], ensure_renditions=True)
    assert created["missing"] == ["missing"]

    styleguide_view._styleguide_gallery_repository(repository, [image], ensure_renditions=False)

    rendered = []

    def fake_render(**_kwargs):
        rendered.append(_kwargs.get("ensure_renditions"))
        return "<block/>"

    monkeypatch.setattr(styleguide_view, "_render_gallery_block", fake_render)
    gallery = create_gallery(images=[image])
    result = styleguide_view._ensure_styleguide_gallery_blocks(
        [gallery, gallery],
        repository,
        "bootstrap4",
        limit=None,
    )
    assert len(result) == 2
    assert rendered == [True, True]

    rendered.clear()
    result_limited = styleguide_view._ensure_styleguide_gallery_blocks(
        [gallery],
        repository,
        "bootstrap4",
        limit=1,
    )
    assert result_limited == ["<block/>"]
    assert rendered == [True]


@pytest.mark.django_db
def test_styleguide_render_gallery_block_uses_default_renditions(monkeypatch):
    image = create_image()
    repository = SimpleNamespace(renditions_for_posts={})
    called = {}

    def fake_generate():
        called["generated"] = True
        return False

    def fake_gallery_repository(_repo, _images, *, ensure_renditions):
        called["ensure_renditions"] = ensure_renditions
        return SimpleNamespace(renditions_for_posts={})

    class FakeBlock:
        def render(self, _value, context):
            called["context"] = context
            return "<block/>"

    import cast.blocks as blocks

    monkeypatch.setattr(styleguide_view, "_styleguide_generate_renditions", fake_generate)
    monkeypatch.setattr(styleguide_view, "_styleguide_gallery_repository", fake_gallery_repository)
    monkeypatch.setattr(blocks, "GalleryBlockWithLayout", FakeBlock)

    html = styleguide_view._render_gallery_block(
        images=[image],
        repository=repository,
        template_base_dir="bootstrap4",
    )
    assert called["generated"] is True
    assert called["ensure_renditions"] is False
    assert html == "<block/>"


@pytest.mark.django_db
def test_styleguide_gallery_blocks_renders_all_galleries(monkeypatch):
    image = create_image()
    gallery = create_gallery(images=[image])
    second_gallery = create_gallery(images=[create_image()])
    repository = SimpleNamespace(renditions_for_posts={})

    def fake_render(**_kwargs):
        return "<block/>"

    monkeypatch.setattr(styleguide_view, "_render_gallery_block", fake_render)
    result = styleguide_view._ensure_styleguide_gallery_blocks(
        [gallery, second_gallery],
        repository,
        "bootstrap4",
        limit=None,
    )
    assert len(result) == 2


def test_styleguide_gallery_blocks_handles_empty_galleries():
    repository = SimpleNamespace(renditions_for_posts={})
    result = styleguide_view._ensure_styleguide_gallery_blocks(
        [],
        repository,
        "bootstrap4",
        limit=None,
    )
    assert result == []


@pytest.mark.django_db
def test_styleguide_find_media_post_prefers_media(post, audio):
    from tests.factories import PostFactory

    media_post = PostFactory(
        owner=post.owner,
        parent=post.blog,
        title="media post",
        slug="media-post",
        body=post.body,
    )
    media_post.audios.add(audio)
    selected = styleguide_view._styleguide_find_media_post([post, media_post], fallback=post)
    assert selected.pk == media_post.pk


@pytest.mark.django_db
def test_styleguide_find_media_post_falls_back(post, post_in_podcast):
    selected = styleguide_view._styleguide_find_media_post([post], fallback=post_in_podcast)
    assert selected.pk == post_in_podcast.pk


def test_styleguide_remote_media_flag(settings):
    settings.CAST_STYLEGUIDE_REMOTE_MEDIA = False
    assert styleguide_view._styleguide_remote_media_enabled() is False
    settings.CAST_STYLEGUIDE_REMOTE_MEDIA = True
    assert styleguide_view._styleguide_remote_media_enabled() is True


def test_styleguide_fetch_podlove_data(monkeypatch):
    def fake_urlopen(_request, timeout=0):
        return DummyResponse(json.dumps({"ok": True}).encode("utf-8"))

    monkeypatch.setattr(styleguide_view, "urlopen", fake_urlopen)
    assert styleguide_view._fetch_podlove_data("https://example.com/api") == {"ok": True}

    def fake_error(_request, timeout=0):
        raise OSError("boom")

    monkeypatch.setattr(styleguide_view, "urlopen", fake_error)
    assert styleguide_view._fetch_podlove_data("https://example.com/api") is None


def test_styleguide_remote_html_pages_skips_empty_and_missing(monkeypatch):
    html_by_url = {
        "https://example.com/one/": "<html>one</html>",
        "https://example.com/two/": None,
    }

    monkeypatch.setattr(styleguide_view, "_fetch_remote_html", lambda url: html_by_url.get(url))

    assert styleguide_view._styleguide_remote_html_pages(
        ["", "https://example.com/one/", "https://example.com/two/"]
    ) == [("https://example.com/one/", "<html>one</html>")]


def test_styleguide_fetch_remote_gallery_media_extracts_blocks_and_honors_limit(monkeypatch, settings):
    settings.CAST_STYLEGUIDE_IMAGE_SOURCE_URLS = ["https://example.com/gallery/", ""]
    settings.CAST_STYLEGUIDE_IMAGE_LIMIT = 1
    first_image = object()

    monkeypatch.setattr(
        styleguide_view,
        "_fetch_remote_html",
        lambda url: "<image-gallery-bs4>gallery</image-gallery-bs4>" if url else None,
    )
    monkeypatch.setattr(
        styleguide_view,
        "_extract_image_urls",
        lambda _html, _page_url: ["https://example.com/one.jpg", "https://example.com/two.jpg"],
    )
    monkeypatch.setattr(
        styleguide_view,
        "_get_or_create_remote_image",
        lambda url, _user: first_image if url.endswith("one.jpg") else None,
    )

    gallery_images, gallery_blocks = styleguide_view._fetch_styleguide_remote_gallery_media(user=object())
    assert gallery_images == [first_image]
    assert gallery_blocks == ["<image-gallery-bs4>gallery</image-gallery-bs4>"]


def test_styleguide_fetch_remote_video_media_uses_first_video_source(monkeypatch, settings):
    settings.CAST_STYLEGUIDE_VIDEO_SOURCE_URL = None
    settings.CAST_STYLEGUIDE_IMAGE_SOURCE_URLS = ["", "https://example.com/gallery/", "https://example.com/second/"]

    html_by_url = {
        "https://example.com/gallery/": '<video poster="poster.jpg"><source src="/video.mp4"></video>',
        "https://example.com/second/": '<video poster="other.jpg"><source src="/other.mp4"></video>',
    }

    monkeypatch.setattr(styleguide_view, "_fetch_remote_html", lambda url: html_by_url.get(url))

    video_url, poster_url = styleguide_view._fetch_styleguide_remote_video_media()
    assert video_url == "https://example.com/video.mp4"
    assert poster_url == "https://example.com/gallery/poster.jpg"


def test_styleguide_fetch_remote_podcast_media_derives_transcript_url_and_prefers_podlove_cover(
    monkeypatch,
    settings,
):
    settings.CAST_STYLEGUIDE_PODCAST_SOURCE_URL = "https://example.com/podcast"
    settings.CAST_STYLEGUIDE_TRANSCRIPT_SOURCE_URL = None
    audio = object()
    cover_image = object()

    monkeypatch.setattr(
        styleguide_view,
        "_fetch_remote_html",
        lambda url: (
            (
                '<meta name="twitter:player:stream" content="https://example.com/audio.m4a">'
                '<podlove-player data-url="/api/audios/podlove/1"></podlove-player>'
                '<meta property="og:image" content="https://example.com/meta-cover.jpg">'
            )
            if url == "https://example.com/podcast"
            else None
        ),
    )
    monkeypatch.setattr(styleguide_view, "_get_or_create_remote_audio", lambda _url, _user: audio)
    monkeypatch.setattr(
        styleguide_view,
        "_fetch_podlove_data",
        lambda _url: {
            "version": 2,
            "show": {"poster": "https://example.com/podlove-cover.jpg"},
            "transcripts": [{"start": "00:00:00.000"}],
        },
    )
    monkeypatch.setattr(
        styleguide_view,
        "_get_or_create_remote_image",
        lambda url, _user: cover_image if url.endswith("podlove-cover.jpg") else object(),
    )

    result_audio, transcript_data, result_cover, transcript_url = (
        styleguide_view._fetch_styleguide_remote_podcast_media(
            object(),
            None,
        )
    )
    assert result_audio is audio
    assert transcript_data == {"version": 2, "transcripts": [{"start": "00:00:00.000"}]}
    assert result_cover is cover_image
    assert transcript_url == "https://example.com/podcast/transcript/"
