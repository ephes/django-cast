import json
from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.core.files.base import ContentFile
from django.test import RequestFactory

from cast.devdata import create_audio, create_blog, create_gallery, create_image, create_podcast, create_user
from cast.models import Audio, Post
from cast.views import styleguide as styleguide_view
from cast.views.styleguide import StyleguideRemoteFile, StyleguideRemoteVideo

pytestmark = pytest.mark.slow


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
def test_styleguide_context_uses_remote_video(settings):
    settings.CAST_ENABLE_STYLEGUIDE = True
    factory = RequestFactory()
    request = factory.get("/cast/styleguide/")

    data = styleguide_view._build_styleguide_data(request)
    data.video_url = "https://example.com/video.mp4"
    data.video_poster_url = "https://example.com/poster.jpg"

    context = styleguide_view._styleguide_context(data, request, "plain")
    assert isinstance(context["styleguide_video"], StyleguideRemoteVideo)


@pytest.mark.django_db
def test_styleguide_context_uses_pagination_object_list(settings):
    settings.CAST_ENABLE_STYLEGUIDE = True
    factory = RequestFactory()
    request = factory.get("/cast/styleguide/")

    data = styleguide_view._build_styleguide_data(request)
    data.blog_repository.pagination_context = {"object_list": data.posts[:1]}

    context = styleguide_view._styleguide_context(data, request, "plain")
    assert context["styleguide_media_post"].pk == data.posts[0].pk


@pytest.mark.django_db
def test_styleguide_context_generates_media_post_renditions(settings, monkeypatch):
    settings.CAST_ENABLE_STYLEGUIDE = True
    factory = RequestFactory()
    request = factory.get("/cast/styleguide/")

    data = styleguide_view._build_styleguide_data(request)
    called = {}

    def fake_create(posts):
        called["posts"] = list(posts)

    monkeypatch.setattr(styleguide_view, "create_missing_renditions_for_posts", fake_create)
    context = styleguide_view._styleguide_context(data, request, "plain")
    assert called["posts"] == [context["styleguide_media_post"]]


@pytest.mark.django_db
def test_styleguide_context_refreshes_media_post_renditions(settings, monkeypatch):
    settings.CAST_ENABLE_STYLEGUIDE = True
    factory = RequestFactory()
    request = factory.get("/cast/styleguide/")

    data = styleguide_view._build_styleguide_data(request)
    refreshed = {123: ["sentinel"]}

    monkeypatch.setattr(styleguide_view, "create_missing_renditions_for_posts", lambda _posts: None)
    monkeypatch.setattr(
        styleguide_view.Post,
        "get_all_renditions_from_queryset",
        staticmethod(lambda _posts: refreshed),
    )

    styleguide_view._styleguide_context(data, request, "plain")
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


@pytest.mark.django_db
def test_styleguide_build_data_without_posts(monkeypatch):
    factory = RequestFactory()
    request = factory.get("/cast/styleguide/")

    monkeypatch.setattr(styleguide_view, "_ensure_posts", lambda *_args, **_kwargs: [])
    data = styleguide_view._build_styleguide_data(request)
    assert data.posts == []


@pytest.mark.django_db
def test_styleguide_ensure_episode_branches(settings, site, monkeypatch):
    settings.CAST_STYLEGUIDE_TRANSCRIPT_MAX_SEGMENTS = 2
    user = create_user(name="episode-user", password="episode-user")
    create_blog(owner=user, site=site)
    podcast = create_podcast(owner=user, site=site)
    media = styleguide_view._create_styleguide_media(gallery=None, gallery_images=[], audio=None, user=user)

    galleries = [create_gallery(images=[create_image()])]
    episode, transcript = styleguide_view._ensure_episode(
        podcast,
        user,
        media,
        galleries,
        None,
        include_video_in_body=False,
    )
    assert episode.podcast_audio is not None
    assert transcript["transcripts"]

    episode.body = json.dumps(
        styleguide_view._build_styleguide_body(
            media=media,
            include_media=True,
            galleries=galleries,
            include_video=False,
        )
    )
    episode.podcast_audio = None
    episode.save()

    monkeypatch.setattr(styleguide_view, "_styleguide_should_refresh_body", lambda *_args, **_kwargs: True)

    episode_again, transcript_again = styleguide_view._ensure_episode(
        podcast,
        user,
        media,
        galleries,
        transcript,
        include_video_in_body=False,
    )
    assert episode_again.pk == episode.pk
    assert transcript_again["transcripts"]


@pytest.mark.django_db
def test_styleguide_ensure_episode_does_not_refresh_body(settings, site, monkeypatch):
    user = create_user(name="episode-no-refresh", password="episode-no-refresh")
    create_blog(owner=user, site=site)
    podcast = create_podcast(owner=user, site=site)
    media = styleguide_view._create_styleguide_media(gallery=None, gallery_images=[], audio=None, user=user)
    galleries = [create_gallery(images=[create_image()])]

    episode, transcript = styleguide_view._ensure_episode(
        podcast,
        user,
        media,
        galleries,
        None,
        include_video_in_body=False,
    )
    episode.body = "[]"
    episode.save()

    monkeypatch.setattr(styleguide_view, "_styleguide_should_refresh_body", lambda *_args, **_kwargs: False)
    episode_again, _transcript_again = styleguide_view._ensure_episode(
        podcast,
        user,
        media,
        galleries,
        transcript,
        include_video_in_body=False,
    )
    assert episode_again.pk == episode.pk


