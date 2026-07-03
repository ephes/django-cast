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


@pytest.mark.django_db
def test_blog_index_repository_via_django_models_site_is_none(rf):
    """Make sure the repository can be created from django models when site is None."""
    blog = Blog(id=1, title="Some blog", template_base_dir="plain")
    request = rf.get("/foobar/")
    repository = BlogIndexContext.create_from_django_models(request=request, blog=blog)
    assert repository.root_nav_links == []


@pytest.mark.django_db
def test_blog_index_repository_via_django_models_no_audio_player(rf, blog):
    """Make sure has_audio is False if there's no post with audio."""
    request = rf.get("/foobar/")
    create_post(blog=blog)
    repository = BlogIndexContext.create_from_django_models(request=request, blog=blog)
    assert repository.use_audio_player is False


@pytest.mark.django_db
def test_blog_index_repository_uses_post_cover_image(rf, blog, image):
    post = create_post(blog=blog)
    post.cover_image = image
    post.cover_alt_text = "Cover alt text"
    post.save()

    request = rf.get("/foobar/")
    repository = BlogIndexContext.create_from_django_models(request=request, blog=blog)

    [post_from_repo] = repository.pagination_context["object_list"]
    assert post_from_repo.cover_image_url == image.file.url
    assert post_from_repo.cover_alt_text_display == post.cover_alt_text


def test_apply_cover_fallback_uses_blog_cover():
    cover_url, cover_alt = apply_cover_fallback("", "", "/media/blog.jpg", "Blog alt text")
    assert cover_url == "/media/blog.jpg"
    assert cover_alt == "Blog alt text"


def test_build_media_lookup_groups_media_by_kind():
    from cast.models.repository.builders import build_media_lookup

    images = {10: "image-10", 11: "image-11"}
    videos = {20: "video-20"}
    audios = {30: "audio-30"}
    media_lookup = build_media_lookup(
        1,
        images_by_post_id={1: {10, 11}},
        videos_by_post_id={1: {20}},
        audios_by_post_id={1: {30}},
        images=images,
        videos=videos,
        audios=audios,
    )
    assert media_lookup == {
        "image": {10: "image-10", 11: "image-11"},
        "video": {20: "video-20"},
        "audio": {30: "audio-30"},
    }


def test_build_media_lookup_omits_empty_kinds_for_post_without_media():
    from cast.models.repository.builders import build_media_lookup

    # A post with no media of any kind must yield an empty mapping (no empty
    # "image"/"video"/"audio" sub-dicts), matching the previous inline behavior.
    media_lookup = build_media_lookup(
        99,
        images_by_post_id={},
        videos_by_post_id={},
        audios_by_post_id={},
        images={},
        videos={},
        audios={},
    )
    assert media_lookup == {}


@pytest.mark.django_db
def test_data_for_blog_cachable_includes_blog_cover_image(rf, blog, image):
    blog.cover_image = image
    blog.cover_alt_text = "Blog cover alt"
    blog.save()

    request = rf.get("/blog/")
    data = data_for_blog_cachable(
        request=request,
        blog=blog,
        is_paginated=False,
        post_queryset=blog.unfiltered_published_posts,
    )

    assert data["blog_cover_image_url"] == image.file.url
    assert data["blog_cover_alt_text"] == blog.cover_alt_text


@pytest.mark.django_db
def test_data_for_blog_cachable_uses_request_site(rf, blog):
    other_site = WagtailSite.objects.create(
        hostname="example.com",
        port=80,
        root_page=blog.get_site().root_page,
        is_default_site=False,
    )
    request = rf.get("/blog/", HTTP_HOST="example.com")
    request.htmx = False
    data = data_for_blog_cachable(
        request=request,
        blog=blog,
        is_paginated=False,
        post_queryset=blog.unfiltered_published_posts,
    )
    assert data["site"]["id"] == other_site.id


def test_add_queryset_data_includes_page_url_maps():
    data = add_queryset_data(
        {},
        queryset_data(
            page_url_by_id={1: "/post/"},
            absolute_page_url_by_id={1: "https://example.com/post/"},
        ),
    )
    assert data["page_url_by_id"] == {1: "/post/"}
    assert data["absolute_page_url_by_id"] == {1: "https://example.com/post/"}


def test_add_site_raw_uses_blog_site_if_request_has_no_site(rf, blog, mocker):
    request = rf.get("/blog/", HTTP_HOST="no-such-host.local")
    mocker.patch("cast.models.repository.builders.Site.find_for_request", return_value=None)
    data = add_site_raw({}, request=request, blog=blog)
    assert data["site"]["id"] == blog.get_site().id


