import io
import os
import pytest

from django.utils import timezone
from django.core.files.uploadedfile import SimpleUploadedFile

from rest_framework.test import APIClient

from cast.models import Blog, Post, Image, Audio, ItunesArtWork

from .factories import UserFactory
from .factories import VideoFactory
from .factories import GalleryFactory


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
    simple_png = SimpleUploadedFile(
        name="test.png", content=png, content_type="image/png"
    )
    return simple_png


@pytest.fixture()
def image_1px_io():
    png = create_1pximage()
    bio_file = io.BytesIO(png)
    bio_file.name = "testimage.png"
    bio_file.seek(0)
    return bio_file


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
    simple_mp3 = SimpleUploadedFile(
        name="test.mp3", content=mp3, content_type="audio/mpeg"
    )
    return simple_mp3


@pytest.fixture()
def m4a_audio(fixture_dir):
    m4a = read_test_m4a(fixture_dir)
    simple_m4a = SimpleUploadedFile(
        name="test.m4a", content=m4a, content_type="audio/mp4"
    )
    return simple_m4a


# Models
@pytest.fixture()
def user():
    user = UserFactory()
    user._password = "password"
    return user


@pytest.fixture()
def image(user, image_1px):
    image = Image(user=user, original=image_1px)
    image.save()
    yield image
    # teardown
    os.unlink(image.original.path)


@pytest.fixture()
def itunes_artwork(image_1px):
    ia = ItunesArtWork(original=image_1px)
    ia.save()
    yield ia
    # teardown
    os.unlink(ia.original.path)


@pytest.fixture()
def audio(user, m4a_audio):
    audio = Audio(user=user, m4a=m4a_audio)
    audio.save()
    yield audio
    # teardown
    os.unlink(audio.m4a.path)


@pytest.fixture()
def blog(user):
    return Blog.objects.create(user=user, title="testblog", slug="testblog")


@pytest.fixture()
def blog_with_artwork(user, itunes_artwork):
    return Blog.objects.create(
        user=user, title="testblog", slug="testblog", itunes_artwork=itunes_artwork
    )


@pytest.fixture()
def post(blog):
    return Post.objects.create(
        author=blog.user,
        blog=blog,
        title="test entry",
        slug="test-entry",
        pub_date=timezone.now(),
        content="foobar",
    )


@pytest.fixture()
def unpublished_post(blog):
    return Post.objects.create(
        author=blog.user,
        blog=blog,
        title="test entry",
        slug="test-entry",
        pub_date=None,
        content="foobar",
    )


@pytest.fixture()
def podcast_episode(blog, audio):
    return Post.objects.create(
        author=blog.user,
        blog=blog,
        title="test podast episode",
        slug="test-podcast-entry",
        pub_date=timezone.now(),
        content="foobar",
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
    video.user = user
    video.save(poster=False)
    return video


@pytest.fixture()
def gallery(user, image):
    gallery = GalleryFactory(user=user)
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