@pytest.mark.django_db
def test_styleguide_comments_parent_id_branch(monkeypatch, site, comments_enabled):
    user = create_user(name="comment-user", password="comment-user")
    blog = create_blog(owner=user, site=site)
    post = Post(title="Post", slug="post", owner=user)
    blog.add_child(instance=post)
    post = post.specific

    class FakeField:
        def __init__(self, name):
            self.name = name

    class FakeManager:
        def __init__(self):
            self.created = []

        def filter(self, **_kwargs):
            return self

        def order_by(self, *_args):
            return self

        def all(self):
            return []

        def create(self, **kwargs):
            self.created.append(SimpleNamespace(**kwargs))
            return self.created[-1]

    class FakeCommentModel:
        _meta = SimpleNamespace(fields=[FakeField("parent_id"), FakeField("comment")])
        objects = FakeManager()

    import django_comments

    monkeypatch.setattr(django_comments, "get_model", lambda: FakeCommentModel)

    styleguide_view._ensure_styleguide_comments(post, site=site, user=user)
    assert FakeCommentModel.objects.created


@pytest.mark.django_db
def test_styleguide_comments_update_flags(settings, site, comments_enabled):
    settings.CAST_ENABLE_STYLEGUIDE = True
    user = create_user(name="comment-update", password="comment-update")
    blog = create_blog(owner=user, site=site)
    post = Post(title="Post", slug="post-update", owner=user)
    blog.add_child(instance=post)
    post = post.specific

    from django.contrib.contenttypes.models import ContentType
    from django.contrib.sites.models import Site as DjangoSite
    from django_comments import get_model as get_comment_model

    comment_model = get_comment_model()
    django_site, _created = DjangoSite.objects.get_or_create(
        id=settings.SITE_ID,
        defaults={"domain": "localhost", "name": "localhost"},
    )
    content_type = ContentType.objects.get_for_model(post)
    parent = comment_model.objects.create(
        content_type=content_type,
        object_pk=str(post.pk),
        site=django_site,
        user=user,
        user_name=user.username,
        user_email=f"{user.username}@example.com",
        comment="Old comment",
        submit_date=styleguide_view.timezone.now(),
        is_public=False,
        is_removed=True,
    )
    reply = comment_model.objects.create(
        content_type=content_type,
        object_pk=str(post.pk),
        site=django_site,
        user=user,
        user_name=user.username,
        user_email=f"{user.username}@example.com",
        comment="Old reply",
        submit_date=styleguide_view.timezone.now(),
        is_public=False,
        is_removed=True,
        parent=parent,
    )

    styleguide_view._ensure_styleguide_comments(post, site=site, user=user)
    parent.refresh_from_db()
    reply.refresh_from_db()
    assert parent.is_public is True
    assert parent.is_removed is False
    assert reply.is_public is True
    assert reply.is_removed is False


@pytest.mark.django_db
def test_styleguide_comments_without_reply(settings, site, comments_enabled):
    user = create_user(name="comment-orphan", password="comment-orphan")
    blog = create_blog(owner=user, site=site)
    post = Post(title="Post", slug="post-orphan", owner=user)
    blog.add_child(instance=post)
    post = post.specific

    from django.contrib.contenttypes.models import ContentType
    from django.contrib.sites.models import Site as DjangoSite
    from django_comments import get_model as get_comment_model

    comment_model = get_comment_model()
    django_site, _created = DjangoSite.objects.get_or_create(
        id=settings.SITE_ID,
        defaults={"domain": "localhost", "name": "localhost"},
    )
    content_type = ContentType.objects.get_for_model(post)
    parent = comment_model.objects.create(
        content_type=content_type,
        object_pk=str(post.pk),
        site=django_site,
        user=user,
        user_name=user.username,
        user_email=f"{user.username}@example.com",
        comment="Parent",
        submit_date=styleguide_view.timezone.now(),
    )
    orphan = comment_model.objects.create(
        content_type=content_type,
        object_pk=str(post.pk),
        site=django_site,
        user=user,
        user_name=user.username,
        user_email=f"{user.username}@example.com",
        comment="Orphan",
        submit_date=styleguide_view.timezone.now(),
    )

    styleguide_view._ensure_styleguide_comments(post, site=site, user=user)
    parent.refresh_from_db()
    orphan.refresh_from_db()
    assert orphan.comment == "Orphan"


