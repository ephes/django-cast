"""Shared helpers for the tests in this package.

Holds the ``StubFile`` stand-in for saved media files, the query
guard/inspection helpers and the constructors that build repository
context objects without touching the database. Pytest fixtures belong in
``conftest.py``, not here, so that importing this module stays free of
side effects.
"""

import sqlparse
from django.contrib.sites.models import Site as DjangoSite

from cast.filters import PostFilterset
from cast.models import (
    Blog,
)
from cast.models.repository import (
    BlogIndexContext,
    FeedContext,
    PostDetailContext,
    PostQuerySnapshot,
)


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
        chapters_by_audio_id={},
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
