import io
import json
import os
import shutil
from copy import deepcopy
from datetime import datetime

import pytest
import pytz
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from django_comments import get_model as get_comments_model
from django_htmx.middleware import HtmxDetails
from rest_framework.test import APIClient
from wagtail.images.models import Image
from wagtail.models import Site

from cast import appsettings
from cast.models import Audio, ChapterMark, File, ItunesArtWork, Video

from .factories import (
    BlogFactory,
    EpisodeFactory,
    GalleryFactory,
    PodcastFactory,
    PostFactory,
    UserFactory,
    VideoFactory,
)


@pytest.fixture(scope="module")
def api_client():
    return APIClient()


@pytest.fixture()
def fixture_dir():
    current_directory = os.path.dirname(os.path.realpath(__file__))
    return os.path.join(current_directory, "fixtures")


@pytest.fixture(scope="session", autouse=True)
def remove_stale_media_files():
    # runs before test starts
    yield
    # runs after test ends
    # cannot use function scoped settings fixture, so import settings
    from django.conf import settings

    shutil.rmtree(settings.MEDIA_ROOT, ignore_errors=True)


# Image testing stuff
def create_1_px_image():
    # This is a 1x1 black png
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00"
        b"\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
        b"\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc````"
        b"\x00\x00\x00\x05\x00\x01\xa5\xf6E@\x00\x00"
        b"\x00\x00IEND\xaeB`\x82"
    )
    return png


@pytest.fixture()
def image_1px():
    png = create_1_px_image()
    simple_png = SimpleUploadedFile(name="test.png", content=png, content_type="image/png")
    return simple_png


@pytest.fixture()
def image_1px_io():
    png = create_1_px_image()
    bio_file = io.BytesIO(png)
    bio_file.name = "test_image.png"
    bio_file.seek(0)
    return bio_file


def read_test_mp4(fixture_dir):
    with open(os.path.join(fixture_dir, "test.mp4"), "rb") as f:
        mp4 = f.read()
    return mp4


@pytest.fixture()
def minimal_mp4(fixture_dir):
    mp4 = read_test_mp4(fixture_dir)
    simple_mp4 = SimpleUploadedFile(name="test.mp4", content=mp4, content_type="video/mp4")
    return simple_mp4


def create_small_rgb():
    # this is a small test jpeg
    from PIL import Image

    img = Image.new("RGB", (200, 200), (255, 0, 0, 0))
    return img


@pytest.fixture()
def small_jpeg_io():
    rgb = create_small_rgb()
    im_io = io.BytesIO()
    rgb.save(im_io, format="JPEG", quality=60, optimize=True, progressive=True)
    im_io.name = "test_image.jpg"
    im_io.seek(0)
    return im_io


# Audio testing stuff
def create_minimal_mp3():
    mp3 = (
        b"\xff\xe3\x18\xc4\x00\x00\x00\x03H\x00\x00\x00\x00"
        b"LAME3.98.2\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
        b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
        b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
        b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    )
    return mp3


def read_test_m4a(fixture_dir):
    with open(os.path.join(fixture_dir, "test.m4a"), "rb") as f:
        m4a = f.read()
    return m4a


@pytest.fixture()
def mp3_audio():
    mp3 = create_minimal_mp3()
    simple_mp3 = SimpleUploadedFile(name="test.mp3", content=mp3, content_type="audio/mpeg")
    return simple_mp3


@pytest.fixture()
def m4a_audio(fixture_dir):
    m4a = read_test_m4a(fixture_dir)
    simple_m4a = SimpleUploadedFile(name="test.m4a", content=m4a, content_type="audio/mp4")
    return simple_m4a


# Models
@pytest.fixture()
def user():
    user = UserFactory()
    user._password = "password"
    group = Group.objects.get(name="Moderators")
    group.user_set.add(user)
    return user


@pytest.fixture()
def authenticated_client(client, user):
    client.login(username=user.username, password=user._password)
    return client


@pytest.fixture()
def image(image_1px):
    image = Image(file=image_1px)
    image.save()
    return image


@pytest.fixture()
def video_with_poster(user, minimal_mp4, image_1px):
    video = Video(user=user, original=minimal_mp4, poster=image_1px)
    video.save()
    return video


@pytest.fixture()
def itunes_artwork(image_1px):
    ia = ItunesArtWork(original=image_1px)
    ia.save()
    return ia


@pytest.fixture()
def audio(user, m4a_audio, settings):
    settings.DEFAULT_FILE_STORAGE = "django.core.files.storage.FileSystemStorage"
    audio = Audio(user=user, m4a=m4a_audio, title="foobar audio")
    audio.save()
    teardown_path = audio.m4a.path  # save path to unlink if audio.m4a is set to None
    yield audio
    # teardown
    try:
        os.unlink(teardown_path)
    except FileNotFoundError:
        pass


@pytest.fixture()
def chaptermarks(audio):
    cms = [
        ("00:01:01.234", "introduction", "", ""),
        ("00:03:05.567", "coughing", "https://google.com", ""),
        ("00:02:05.567", "wrong order", "", ""),
    ]
    results = []
    for start, title, href, image in cms:
        results.append(ChapterMark.objects.create(audio=audio, start=start, title=title))
    return results