@pytest.mark.django_db
def test_styleguide_comments_without_parent_field(monkeypatch, site, comments_enabled):
    user = create_user(name="comment-noparent", password="comment-noparent")
    blog = create_blog(owner=user, site=site)
    post = Post(title="Post", slug="post-noparent", owner=user)
    blog.add_child(instance=post)
    post = post.specific

    class FakeField:
        def __init__(self, name):
            self.name = name

    class FakeManager:
        def __init__(self, comments):
            self._comments = comments

        def filter(self, **_kwargs):
            return self

        def order_by(self, *_args):
            return self

        def all(self):
            return self._comments

    class FakeComment:
        def __init__(self, comment):
            self.comment = comment
            self.is_public = True
            self.is_removed = False
            self.saved = False

        def save(self, update_fields=None):
            self.saved = True
            return None

    parent_comment = FakeComment("Parent")
    reply_comment = FakeComment("Reply")

    class FakeCommentModel:
        _meta = SimpleNamespace(fields=[FakeField("comment")])
        objects = FakeManager([parent_comment, reply_comment])

    import django_comments

    monkeypatch.setattr(django_comments, "get_model", lambda: FakeCommentModel)

    styleguide_view._ensure_styleguide_comments(post, site=site, user=user)
    assert reply_comment.saved is True


@pytest.mark.django_db
def test_styleguide_comments_without_parent_field_single_comment(monkeypatch, site, comments_enabled):
    user = create_user(name="comment-single", password="comment-single")
    blog = create_blog(owner=user, site=site)
    post = Post(title="Post", slug="post-single", owner=user)
    blog.add_child(instance=post)
    post = post.specific

    class FakeField:
        def __init__(self, name):
            self.name = name

    class FakeManager:
        def __init__(self, comments):
            self._comments = comments

        def filter(self, **_kwargs):
            return self

        def order_by(self, *_args):
            return self

        def all(self):
            return self._comments

    class FakeComment:
        def __init__(self, comment):
            self.comment = comment
            self.is_public = True
            self.is_removed = False
            self.saved = False

        def save(self, update_fields=None):
            self.saved = True
            return None

    parent_comment = FakeComment("Parent")

    class FakeCommentModel:
        _meta = SimpleNamespace(fields=[FakeField("comment")])
        objects = FakeManager([parent_comment])

    import django_comments

    monkeypatch.setattr(django_comments, "get_model", lambda: FakeCommentModel)

    styleguide_view._ensure_styleguide_comments(post, site=site, user=user)
    assert parent_comment.saved is True


@pytest.mark.django_db
def test_styleguide_comments_creates_parent_without_reply(monkeypatch, site, comments_enabled):
    user = create_user(name="comment-no-reply", password="comment-no-reply")
    blog = create_blog(owner=user, site=site)
    post = Post(title="Post", slug="post-no-reply", owner=user)
    blog.add_child(instance=post)
    post = post.specific

    class FakeField:
        def __init__(self, name):
            self.name = name

    class FakeManager:
        def __init__(self):
            self.created = []

        def filter(self, **_kwargs):
            return self

        def order_by(self, *_args):
            return self

        def all(self):
            return []

        def create(self, **kwargs):
            self.created.append(SimpleNamespace(**kwargs))
            return self.created[-1]

    class FakeCommentModel:
        _meta = SimpleNamespace(fields=[FakeField("comment")])
        objects = FakeManager()

    import django_comments

    monkeypatch.setattr(django_comments, "get_model", lambda: FakeCommentModel)

    styleguide_view._ensure_styleguide_comments(post, site=site, user=user)
    assert FakeCommentModel.objects.created


@pytest.mark.django_db
def test_styleguide_comments_creates_parent_and_reply(site, comments_enabled):
    user = create_user(name="comment-new", password="comment-new")
    blog = create_blog(owner=user, site=site)
    post = Post(title="Post", slug="post-new", owner=user)
    blog.add_child(instance=post)
    post = post.specific

    styleguide_view._ensure_styleguide_comments(post, site=site, user=user)

    from django_comments import get_model as get_comment_model

    comment_model = get_comment_model()
    comments = comment_model.objects.for_model(post).filter(user=user).order_by("submit_date", "pk").all()
    assert len(comments) >= 1


@pytest.mark.django_db
def test_ensure_posts_updates_stale_visible_date(site):
    """When an existing styleguide post has a visible_date in the wrong month, _ensure_posts updates it."""
    from dateutil.relativedelta import relativedelta

    from django.utils import timezone

    user = create_user(name="date-user", password="date-user")
    blog = create_blog(owner=user, site=site)

    # First call creates posts with spread dates
    galleries = [create_gallery(images=[create_image()])]
    media = styleguide_view._create_styleguide_media(gallery=None, gallery_images=[], audio=None, user=user)
    posts = styleguide_view._ensure_posts(blog, user, media, galleries, include_video_in_body=False)
    assert len(posts) >= 2

    # Set the second post's visible_date to "now" so it no longer matches the expected spread month
    second_post = Post.objects.get(pk=posts[1].pk)
    second_post.visible_date = timezone.now()
    second_post.save()

    # Second call should detect the stale date and update it
    posts_again = styleguide_view._ensure_posts(blog, user, media, galleries, include_video_in_body=False)
    refreshed = Post.objects.get(pk=posts_again[1].pk)
    now = timezone.now()
    expected_date = now - relativedelta(months=1)
    assert refreshed.visible_date.strftime("%Y-%m") == expected_date.strftime("%Y-%m")
