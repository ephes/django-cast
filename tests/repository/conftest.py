# ruff: noqa: F401,F811,I001
"""
This file contains tests for the post data cache. Make sure
all queries happen in one place and there are no additional
queries when rendering posts.
"""

import json
import pickle
from contextvars import Context, copy_context
from copy import deepcopy
from pathlib import Path
from xml.etree import ElementTree

import pytest
import sqlparse
import cast.models.repository as repository_module
from django.contrib.contenttypes.models import ContentType
from django.contrib.sites import models as sites_models
from django.contrib.sites.models import Site as DjangoSite
from django.db import connection, reset_queries
from django.urls import reverse
from django.utils import timezone
from wagtail.images.models import Image, Rendition
from wagtail.models import Site as WagtailSite

from cast.devdata import create_post, create_python_body, create_transcript, generate_blog_with_media
from cast.feeds import LatestEntriesFeed, RssPodcastFeed
from cast.filters import PostFilterset
from cast.models import (
    Audio,
    Blog,
    Contributor,
    ContributorLink,
    Episode,
    EpisodeContributor,
    Podcast,
    Post,
    Season,
    Transcript,
    Video,
)
from cast.models.image_renditions import create_missing_renditions_for_posts
from cast.models.repository.builders import _blog_url_from_referer
from cast.models.repository import (
    BlogIndexContext,
    FeedContext,
    PostDetailContext,
    PostQuerySnapshot,
    add_queryset_data,
    add_site_raw,
    apply_cover_fallback,
    deserialize_audio,
    deserialize_episode,
    deserialize_image,
    deserialize_post,
    deserialize_season,
    deserialize_transcript,
    deserialize_video,
    deserialize_blog,
    deserialize_episode_contributor,
    data_for_blog_cachable,
    get_facet_choices,
    serialize_audio,
    serialize_blog,
    serialize_episode_contributor,
    serialize_episode,
    serialize_image,
    serialize_post,
    serialize_renditions,
    serialize_season,
    serialize_transcript,
    serialize_video,
)
from cast.wagtail_hooks import PageLinkHandlerWithCache
from tests.factories import EpisodeFactory

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


def test_render_post_detail_without_hitting_the_database(rf, post, renditions_for_post):
    """
    Given a post with media which is not in the database. And a repository
    containing the media needed to render the post detail.

    When we render the post detail, then the media should be rendered and
    the database should not be hit.
    """

    repository = PostDetailContext(
        post_id=1,
        template_base_dir="bootstrap4",
        blog=Blog(id=1, title="Some blog"),
        root_nav_links=[("http://testserver/", "Home"), ("http://testserver/about/", "About")],
        comments_are_enabled=False,  # FIXME see #131
        has_audio=True,
        page_url="/some-post/",
        absolute_page_url="http://testserver/some-post/",
        owner_username="owner",
        blog_url="/some-blog/",
        cover_image_url="/media/foo.jpg",
        cover_alt_text="Cover alt text",
        audio_by_id={1: Audio(id=1, title="Some audio", collection=None)},
        video_by_id={1: Video(id=1, title="Some video", collection=None, original=StubFile("foo.mp4"))},
        image_by_id={
            1: Image(id=1, title="Some image", collection=None, file=StubFile("foo.jpg"), width=2000, height=1000)
        },
        renditions_for_posts=renditions_for_post,
    )
    request = rf.get("/some-post/")
    request.htmx = False
    reset_queries()
    # with connection.execute_wrapper(blocker):
    response = post.serve(request, repository=repository).render()
    # Then the media should be rendered
    html = response.content.decode("utf-8")
    assert "web-player/embed.5.js" in html  # audio player because has_audio is True
    assert post.title in html
    assert repository.page_url in html
    assert repository.owner_username.capitalize() in html
    assert '<meta name="twitter:image:alt" content="Cover alt text">' in html
    assert '<meta property="og:image:alt" content="Cover alt text">' in html
    assert "audio_1" in html
    assert "<video" in html
    assert '<section class="block-image">' in html
    assert "1110w" in html
    assert '<section class="block-gallery">' in html
    context = response.context_data
    assert context["template_base_dir"] == repository.template_base_dir
    assert context["blog"] == repository.blog
    assert context["root_nav_links"] == repository.root_nav_links
    assert context["comments_are_enabled"] == repository.comments_are_enabled
    assert context["page_url"] == repository.page_url
    assert context["page"].page_url == repository.page_url
    assert context["absolute_page_url"] == repository.absolute_page_url
    assert context["cover_image_url"] == repository.cover_image_url
    assert context["cover_alt_text"] == repository.cover_alt_text
    assert len(connection.queries) == 0


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
