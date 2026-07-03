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


def show_queries(queries):
    """
    Helper function to show the queries executed during a test.
    """
    for num, query in enumerate(queries, 1):
        print(f"{num} ----------------------------------")
        formatted_sql = sqlparse.format(query["sql"], reindent=True, keyword_case="upper")
        print(formatted_sql)


def blocker(*_args):
    """Get a traceback when a query is executed."""
    raise Exception("No database access allowed here.")


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


@pytest.fixture(autouse=True)
def debug_settings(settings):
    """Set DEBUG to True for all tests to be able to see the queries."""
    settings.DEBUG = True


def post_detail_repository(**kwargs):
    defaults = dict(
        post_id=1,
        template_base_dir="bootstrap4",
        blog=Blog(id=1, title="Some blog"),
        root_nav_links=[],
        comments_are_enabled=False,
        has_audio=False,
        page_url="/some-post/",
        absolute_page_url="http://testserver/some-post/",
        owner_username="owner",
        blog_url="/some-blog/",
        audio_by_id={},
        video_by_id={},
        image_by_id={},
        cover_image_url="",
        cover_alt_text="",
        renditions_for_posts={},
    )
    defaults.update(kwargs)
    return PostDetailContext(**defaults)


def queryset_data(**kwargs):
    defaults = dict(
        post_queryset=[],
        post_by_id={},
        audios={},
        images={},
        videos={},
        audios_by_post_id={},
        podcast_audio_by_episode_id={},
        transcript_by_audio_id={},
        videos_by_post_id={},
        images_by_post_id={},
        owner_username_by_id={},
        has_audio_by_id={},
        renditions_for_posts={},
        page_url_by_id={},
        cover_by_post_id={},
        cover_alt_by_post_id={},
        absolute_page_url_by_id={},
    )
    defaults.update(kwargs)
    return PostQuerySnapshot(**defaults)


def blog_index_repository(**kwargs):
    defaults = dict(
        template_base_dir="bootstrap4",
        blog=Blog(id=1, title="Some blog", slug="some-blog"),
        filterset=PostFilterset(None),
        queryset_data=queryset_data(),
        pagination_context={"object_list": []},
        root_nav_links=[],
        use_audio_player=False,
    )
    defaults.update(kwargs)
    return BlogIndexContext(**defaults)


def feed_repository(**kwargs):
    defaults = dict(
        site=DjangoSite(),
        blog=Blog(id=1, title="Some blog"),
        blog_url="/some-blog/",
        template_base_dir="bootstrap4",
        queryset_data=queryset_data(),
        root_nav_links=[],
    )
    defaults.update(kwargs)
    return FeedContext(**defaults)


class StubFile:
    def __init__(self, name):
        self.name = name
        self.url = f"/media/{name}"