@pytest.fixture()
def file_instance(user, m4a_audio):
    file_instance = File(user=user, original=m4a_audio)
    file_instance.save()
    return file_instance


@pytest.fixture()
def site():
    return Site.objects.first()


@pytest.fixture()
def blog(user, site):
    return BlogFactory(owner=user, title="test blog", slug="test_blog", parent=site.root_page)


@pytest.fixture()
def podcast(user, site):
    return PodcastFactory(owner=user, title="test podcast", slug="test_podcast", parent=site.root_page)


@pytest.fixture()
def podcast_with_artwork(user, itunes_artwork, site):
    return PodcastFactory(
        owner=user,
        title="test podcast",
        slug="test_podcast",
        itunes_artwork=itunes_artwork,
        parent=site.root_page,
    )


@pytest.fixture()
def podcast_with_itunes_categories(user, site):
    categories = {"foo": ["baz"]}
    return PodcastFactory(
        owner=user,
        title="test blog",
        slug="test_blog",
        itunes_categories=json.dumps(categories),
        parent=site.root_page,
    )


@pytest.fixture()
def post_data():
    return {"title": "foobar", "content": "blub", "explicit": "2"}


@pytest.fixture()
def post_data_wagtail():
    return {
        "action-publish": "action-publish",
        "body-0-deleted": "",
        "body-0-order": "0",
        "body-0-type": "overview",
        "body-0-value-0-deleted": "",
        "body-0-value-0-order": "0",
        "body-0-value-0-type": "heading",
        "body-0-value-0-value": "overview heading",
        "body-0-value-count": "1",
        "body-count": "1",
        "slug": "new-post",
        "title": "new post",
        "visible_date": "2021-08-17 08:13",
    }


@pytest.fixture()
def python_body():
    return [
        {
            "type": "overview",
            "value": [
                {
                    "type": "heading",
                    "value": "in_all heading",
                }
            ],
        },
        {
            "type": "detail",
            "value": [
                {
                    "type": "heading",
                    "value": "only_in_detail heading",
                }
            ],
        },
    ]


@pytest.fixture()
def body(python_body):
    return json.dumps(python_body)


@pytest.fixture()
def body_with_gallery(python_body, gallery):
    image_pks = [img.pk for img in gallery.images.all()]
    gallery_body = deepcopy(python_body)
    gallery_with_layout = {"layout": "default", "gallery": image_pks}
    gallery_body[0]["value"].append({"type": "gallery", "value": gallery_with_layout})
    return json.dumps(gallery_body)


@pytest.fixture
def body_with_video(python_body, video):
    video_body = deepcopy(python_body)
    video_body[0]["value"].append({"type": "video", "value": video.id})
    return json.dumps(video_body)


@pytest.fixture
def body_with_audio(python_body, audio):
    audio_body = deepcopy(python_body)
    audio_body[0]["value"].append({"type": "audio", "value": audio.id})
    return json.dumps(audio_body)


@pytest.fixture
def body_with_image(python_body, image):
    image_body = deepcopy(python_body)
    image_body[0]["value"].append({"type": "image", "value": image.id})
    return json.dumps(image_body)


@pytest.fixture()
def post(blog, body):
    return PostFactory(
        owner=blog.owner,
        parent=blog,
        title="test entry",
        slug="test-entry",
        body=body,
    )


@pytest.fixture()
def post_in_podcast(podcast, body):
    return PostFactory(
        owner=podcast.owner,
        parent=podcast,
        title="test entry",
        slug="test-entry",
        body=body,
    )


@pytest.fixture()
def post_with_gallery(blog, body_with_gallery):
    return PostFactory(
        owner=blog.owner,
        parent=blog,
        title="test entry",
        slug="test-entry",
        body=body_with_gallery,
    )


@pytest.fixture
def post_with_video(blog, body_with_video):
    return PostFactory(
        owner=blog.owner,
        parent=blog,
        title="test entry",
        slug="test-entry",
        body=body_with_video,
    )


@pytest.fixture
def post_with_audio(blog, body_with_audio):
    return PostFactory(
        owner=blog.owner,
        parent=blog,
        title="test entry",
        slug="test-entry",
        body=body_with_audio,
    )


@pytest.fixture
def post_with_image(blog, body_with_image):
    return PostFactory(
        owner=blog.owner,
        parent=blog,
        title="test entry",
        slug="test-entry",
        body=body_with_image,
    )


@pytest.fixture()
def unpublished_post(blog):
    post = PostFactory(
        owner=blog.owner,
        parent=blog,
        title="test entry",
        slug="test-entry",
    )
    post.unpublish()
    post.refresh_from_db()
    return post


@pytest.fixture()
def unpublished_episode_without_audio(episode):
    episode.podcast_audio = None
    episode.unpublish()
    episode.refresh_from_db()
    return episode


@pytest.fixture()
def post_with_date(blog):
    visible_date = pytz.timezone("Europe/Berlin").localize(datetime(2018, 1, 1, 8))
    return PostFactory(
        owner=blog.owner,
        parent=blog,
        title="test entry",
        slug="test-entry",
        visible_date=visible_date,
    )