@pytest.mark.django_db
def test_add_site_raw_falls_back_to_sql_when_no_context():
    data = add_site_raw({})
    assert "site" in data
    assert "id" in data["site"]


def test_add_site_raw_handles_empty_site_table(mocker):
    class EmptySiteCursor:
        description = [
            ("id",),
            ("hostname",),
            ("port",),
            ("site_name",),
            ("root_page_id",),
            ("is_default_site",),
        ]

        def execute(self, *_args, **_kwargs):
            return None

        def fetchone(self):
            return None

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

    mocker.patch("cast.models.repository.builders.Site.find_for_request", return_value=None)
    mocker.patch("cast.models.repository.builders.connection.cursor", return_value=EmptySiteCursor())
    data = add_site_raw({})
    assert "site" not in data


def test_page_link_handler_expand_db_attributes_single():
    PageLinkHandlerWithCache.cache_url(1, "/foo-bar/")
    tag = PageLinkHandlerWithCache.expand_db_attributes({"id": 1})
    assert tag == '<a href="/foo-bar/">'


def test_page_link_handler_expand_db_attributes_many(mocker):
    PageLinkHandlerWithCache.cache.clear()
    # all urls are cached
    PageLinkHandlerWithCache.cache_url(1, "/foo-bar/")
    PageLinkHandlerWithCache.cache_url(2, "/bar-foo/")
    tags = PageLinkHandlerWithCache.expand_db_attributes_many([{"id": 1}, {"id": 2}])
    assert tags[0] == '<a href="/foo-bar/">'
    assert tags[1] == '<a href="/bar-foo/">'

    # super is called - only happens in Wagtail >= 6.1
    mocker.patch("wagtail.rich_text.pages.PageLinkHandler.expand_db_attributes_many", create=True)
    tags = PageLinkHandlerWithCache.expand_db_attributes_many([{"id": 1}, {"id": 3}])
    assert tags.is_called_once()


def test_page_link_handler_cache_isolation_across_contexts():
    page_id = 887766
    context_1 = copy_context()
    context_2 = copy_context()

    context_1.run(lambda: PageLinkHandlerWithCache.cache.clear())
    context_2.run(lambda: PageLinkHandlerWithCache.cache.clear())

    context_1.run(lambda: PageLinkHandlerWithCache.cache_url(page_id, "/from-context-1/"))
    context_2.run(lambda: PageLinkHandlerWithCache.cache_url(page_id, "/from-context-2/"))

    assert context_1.run(lambda: PageLinkHandlerWithCache.expand_db_attributes({"id": page_id})) == (
        '<a href="/from-context-1/">'
    )
    assert context_2.run(lambda: PageLinkHandlerWithCache.expand_db_attributes({"id": page_id})) == (
        '<a href="/from-context-2/">'
    )


def test_page_link_handler_clear_cache_isolated_per_context():
    page_id = 556677
    context_1 = copy_context()
    context_2 = copy_context()

    context_1.run(lambda: PageLinkHandlerWithCache.cache.clear())
    context_2.run(lambda: PageLinkHandlerWithCache.cache.clear())

    context_1.run(lambda: PageLinkHandlerWithCache.cache_url(page_id, "/context-1-url/"))
    context_2.run(lambda: PageLinkHandlerWithCache.cache_url(page_id, "/context-2-url/"))

    context_1.run(lambda: PageLinkHandlerWithCache.cache.clear())

    assert context_1.run(lambda: PageLinkHandlerWithCache.cache.get(page_id)) is None
    assert context_2.run(lambda: PageLinkHandlerWithCache.cache.get(page_id)) == "/context-2-url/"


def test_page_link_handler_cache_mapping_behaves_like_dict():
    page_id = 223344
    context = copy_context()

    # Fresh context lazily initializes an empty cache.
    assert context.run(lambda: PageLinkHandlerWithCache.cache.get(page_id)) is None

    context.run(lambda: PageLinkHandlerWithCache.cache.clear())
    assert context.run(lambda: len(PageLinkHandlerWithCache.cache)) == 0

    context.run(lambda: PageLinkHandlerWithCache.cache_url(page_id, "/cache-url/"))
    assert context.run(lambda: list(PageLinkHandlerWithCache.cache)) == [page_id]
    assert context.run(lambda: PageLinkHandlerWithCache.cache[page_id]) == "/cache-url/"

    context.run(lambda: PageLinkHandlerWithCache.cache.__delitem__(page_id))
    assert context.run(lambda: len(PageLinkHandlerWithCache.cache)) == 0

    context.run(lambda: PageLinkHandlerWithCache.cache_url(page_id, "/cache-url/"))
    assert context.run(lambda: PageLinkHandlerWithCache.cache.pop(page_id)) == "/cache-url/"


