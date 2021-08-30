import io
import os
import json
import pytz
import pytest

from pathlib import Path
from copy import deepcopy
from datetime import datetime

from django.conf import settings
from django.utils import timezone
from django.test.client import RequestFactory
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile

from rest_framework.test import APIClient

from django_comments import get_model as get_comments_model

from wagtail.core.models import Site, Page, Collection
from wagtail.images.models import Image as WagtailImage

from cast import appsettings

from cast.models import (
    Blog,
    Post,
    Image,
    Audio,
    Video,
    File,
    ItunesArtWork,
    ChapterMark,
)

from .factories import (
    UserFactory,
    PostFactory,
    BlogFactory,
    VideoFactory,
    GalleryFactory,
)


@pytest.fixture(scope="module")
def api_client():
    return APIClient()


@pytest.fixture()
def fixture_dir():
    curdir = os.path.dirname(os.path.realpath(__file__))
    return os.path.join(curdir, "fixtures")


# Image testing stuff
def create_1pximage():
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
    png = create_1pximage()
    simple_png = SimpleUploadedFile(name="test.png", content=png, content_type="image/png")
    return simple_png


@pytest.fixture()
def image_1px_io():
    png = create_1pximage()
    bio_file = io.BytesIO(png)
    bio_file.name = "testimage.png"
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
    im_io.name = "testimage.jpg"
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
def user(settings):
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
def image(user, image_1px):
    image = Image(user=user, original=image_1px)
    image.save()
    return image


@pytest.fixture()
def wagtail_image(image_1px):
    image = WagtailImage(file=image_1px)
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
    audio = Audio(user=user, m4a=m4a_audio)
    audio.save()
    yield audio
    # teardown
    os.unlink(audio.m4a.path)


@pytest.fixture()
def chaptermarks(audio):
    cms = [
        ("00:01:01.234", "introduction", "", ""),
        ("00:03:05.567", "coughing", "http://google.com", ""),
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
    return BlogFactory(owner=user, title="testblog", slug="testblog", parent=site.root_page)


@pytest.fixture()
def blog_with_artwork(user, itunes_artwork, site):
    return BlogFactory(
        owner=user, title="testblog", slug="testblog", itunes_artwork=itunes_artwork, parent=site.root_page,
    )


@pytest.fixture()
def blog_with_itunes_categories(user, site):
    categories = {"foo": ["baz"]}
    return BlogFactory(
        owner=user, title="testblog", slug="testblog", itunes_categories=json.dumps(categories), parent=site.root_page,
    )


@pytest.fixture()
def post_data():
    return {"title": "foobar", "content": "blub", "explicit": "2", "pub_date": ""}


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
        {"type": "overview", "value": [{"type": "heading", "value": "in_all heading",}],},
        {"type": "detail", "value": [{"type": "heading", "value": "only_in_detail heading",}],},
    ]


@pytest.fixture()
def body(python_body):
    return json.dumps(python_body)


@pytest.fixture()
def body_with_gallery(python_body, gallery):
    image_pks = [img.pk for img in gallery.images.all()]
    gallery_body = deepcopy(python_body)
    gallery_body[0]["value"].append({"type": "gallery", "value": image_pks})
    return json.dumps(gallery_body)


@pytest.fixture
def body_with_video(python_body, video):
    video_body = deepcopy(python_body)
    video_body[0]["value"].append({"type": "video", "value": video.id})
    return json.dumps(video_body)


@pytest.fixture
def body_with_image(python_body, wagtail_image):
    image_body = deepcopy(python_body)
    image_body[0]["value"].append({"type": "image", "value": wagtail_image.id})
    return json.dumps(image_body)


@pytest.fixture()
def post(blog, body):
    return PostFactory(
        owner=blog.owner, parent=blog, title="test entry", slug="test-entry", pub_date=timezone.now(), body=body,
    )


@pytest.fixture()
def post_with_gallery(blog, body_with_gallery):
    return PostFactory(
        owner=blog.owner,
        parent=blog,
        title="test entry",
        slug="test-entry",
        pub_date=timezone.now(),
        body=body_with_gallery,
    )


@pytest.fixture
def post_with_video(blog, body_with_video):
    return PostFactory(
        owner=blog.owner,
        parent=blog,
        title="test entry",
        slug="test-entry",
        pub_date=timezone.now(),
        body=body_with_video,
    )

@pytest.fixture
def post_with_image(blog, body_with_image):
    return PostFactory(
        owner=blog.owner,
        parent=blog,
        title="test entry",
        slug="test-entry",
        pub_date=timezone.now(),
        body=body_with_image,
    )


@pytest.fixture()
def unpublished_post(blog):
    post = PostFactory(owner=blog.owner, parent=blog, title="test entry", slug="test-entry", pub_date=None,)
    post.unpublish()
    post.refresh_from_db()
    return post


@pytest.fixture()
def post_with_date(blog):
    visible_date = pytz.timezone("Europe/Berlin").localize(datetime(2018, 1, 1, 8))
    return PostFactory(
        owner=blog.owner,
        parent=blog,
        title="test entry",
        slug="test-entry",
        pub_date=timezone.now(),
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
        pub_date=timezone.now(),
        visible_date=visible_date,
    )


@pytest.fixture()
def post_with_search(blog):
    return PostFactory(
        owner=blog.owner,
        parent=blog,
        title="asdf",
        slug="test-entry-with-search",
        pub_date=timezone.now(),
        visible_date=timezone.now(),
    )


@pytest.fixture()
def podcast_episode(blog, audio, body):
    return PostFactory(
        owner=blog.owner,
        parent=blog,
        title="test podcast episode",
        slug="test-podcast-entry",
        pub_date=timezone.now(),
        podcast_audio=audio,
        body=body,
    )


@pytest.fixture()
def podcast_episode_with_different_visible_date(blog, audio):
    visible_date = pytz.timezone("Europe/Berlin").localize(datetime(2019, 1, 1, 8))
    return PostFactory(
        owner=blog.owner,
        parent=blog,
        title="test podast episode",
        slug="test-podcast-entry",
        pub_date=timezone.now(),
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
def video_without_file(video):
    video.original.delete()
    video.original.name = "does_not_exist"
    video.save()
    return video


@pytest.fixture()
def gallery(wagtail_image):
    gallery = GalleryFactory()
    gallery.images.add(wagtail_image)
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


@pytest.fixture()
def request_factory():
    return RequestFactory()


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
def comment(post):
    comment_model = get_comments_model()
    instance = comment_model(content_object=post, site_id=settings.SITE_ID, title="foobar", comment="bar baz")
    instance.save()
    return instance


@pytest.fixture()
def access_log_path(fixture_dir):
    return Path(fixture_dir) / "access.log"


@pytest.fixture()
def last_request_dummy():
    class RequestDummy:
        def __init__(self):
            self.timestamp = datetime.strptime("01/Dec/2018:06:55:44 +0100", "%d/%b/%Y:%H:%M:%S %z")
            self.ip = "79.230.47.221"

    return RequestDummy()
