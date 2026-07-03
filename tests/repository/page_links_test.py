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

from tests.repository.helpers import (
    StubFile,
    blocker,
    blog_index_repository,
    feed_repository,
    post_detail_repository,
    queryset_data,
    show_queries,
)


def test_repository_removed_legacy_exports_are_absent():
    removed_names = [
        "QuerysetData",
        "PostDetailRepository",
        "BlogIndexRepository",
        "FeedRepository",
        "EpisodeFeedRepository",
        "audio_to_dict",
        "video_to_dict",
        "image_to_dict",
        "blog_to_dict",
        "blog_from_data",
        "post_to_dict",
        "episode_to_dict",
        "transcript_to_dict",
        "Site",
    ]
    for name in removed_names:
        assert not hasattr(repository_module, name)


@pytest.mark.django_db
def test_internal_page_link_is_not_cached():
    """
    Make sure the right page is returned from the page link handler, especially
    if it's not in the cache.
    """
    # Use a high ID to avoid collisions with styleguide pages created in tests.
    tag = PageLinkHandlerWithCache.expand_db_attributes({"id": 99999})  # get page with non-existing id
    assert tag == "<a>"


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


def test_internal_page_link_is_cached_post_detail(rf, post_with_link_to_itself):
    PageLinkHandlerWithCache.cache.clear()  # reset the page link cache
    # Given a post which links to itself
    post = post_with_link_to_itself
    page_url = "/source-detail/"
    request = rf.get(page_url)
    # Using the post detail repository will cache the page url in the page link handler
    repository = post_detail_repository(post_id=post.id, page_url=page_url)
    reset_queries()
    # When we render the post detail page
    response = post.serve(request, repository=repository).render()
    html = response.content.decode("utf-8")
    # Then the internal link should be rendered
    assert f'<a href="{page_url}">just an internal link</a>' in html
    # And the database should not be hit
    assert len(connection.queries) == 0


def test_internal_page_link_is_cached_blog_index(rf, post_with_link_to_itself):
    PageLinkHandlerWithCache.cache.clear()  # reset the page link cache
    # Given a post which links to itself and a blog containing the post
    post = post_with_link_to_itself
    page_url = "/source-detail/"
    blog = Blog(id=1, title="Some blog", slug="some-blog")
    # Using the blog index repository will cache the page url in the page link handler
    repository = blog_index_repository(
        blog=blog,
        pagination_context={"object_list": [post]},
        queryset_data=queryset_data(page_url_by_id={post.id: page_url}),  # this will cache the page url
    )
    request = rf.get("/blog-index/")
    request.htmx = False
    reset_queries()
    # When we render the blog index page
    # with connection.execute_wrapper(blocker):
    response = blog.serve(request, repository=repository).render()
    html = response.content.decode("utf-8")
    # Then the internal link should be rendered
    assert f'<a href="{page_url}">just an internal link</a>' in html
    # And the database should not be hit
    assert len(connection.queries) == 0


def test_internal_page_link_is_cached_feed(rf, post_with_link_to_itself):
    PageLinkHandlerWithCache.cache.clear()  # reset the page link cache
    # Given a post which links to itself and a blog containing the post
    post = post_with_link_to_itself
    page_url = "/source-detail/"
    blog = Blog(id=1, title="Some blog", slug="some-blog")
    django_site = DjangoSite(domain="testserver", name="testserver")
    sites_models.SITE_CACHE[1] = django_site  # cache site to avoid db hit
    # Using the feed repository will cache the page url in the page link handler
    repository = feed_repository(
        queryset_data=queryset_data(
            post_queryset=[post],
            has_audio_by_id={post.id: False},
            page_url_by_id={post.id: page_url},  # this will cache the page url
            absolute_page_url_by_id={post.id: f"http://testserver{page_url}"},
            owner_username_by_id={post.id: "owner"},
        ),
    )
    request = rf.get("/feed/")
    reset_queries()
    feed_view = LatestEntriesFeed(repository=repository)
    # When we render the feed
    response = feed_view(request, slug=blog.slug)
    # Then the internal link should be rendered
    html = response.content.decode("utf-8")
    assert f'&lt;a href="{page_url}"&gt;just an internal link&lt;/a&gt;' in html
    # And the database should not be hit
    assert len(connection.queries) == 0


# Test render post detail, blog index and blog feed with data from database