def test_page_link_handler_cache_lazy_init_in_empty_context():
    page_id = 778899
    empty_context = Context()
    assert empty_context.run(lambda: PageLinkHandlerWithCache.cache.get(page_id)) is None


@pytest.mark.django_db
def test_feed_context_create_from_django_models_clears_page_link_cache(rf, blog, mocker):
    clear_cached_page_urls = mocker.patch("cast.models.repository.contexts.clear_cached_page_urls")
    request = rf.get("/blog/")
    FeedContext.create_from_django_models(
        request=request,
        blog=blog,
        post_queryset=blog.unfiltered_published_posts,
    )
    clear_cached_page_urls.assert_called_once()


@pytest.mark.django_db
def test_post_detail_context_create_from_django_models_clears_page_link_cache(rf, blog, mocker):
    clear_cached_page_urls = mocker.patch("cast.models.repository.contexts.clear_cached_page_urls")
    request = rf.get("/post/")
    post = create_post(blog=blog)
    PostDetailContext.create_from_django_models(request=request, post=post)
    clear_cached_page_urls.assert_called_once()


@pytest.mark.django_db
def test_blog_index_context_create_from_django_models_clears_page_link_cache(rf, blog, mocker):
    clear_cached_page_urls = mocker.patch("cast.models.repository.contexts.clear_cached_page_urls")
    request = rf.get("/blog/")
    BlogIndexContext.create_from_django_models(request=request, blog=blog)
    clear_cached_page_urls.assert_called_once()


@pytest.mark.django_db
def test_blog_index_context_create_from_cachable_data_clears_page_link_cache(mocker):
    clear_cached_page_urls = mocker.patch("cast.models.repository.contexts.clear_cached_page_urls")
    data = {
        "template_base_dir": "bootstrap4",
        "blog": {"id": 1, "title": "Some blog", "slug": "some-blog"},
        "post_by_id": {1: {"pk": 1}},
        "posts": [1],
        "page_url_by_id": {1: "/foo-bar-baz/"},
        "absolute_page_url_by_id": {1: "http://testserver/foo-bar-baz/"},
        "pagination_context": {},
        "audios": {},
        "images": {},
        "videos": {},
        "renditions_for_posts": {},
        "audios_by_post_id": {},
        "videos_by_post_id": {},
        "images_by_post_id": {},
        "cover_by_post_id": {},
        "cover_alt_by_post_id": {},
        "owner_username_by_id": {1: "owner"},
        "has_audio_by_id": {1: False},
        "root_nav_links": [],
        "filterset": {
            "get_params": {},
            "date_facets_choices": [],
            "category_facets_choices": [],
            "tag_facets_choices": [],
        },
    }
    BlogIndexContext.create_from_cachable_data(data=data)
    clear_cached_page_urls.assert_called_once()


@pytest.mark.django_db
def test_blog_index_context_clears_stale_cache_entries(rf, blog):
    """Verify stale page-link cache entries are removed and current entries populated."""
    from cast.wagtail_hooks import PageLinkHandlerWithCache

    # Seed a stale entry
    PageLinkHandlerWithCache.cache[9999] = "/stale-url/"
    try:
        request = rf.get("/blog/")
        BlogIndexContext.create_from_django_models(request=request, blog=blog)
        # Stale entry must be gone
        assert 9999 not in PageLinkHandlerWithCache.cache
    finally:
        PageLinkHandlerWithCache.cache.pop(9999, None)


@pytest.mark.django_db
def test_queryset_data_create_from_post_queryset_and_post_detail_cover_is_not_none(rf, blog, image):
    post = create_post(blog=blog)
    post.cover_image = image
    post.cover_alt_text = "foo alt text"
    post.save()

    request = rf.get("/foobar/")

    # make sure the cover is not None for queryset data
    queryset_data = PostQuerySnapshot.create_from_post_queryset(
        request=request, site=None, queryset=blog.unfiltered_published_posts
    )
    assert queryset_data.cover_by_post_id[post.id] == image.file.url
    assert queryset_data.cover_alt_by_post_id[post.id] == post.cover_alt_text

    # make sure the cover is not None for post detail repository
    repository = PostDetailContext.create_from_django_models(request=request, post=post)
    assert repository.cover_image_url == image.file.url
    assert repository.cover_alt_text == "foo alt text"

    # make sure it is not None even if the cover is None
    post.cover_image = None
    post.cover_alt_text = ""  # cannot be null
    post.save()

    queryset_data = PostQuerySnapshot.create_from_post_queryset(
        request=request, site=None, queryset=blog.unfiltered_published_posts
    )
    assert queryset_data.cover_by_post_id[post.id] == ""
    assert queryset_data.cover_alt_by_post_id[post.id] == ""

    repository = PostDetailContext.create_from_django_models(request=request, post=post)
    assert repository.cover_image_url == ""
    assert repository.cover_alt_text == ""


