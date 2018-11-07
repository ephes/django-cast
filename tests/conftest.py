import io
import os
import pytest

from django.utils import timezone
from django.core.files.uploadedfile import SimpleUploadedFile

from rest_framework.test import APIClient

from cast.models import Blog, Post, Image

from .factories import UserFactory
from .factories import VideoFactory
from .factories import GalleryFactory


@pytest.fixture(scope="module")
def api_client():
    return APIClient()


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
def blog(user):
    return Blog.objects.create(user=user, title="testblog", slug="testblog")


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