@pytest.fixture()
def post_with_different_date(blog):
    visible_date = pytz.timezone("Europe/Berlin").localize(datetime(2019, 1, 1, 8))
    return PostFactory(
        owner=blog.owner,
        parent=blog,
        title="test entry",
        slug="test-entry-alt",
        visible_date=visible_date,
    )


@pytest.fixture()
def post_with_search(blog, python_body):
    search_body = deepcopy(python_body)
    query = "only_in_search"
    search_body[-1]["value"][0]["value"] = f"{query} foobar"
    body = json.dumps(search_body)
    post = PostFactory(
        owner=blog.owner,
        parent=blog,
        title="asdf",
        slug="test-entry-with-search",
        visible_date=timezone.now(),
        body=body,
    )
    post.query = query
    return post


@pytest.fixture()
def episode(podcast, audio, body):
    return EpisodeFactory(
        owner=podcast.owner,
        parent=podcast,
        title="test podcast episode",
        slug="test-podcast-entry",
        podcast_audio=audio,
        body=body,
    )


@pytest.fixture()
def podcast_episode_with_same_audio(blog, audio, body):
    return EpisodeFactory(
        owner=blog.owner,
        parent=blog,
        title="test podcast episode 2",
        slug="test-podcast-entry2",
        podcast_audio=audio,
        body=body,
    )


@pytest.fixture()
def podcast_episode_with_different_visible_date(podcast, audio):
    visible_date = pytz.timezone("Europe/Berlin").localize(datetime(2019, 1, 1, 8))
    return EpisodeFactory(
        owner=podcast.owner,
        parent=podcast,
        title="test podcast episode",
        slug="test-podcast-entry",
        visible_date=visible_date,
        podcast_audio=audio,
    )


@pytest.fixture()
def test_templ():
    return """
        {% lorem %}
    """


@pytest.fixture()
def img_templ():
    return """
        {{% load cast_extras %}}
        {{% image {} %}}
    """


@pytest.fixture()
def video(user):
    video = VideoFactory.build()
    video.title = "video title"
    video.user = user
    video.save(poster=False)
    return video


@pytest.fixture
def video_without_original(video):
    video.original = None
    video.save()
    return video


@pytest.fixture
def audio_without_m4a(audio):
    audio.m4a = None
    audio.save()
    return audio


@pytest.fixture
def video_without_file(video):
    video.original.delete()
    video.original.name = "does_not_exist"
    video.save()
    return video


@pytest.fixture()
def gallery(image):
    gallery = GalleryFactory()
    gallery.images.add(image)
    return gallery


# Mocks
class DummyHandler:
    def __init__(self):
        self.se = {}
        self.ee = set()
        self.aqe = {}

    def startElement(self, name, value):
        self.se[name] = value

    def endElement(self, name):
        self.ee.add(name)

    def addQuickElement(self, *args, attrs=None):
        name = args[0]
        value = None
        if len(args) > 1:
            value = args[1]
        self.aqe[name] = (value, attrs)


@pytest.fixture()
def dummy_handler():
    return DummyHandler()


@pytest.fixture
def simple_request(rf):
    request = rf.get("/")
    request.htmx = HtmxDetails(request)
    request.session = {}
    return request


@pytest.fixture
def htmx_request(rf):
    request = rf.get("/", HTTP_HX_REQUEST="true", HTTP_HX_TARGET="paging-area")
    request.htmx = HtmxDetails(request)
    return request


@pytest.fixture
def htmx_request_without_target(rf):
    request = rf.get("/", HTTP_HX_REQUEST="true", HTTP_HX_TARGET=None)
    request.htmx = HtmxDetails(request)
    return request


@pytest.fixture()
def comments_enabled():
    previous = appsettings.CAST_COMMENTS_ENABLED
    appsettings.CAST_COMMENTS_ENABLED = True
    yield appsettings.CAST_COMMENTS_ENABLED
    appsettings.CAST_COMMENTS_ENABLED = previous


@pytest.fixture()
def comments_not_enabled():
    previous = appsettings.CAST_COMMENTS_ENABLED
    appsettings.CAST_COMMENTS_ENABLED = False
    yield appsettings.CAST_COMMENTS_ENABLED
    appsettings.CAST_COMMENTS_ENABLED = previous


@pytest.fixture()
def comment(post, settings):
    comment_model = get_comments_model()
    instance = comment_model(content_object=post, site_id=settings.SITE_ID, title="foobar", comment="bar baz")
    instance.save()
    return instance


@pytest.fixture()
def comment_spam(post, settings):
    comment_model = get_comments_model()
    instance = comment_model(
        content_object=post, site_id=settings.SITE_ID, title="blub", comment="asdf bsdf", is_removed=True
    )
    instance.save()
    return instance


@pytest.fixture
def use_dummy_cache_backend(settings, mocker):
    settings.CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.dummy.DummyCache",
        }
    }
    # workaround for settings fixture is not working in Django 4.0 and pytest-django
    mocker.patch("django.core.cache.backends.locmem.LocMemCache.get", return_value=None)