@pytest.mark.django_db
def test_queryset_data_create_from_post_queryset_includes_transcripts(rf, episode):
    transcript = create_transcript(audio=episode.podcast_audio)
    request = rf.get("/foobar/")
    queryset_data = PostQuerySnapshot.create_from_post_queryset(
        request=request,
        site=episode.podcast.get_site(),
        queryset=Post.objects.live().descendant_of(episode.podcast),
    )
    podcast_audio = queryset_data.podcast_audio_by_episode_id[episode.id]
    assert queryset_data.transcript_by_audio_id[podcast_audio.id].id == transcript.id


@pytest.mark.django_db
def test_queryset_data_create_from_post_queryset_handles_episode_without_podcast_audio(rf, episode):
    episode.podcast_audio = None
    episode.save()
    request = rf.get("/foobar/")
    queryset_data = PostQuerySnapshot.create_from_post_queryset(
        request=request,
        site=episode.podcast.get_site(),
        queryset=Post.objects.live().descendant_of(episode.podcast),
    )
    assert episode.id not in queryset_data.podcast_audio_by_episode_id


@pytest.mark.django_db
def test_post_queryset_snapshot_bulk_fetches_non_episode_specific_models(rf, blog):
    post = create_post(blog=blog)

    class OtherPost(Post):
        class Meta:
            proxy = True
            app_label = "cast"

    class FakeManager:
        @staticmethod
        def count():
            return 0

        @staticmethod
        def all():
            return []

    class FakePost:
        pk = post.pk
        owner = post.owner
        cover_image = None
        cover_alt_text = ""
        specific_class = OtherPost
        videos = FakeManager()
        audios = FakeManager()
        audio_in_body = False
        full_url = "http://testserver/fake-post/"

        @staticmethod
        def get_url(**_kwargs):
            return "/fake-post/"

        @staticmethod
        def get_all_images():
            return []

    class FakeQuerySet(list):
        model = Post

        def select_related(self, *_args):
            return self

        def prefetch_related(self, *_args):
            return self

    queryset_data = PostQuerySnapshot.create_from_post_queryset(
        request=rf.get("/"), site=None, queryset=FakeQuerySet([FakePost()])
    )

    assert isinstance(queryset_data.post_by_id[post.pk], OtherPost)


@pytest.mark.django_db
def test_post_queryset_snapshot_bulk_fetches_episode_subclass_specific_models(rf, episode):
    transcript = create_transcript(audio=episode.podcast_audio)
    season = Season.objects.create(podcast=episode.podcast, number=1, name="Subclass season")
    episode.season = season
    episode.save(update_fields=["season"])

    class OtherEpisode(Episode):
        class Meta:
            proxy = True
            app_label = "cast"

    class FakeManager:
        @staticmethod
        def count():
            return 0

        @staticmethod
        def all():
            return []

    class FakePost:
        pk = episode.pk
        owner = episode.owner
        cover_image = None
        cover_alt_text = ""
        specific_class = OtherEpisode
        videos = FakeManager()
        audios = FakeManager()
        audio_in_body = False
        full_url = "http://testserver/fake-episode/"

        @staticmethod
        def get_url(**_kwargs):
            return "/fake-episode/"

        @staticmethod
        def get_all_images():
            return []

    class FakeQuerySet(list):
        model = Post

        def select_related(self, *_args):
            return self

        def prefetch_related(self, *_args):
            return self

    queryset_data = PostQuerySnapshot.create_from_post_queryset(
        request=rf.get("/"), site=None, queryset=FakeQuerySet([FakePost()])
    )
    snapshot_episode = queryset_data.post_by_id[episode.pk]

    assert isinstance(snapshot_episode, OtherEpisode)
    assert queryset_data.transcript_by_audio_id[episode.podcast_audio_id].pk == transcript.pk
    reset_queries()
    with connection.execute_wrapper(blocker):
        assert snapshot_episode.podcast_audio.transcript.pk == transcript.pk
        assert snapshot_episode.season.number == season.number
    assert len(connection.queries) == 0


