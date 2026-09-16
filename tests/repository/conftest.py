"""Shared fixtures for the repository tests.

The fixtures here build posts, renditions and cachable payloads without
touching the database, so the tests in this package can assert that
rendering a post issues no queries.
"""

import json
from pathlib import Path

import pytest
from django.contrib.contenttypes.models import ContentType
from wagtail.images.models import Image, Rendition

from cast.devdata import create_python_body, generate_blog_with_media
from cast.models import (
    Audio,
    Post,
    Video,
)
from cast.models.image_renditions import create_missing_renditions_for_posts
from cast.models.repository import (
    serialize_audio,
    serialize_image,
    serialize_post,
    serialize_renditions,
    serialize_video,
)
from tests.repository.helpers import StubFile


@pytest.fixture(autouse=True)
def debug_settings(settings):
    """Set DEBUG to True for all tests to be able to see the queries."""
    settings.DEBUG = True


@pytest.fixture
def post_with_link_to_itself():
    body = [
        {
            "type": "overview",
            "value": [
                {
                    "type": "paragraph",
                    "value": '<a id="1" linktype="page">just an internal link</a>',
                }
            ],
        }
    ]
    post = Post(id=1, title="Link Source Post", body=json.dumps(body), content_type=ContentType("cast", "post"))
    return post


@pytest.fixture
def post_in_blog(settings):
    settings.DEFAULT_FILE_STORAGE = "django.core.files.storage.FileSystemStorage"
    blog = generate_blog_with_media(number_of_posts=1)
    post = blog.unfiltered_published_posts.first()
    create_missing_renditions_for_posts([post])  # force renditions to be created
    teardown_paths = [Path(post.videos.first().original.path)]
    yield post
    # teardown - remove the files created during the test
    for path in teardown_paths:
        if path.exists():
            path.unlink()


@pytest.fixture
def post():
    body = create_python_body()
    body[0]["value"].append({"type": "audio", "value": 1})
    body[0]["value"].append({"type": "video", "value": 1})
    body[0]["value"].append({"type": "image", "value": 1})
    gallery_with_layout = {"layout": "default", "gallery": [{"id": 1, "type": "item", "value": 1}]}
    body[0]["value"].append({"id": 1, "type": "gallery", "value": gallery_with_layout})
    serialized_body = json.dumps(body)
    return Post(id=1, title="Some post", body=serialized_body)


@pytest.fixture
def renditions_for_post():
    return {
        1: [
            # image
            Rendition(file=StubFile("foo.jpg"), filter_spec="width-1110", width=1110, height=200),
            Rendition(file=StubFile("foo.avif"), filter_spec="width-1110|format-avif", width=1110, height=200),
            # gallery
            Rendition(file=StubFile("foo.jpg"), filter_spec="width-120", width=100, height=120),
            Rendition(file=StubFile("foo.jpg"), filter_spec="width-240", width=100, height=240),
            Rendition(file=StubFile("foo.jpg"), filter_spec="width-360", width=100, height=360),
            Rendition(file=StubFile("foo.jpg"), filter_spec="width-120|format-avif", width=100, height=200),
            Rendition(file=StubFile("foo.jpg"), filter_spec="width-240|format-avif", width=100, height=200),
            Rendition(file=StubFile("foo.jpg"), filter_spec="width-360|format-avif", width=100, height=200),
        ]
    }


@pytest.fixture
def blog_data(post, renditions_for_post):
    post.pk = 1
    audio = Audio(id=1, title="Some audio", collection=None)
    video = Video(id=1, title="Some video", collection=None, original=StubFile("foo.mp4"))
    image = Image(id=1, title="Some image", collection=None, file=StubFile("foo.jpg"), width=2000, height=1000)
    serialized_renditions = serialize_renditions(renditions_for_post)
    data = {
        "template_base_dir": "bootstrap4",
        "blog": {"id": 1, "title": "Some blog", "slug": "some-blog"},
        "blog_cover_image_url": "",
        "blog_cover_alt_text": "",
        "post_by_id": {1: serialize_post(post)},
        "posts": [1],
        "pagination_context": {},
        "audios": {1: serialize_audio(audio)},
        "images": {1: serialize_image(image)},
        "videos": {1: serialize_video(video)},
        "images_by_post_id": {1: [1]},
        "videos_by_post_id": {1: [1]},
        "audios_by_post_id": {1: [1]},
        "cover_by_post_id": {},
        "cover_alt_by_post_id": {},
        "renditions_for_posts": serialized_renditions,
        "owner_username_by_id": {1: "owner"},
        "page_url_by_id": {1: "/some-post/"},
        "absolute_page_url_by_id": {1: "http://testserver/some-post/"},
        "has_audio_by_id": {1: True},
        "root_nav_links": [("http://testserver/", "Home"), ("http://testserver/about/", "About")],
        "filterset": {
            "get_params": {},
            "date_facets_choices": [],
            "category_facets_choices": [],
            "tag_facets_choices": [],
        },
    }
    return data