def test_queryset_data_create_from_post_queryset_raises_attribute_error_for_broken_transcript(rf, mocker):
    class BrokenTranscriptAudio:
        pk = 42

        @property
        def transcript(self):
            raise AttributeError("broken transcript property")

    class SpecificPost:
        podcast_audio = BrokenTranscriptAudio()

    class FakeManager:
        @staticmethod
        def all():
            return []

    class FakePost:
        pk = 1
        owner = type("Owner", (), {"username": "owner"})()
        has_audio = True
        full_url = "http://testserver/fake-post/"
        cover_image = None
        cover_alt_text = ""
        specific = SpecificPost()
        videos = FakeManager()
        audios = FakeManager()

        @staticmethod
        def get_url(**_kwargs):
            return "/fake-post/"

        @staticmethod
        def get_all_images():
            return []

    class FakeQuerySet(list):
        def select_related(self, *_args):
            return self

        def prefetch_related(self, *_args):
            return self

    mocker.patch("cast.models.pages.Post.get_all_renditions_from_queryset", return_value={})
    fake_queryset = FakeQuerySet([FakePost()])
    with pytest.raises(AttributeError, match="broken transcript property"):
        PostQuerySnapshot.create_from_post_queryset(request=rf.get("/"), site=None, queryset=fake_queryset)


def test_serialize_transcript_no_collection():
    class Podlove:
        name = "foo"

    class TranscriptFile:
        name = "blub"

    class Transcript:
        pk = 1
        audio_id = 1
        podlove = Podlove()
        vtt = TranscriptFile()
        dote = TranscriptFile()
        collection_id = None

    result = serialize_transcript(Transcript())
    assert result["collection"] is None


class TestBlogUrlFromReferer:
    """Test that _blog_url_from_referer preserves pagination state from the HTTP referer."""

    def test_no_referer_returns_base_url(self, rf):
        request = rf.get("/some-post/")
        assert _blog_url_from_referer(request, "/blog/") == "/blog/"

    def test_referer_with_page_param(self, rf):
        request = rf.get("/some-post/", HTTP_REFERER="http://testserver/blog/?page=3")
        assert _blog_url_from_referer(request, "/blog/") == "/blog/?page=3"

    def test_referer_without_query_returns_base_url(self, rf):
        request = rf.get("/some-post/", HTTP_REFERER="http://testserver/blog/")
        assert _blog_url_from_referer(request, "/blog/") == "/blog/"

    def test_referer_from_different_host_returns_base_url(self, rf):
        request = rf.get("/some-post/", HTTP_REFERER="http://evil.com/blog/?page=3")
        assert _blog_url_from_referer(request, "/blog/") == "/blog/"

    def test_referer_path_does_not_match_blog(self, rf):
        request = rf.get("/some-post/", HTTP_REFERER="http://testserver/other/?page=2")
        assert _blog_url_from_referer(request, "/blog/") == "/blog/"

    def test_referer_with_multiple_query_params(self, rf):
        request = rf.get("/some-post/", HTTP_REFERER="http://testserver/blog/?page=2&tag=python")
        assert _blog_url_from_referer(request, "/blog/") == "/blog/?page=2&tag=python"

    def test_empty_referer_returns_base_url(self, rf):
        request = rf.get("/some-post/", HTTP_REFERER="")
        assert _blog_url_from_referer(request, "/blog/") == "/blog/"

    def test_trailing_slash_mismatch_referer_without(self, rf):
        """Referer /blog without trailing slash should still match base /blog/."""
        request = rf.get("/some-post/", HTTP_REFERER="http://testserver/blog?page=2")
        assert _blog_url_from_referer(request, "/blog/") == "/blog/?page=2"

    def test_trailing_slash_mismatch_base_without(self, rf):
        """Base /blog without trailing slash should still match referer /blog/."""
        request = rf.get("/some-post/", HTTP_REFERER="http://testserver/blog/?page=2")
        assert _blog_url_from_referer(request, "/blog") == "/blog?page=2"

    def test_referer_with_theme_and_page(self, rf):
        request = rf.get("/some-post/", HTTP_REFERER="http://testserver/blog/?page=2&theme=bootstrap5")
        assert _blog_url_from_referer(request, "/blog/") == "/blog/?page=2&theme=bootstrap5"

    def test_same_host_with_explicit_port(self, rf, settings):
        settings.ALLOWED_HOSTS = ["localhost"]
        request = rf.get(
            "/some-post/",
            HTTP_REFERER="http://localhost:8000/blog/?page=3",
            SERVER_NAME="localhost",
            SERVER_PORT="8000",
        )
        assert _blog_url_from_referer(request, "/blog/") == "/blog/?page=3"
