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


# Test page link handler with cache


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


@pytest.mark.django_db
def test_post_detail_blog_url_preserves_pagination_from_referer(rf, post_in_blog):
    """When navigating from a paginated blog index, the 'Return to blog' link should
    preserve the page parameter so the user returns to the same page."""
    post = post_in_blog
    blog = post.blog
    blog_url = blog.get_url()
    referer = f"http://testserver{blog_url}?page=3"
    request = rf.get(post.get_url(), HTTP_REFERER=referer)
    repository = PostDetailContext.create_from_django_models(request=request, post=post)
    assert repository.blog_url == f"{blog_url}?page=3"


@pytest.mark.django_db
def test_post_detail_blog_url_without_referer(rf, post_in_blog):
    """Without a referer, blog_url should be the plain blog URL."""
    post = post_in_blog
    blog = post.blog
    request = rf.get(post.get_url())
    repository = PostDetailContext.create_from_django_models(request=request, post=post)
    assert repository.blog_url == blog.get_url()


@pytest.mark.django_db
def test_render_post_detail_with_django_models_repository(rf, post_in_blog):
    """
    This test should just use the default repository and fetch all data from the database.
    """
    # Given a post with a gallery, an image, a video and an audio
    post = post_in_blog
    post_url = post.get_url()
    request = rf.get(post_url)
    repository = PostDetailContext.create_from_django_models(request=request, post=post)
    reset_queries()
    # When we render the post detail page
    # with connection.execute_wrapper(blocker):
    response = post.serve(request, repository=repository).render()
    html = response.content.decode("utf-8")
    # Then the media should be rendered
    assert "web-player/embed.5.js" in html  # audio player because has_audio is True
    assert post.title in html
    assert repository.page_url in html
    assert repository.owner_username.capitalize() in html
    assert "audio_1" in html
    assert "<video" in html
    assert '<section class="block-image">' in html
    assert '<section class="block-gallery">' in html
    # And the database should not be hit
    assert len(connection.queries) == 0


@pytest.mark.django_db
def test_render_blog_index_with_django_models_repository(rf, post_in_blog):
    # Given a blog with a post
    post = post_in_blog
    blog = post.blog
    author_name = post.owner.username.capitalize()
    post_detail_url = post.get_url()
    request = rf.get(blog.get_url())
    request.htmx = False
    # The blog index repository is created from django models
    repository = BlogIndexContext.create_from_django_models(request=request, blog=blog)
    # When we render the blog index
    reset_queries()
    response = blog.serve(request, repository=repository).render()
    # Then post data should be generated on the fly and the media should be rendered
    assert isinstance(response.context_data["repository"], BlogIndexContext)
    html = response.content.decode("utf-8")
    assert author_name in html
    assert post_detail_url in html
    assert response.context_data["is_paginated"] is False
    # Then the media should be rendered
    assert "web-player/embed.5.js" in html  # audio player because has_audio is True
    assert post.title in html
    assert "audio_1" in html
    assert "<video" in html
    assert '<section class="block-image">' in html
    assert '<section class="block-gallery">' in html
    # And the database should not be hit
    assert len(connection.queries) == 0


@pytest.mark.django_db
def test_render_feed_with_django_models_repository(rf, post_in_blog):
    # Given a post in a blog having a feed
    post = post_in_blog
    blog = post.blog
    post_queryset = blog.unfiltered_published_posts
    repository = FeedContext.create_from_django_models(
        request=rf.get("/"), blog=blog, post_queryset=post_queryset, template_base_dir="bootstrap4"
    )
    feed_url = reverse("cast:latest_entries_feed", kwargs={"slug": blog.slug})
    request = rf.get(feed_url)
    view = LatestEntriesFeed(repository=repository)
    django_site = DjangoSite(domain="testserver", name="testserver")
    sites_models.SITE_CACHE[1] = django_site  # cache site to avoid db hit
    reset_queries()
    # When we render the feed
    # with connection.execute_wrapper(blocker):
    response = view(request, slug=blog.slug)
    html = response.content.decode("utf-8")
    # Then the post title should be rendered
    assert post.title in html
    # And the database should be hit
    assert len(connection.queries) == 0


@pytest.mark.django_db
def test_feed_context_create_from_django_models_handles_missing_request_site(rf, blog, mocker):
    request = rf.get("/feed/", HTTP_HOST="no-such-host.local")
    post_queryset = blog.unfiltered_published_posts.none()
    mocker.patch("cast.models.repository.contexts.Site.find_for_request", return_value=None)
    mocker.patch(
        "cast.models.repository.contexts.PostQuerySnapshot.create_from_post_queryset",
        return_value=queryset_data(post_queryset=[]),
    )

    repository = FeedContext.create_from_django_models(
        request=request, blog=blog, post_queryset=post_queryset, template_base_dir="bootstrap4"
    )

    assert repository.site is None
    assert repository.root_nav_links == []


# Test render post detail, blog index and blog feed with cachable data
# provided without hitting the database


class StubFile:
    def __init__(self, name):
        self.name = name
        self.url = f"/media/{name}"


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


def test_render_blog_index_without_hitting_the_database(rf, blog_data):
    """
    Given a blog including a post with media which is not in the database. And a repository
    containing the media needed to render the blog index page.

    When we render the blog index page, then the media should be rendered and
    the database should not be hit.
    """
    data = blog_data
    reset_queries()
    # with connection.execute_wrapper(blocker):
    repository = BlogIndexContext.create_from_cachable_data(data=data)
    blog = repository.blog
    request = rf.get("/some-blog/")
    request.htmx = False
    # with connection.execute_wrapper(blocker):
    response = blog.serve(request, repository=repository).render()
    html = response.content.decode("utf-8")
    assert "Owner" in html
    assert "audio_1" in html
    assert "<video" in html
    assert '<section class="block-image">' in html
    assert "1110w" in html
    assert '<section class="block-gallery">' in html
    context = response.context_data
    assert context["template_base_dir"] == repository.template_base_dir
    assert context["root_nav_links"] == repository.root_nav_links
    assert len(connection.queries) == 0


def test_render_podcast_index_without_hitting_the_database(rf, blog_data):
    """
    Given a podcast including a post with media which is not in the database. And a repository
    containing the media needed to render the podcast index page.

    When we render the podcast index page, then the media should be rendered and
    the database should not be hit.
    """
    data = blog_data
    # add postcast_audio
    data["post_by_id"][1]["podcast_audio"] = data["audios"][1]
    reset_queries()
    # with connection.execute_wrapper(blocker):
    repository = BlogIndexContext.create_from_cachable_data(data=data)
    podcast = Podcast(id=1, title="Some podcast", slug="some-podcast")
    request = rf.get("/some-podcast/")
    request.htmx = False
    # with connection.execute_wrapper(blocker):
    response = podcast.serve(request, repository=repository).render()
    html = response.content.decode("utf-8")
    assert "Owner" in html
    assert "audio_1" in html
    assert "<video" in html
    assert '<section class="block-image">' in html
    assert "1110w" in html
    assert '<section class="block-gallery">' in html
    context = response.context_data
    assert context["template_base_dir"] == repository.template_base_dir
    assert context["root_nav_links"] == repository.root_nav_links
    assert len(connection.queries) == 0


def test_render_feed_without_hitting_the_database(rf, blog_data):
    """
    Given a blog including a post with media which is not in the database. And a repository
    containing the media needed to render the feed.

    When we render the blog feed, then the database should not be hit.
    """
    data = deepcopy(blog_data)
    data.update(
        {
            "site": {"id": 1},
            "blog": {"id": 1, "title": "Some blog", "slug": "some-blog"},
            "blog_url": "/some-blog/",
            "is_podcast": False,
        }
    )
    reset_queries()
    repository = FeedContext.create_from_cachable_data(data=data)
    feed_url = reverse("cast:latest_entries_feed", kwargs={"slug": "some-blog"})
    request = rf.get(feed_url)
    view = LatestEntriesFeed(repository=repository)
    django_site = DjangoSite(domain="testserver", name="testserver")
    sites_models.SITE_CACHE[1] = django_site  # cache site to avoid db hit
    reset_queries()
    # When we render the feed
    # with connection.execute_wrapper(blocker):
    response = view(request, slug="some-blog")
    html = response.content.decode("utf-8")
    assert data["post_by_id"][1]["title"] in html
    # And the database should be hit
    assert len(connection.queries) == 0


# Render post detail from cachable data is still missing


@pytest.mark.django_db
def test_render_blog_index_with_data_from_cache_without_hitting_the_database(rf, settings):
    # Given a post with media in a blog
    settings.DEFAULT_FILE_STORAGE = "django.core.files.storage.FileSystemStorage"
    blog = generate_blog_with_media(number_of_posts=6)
    post = blog.unfiltered_published_posts.first()
    author_name = post.owner.username.capitalize()
    post_detail_url = post.get_url()
    request = rf.get(blog.get_url())
    request.htmx = False
    # _ = post.serve(rf.get("/")).render()  # force renditions to be created
    create_missing_renditions_for_posts([post])  # force renditions to be created

    # Set up the cache
    cachable_data = BlogIndexContext.data_for_blog_index_cachable(request=request, blog=blog)
    pickled = pickle.dumps(cachable_data)  # make sure it's really cachable by pickling it
    cachable_data = pickle.loads(pickled)
    repository = BlogIndexContext.create_from_cachable_data(data=cachable_data)

    # When we render the blog index
    # call this once without blocker to populate SITE_CACHE
    reset_queries()
    with connection.execute_wrapper(blocker):
        response = blog.serve(request, repository=repository).render()
    # Then the media should be rendered
    html = response.content.decode("utf-8")
    assert 'class="cast-image"' in html
    assert 'class="cast-gallery-modal"' in html
    assert 'class="block-video"' in html
    assert 'class="block-audio"' in html
    assert author_name in html
    assert post_detail_url in html
    assert response.context_data["is_paginated"] is True
    # And the database should not be hit
    show_queries(connection.queries)
    assert len(connection.queries) == 0


@pytest.mark.django_db
def test_render_blog_feed_with_data_from_cache_without_hitting_the_database(rf, settings):
    # Given a post with media in a blog
    settings.DEFAULT_FILE_STORAGE = "django.core.files.storage.FileSystemStorage"
    blog = generate_blog_with_media(number_of_posts=6)
    post = blog.unfiltered_published_posts.first()
    author_name = post.owner.username.capitalize()
    post_detail_url = post.get_url()
    request = rf.get(blog.get_url())
    request.htmx = False
    # _ = post.serve(rf.get("/")).render()  # force renditions to be created
    create_missing_renditions_for_posts([post])  # force renditions to be created
    # _ = post.serve(rf.get("/")).render()  # force renditions to be created
    create_missing_renditions_for_posts([post])  # force renditions to be created

    # Set up the cache
    cachable_data = FeedContext.data_for_feed_cachable(request=request, blog=blog)
    pickled = pickle.dumps(cachable_data)  # make sure it's really cachable by pickling it
    cachable_data = pickle.loads(pickled)
    repository = FeedContext.create_from_cachable_data(data=cachable_data)

    # When we render the blog index
    # call this once without blocker to populate SITE_CACHE
    reset_queries()
    # with connection.execute_wrapper(blocker):
    response = LatestEntriesFeed(repository=repository)(request, slug=blog.slug)
    # Then the media should be rendered
    html = response.content.decode("utf-8")
    assert 'class="cast-image"' in html
    assert 'class="cast-gallery-modal"' in html
    assert 'class="block-video"' in html
    assert 'class="block-audio"' in html
    assert author_name in html
    assert post_detail_url in html
    # And the database should not be hit
    # show_queries(connection.queries)
    assert len(connection.queries) == 0


@pytest.mark.django_db
def test_render_podcast_feed_with_data_from_cache_without_hitting_the_database(rf, settings):
    # Given a post with media in a blog
    settings.DEFAULT_FILE_STORAGE = "django.core.files.storage.FileSystemStorage"
    blog = generate_blog_with_media(number_of_posts=6, podcast=True)
    post = blog.unfiltered_published_posts.first()
    author_name = post.owner.username.capitalize()
    post_detail_url = post.get_url()
    request = rf.get(blog.get_url())

    request.htmx = False
    # _ = post.serve(rf.get("/")).render()  # force renditions to be created
    create_missing_renditions_for_posts([post])  # force renditions to be created
    # _ = post.serve(rf.get("/")).render()  # force renditions to be created
    create_missing_renditions_for_posts([post])  # force renditions to be created

    # Set up the cache
    cachable_data = FeedContext.data_for_feed_cachable(request=request, blog=blog, is_podcast=True)
    pickled = pickle.dumps(cachable_data)  # make sure it's really cachable by pickling it
    cachable_data = pickle.loads(pickled)
    repository = FeedContext.create_from_cachable_data(data=cachable_data)

    # When we render the blog index
    # call this once without blocker to populate SITE_CACHE
    reset_queries()
    # with connection.execute_wrapper(blocker):
    response = RssPodcastFeed(repository=repository)(request, slug=blog.slug, audio_format="mp3")

    # Then the media should be rendered
    html = response.content.decode("utf-8")
    assert 'class="cast-image"' in html
    assert 'class="cast-gallery-modal"' in html
    assert 'class="block-video"' in html
    assert 'class="block-audio"' in html
    assert "podcast:transcript" in html
    assert author_name in html
    assert post_detail_url in html
    # And the database should not be hit
    # show_queries(connection.queries)
    assert len(connection.queries) == 0


@pytest.mark.django_db
def test_render_podcast_feed_with_cached_episode_contributors(rf, settings, episode, image):
    settings.DEFAULT_FILE_STORAGE = "django.core.files.storage.FileSystemStorage"
    contributor = Contributor.objects.create(display_name="Cached Guest", slug="cached-guest", avatar=image)
    link = ContributorLink.objects.create(
        contributor=contributor,
        service=ContributorLink.SERVICE_WEBSITE,
        url="https://example.com/cached-guest",
        sort_order=0,
    )
    EpisodeContributor.objects.create(
        episode=episode,
        contributor=contributor,
        role=EpisodeContributor.ROLE_GUEST,
        link=link,
        sort_order=0,
    )
    request = rf.get(episode.podcast.get_url())
    request.htmx = False
    cachable_data = FeedContext.data_for_feed_cachable(request=request, blog=episode.podcast, is_podcast=True)
    pickled = pickle.dumps(cachable_data)
    cachable_data = pickle.loads(pickled)
    repository = FeedContext.create_from_cachable_data(data=cachable_data)
    feed_url = reverse("cast:podcast_feed_rss", kwargs={"slug": episode.podcast.slug, "audio_format": "m4a"})
    request = rf.get(feed_url)
    django_site = DjangoSite(domain="testserver", name="testserver")
    sites_models.SITE_CACHE[1] = django_site

    reset_queries()
    response = RssPodcastFeed(repository=repository)(request, slug=episode.podcast.slug, audio_format="m4a")

    html = response.content.decode("utf-8")
    root = ElementTree.fromstring(html)
    namespace = {"podcast": "https://podcastindex.org/namespace/1.0/"}
    [person] = root.findall(".//podcast:person", namespace)
    assert person.text == "Cached Guest"
    assert person.attrib["role"] == "guest"
    assert person.attrib["href"] == "https://example.com/cached-guest"
    assert person.attrib["img"].startswith("http://testserver/media/")
    assert "fill-80x80" in person.attrib["img"]
    assert len(connection.queries) == 0
    PageLinkHandlerWithCache.cache.clear()


@pytest.mark.django_db
def test_render_episode_detail_with_contributors_from_repository_without_hitting_database(rf, episode, image):
    contributor = Contributor.objects.create(display_name="Detail Guest", slug="detail-guest", avatar=image)
    link = ContributorLink.objects.create(
        contributor=contributor,
        service=ContributorLink.SERVICE_WEBSITE,
        url="https://example.com/detail-guest",
        sort_order=0,
    )
    EpisodeContributor.objects.create(
        episode=episode,
        contributor=contributor,
        role=EpisodeContributor.ROLE_GUEST,
        link=link,
        sort_order=0,
    )
    host = Contributor.objects.create(display_name="Detail Host", slug="detail-host")
    EpisodeContributor.objects.create(
        episode=episode,
        contributor=host,
        role=EpisodeContributor.ROLE_HOST,
        sort_order=1,
    )
    request = rf.get(episode.get_url())
    repository = PostDetailContext.create_from_django_models(request=request, post=episode)

    reset_queries()
    with connection.execute_wrapper(blocker):
        response = episode.serve(request, repository=repository).render()

    html = response.content.decode("utf-8")
    assert 'class="episode-contributors"' in html
    assert 'class="episode-contributors__list"' in html
    assert 'class="episode-contributors__item"' in html
    assert 'class="episode-contributors__identity episode-contributors__identity--link"' in html
    assert "Detail Guest" in html
    assert "Detail Host" in html
    assert "https://example.com/detail-guest" in html
    assert 'src="/media/' in html
    assert "fill-80x80" in html
    assert 'alt=""' in html
    assert 'width="40"' in html
    assert 'height="40"' in html
    assert "episode-contributors__avatar--placeholder" in html
    assert 'aria-hidden="true"' in html
    assert ">D</span>" in html
    assert 'class="episode-contributors__role">Guest</span>' in html
    assert 'class="episode-contributors__role">Host</span>' in html
    assert html.index("Detail Guest") < html.index("Detail Host")
    assert html.index('class="episode-contributors"') < html.index("in_all heading")
    assert len(connection.queries) == 0


@pytest.mark.django_db
def test_render_podcast_feed_from_django_models_with_contributors_without_hitting_database(rf, episode, image):
    for index in range(3):
        contributor = Contributor.objects.create(
            display_name=f"Feed Guest {index}",
            slug=f"feed-guest-{index}",
            avatar=image,
        )
        link = ContributorLink.objects.create(
            contributor=contributor,
            service=ContributorLink.SERVICE_WEBSITE,
            url=f"https://example.com/feed-guest-{index}",
            sort_order=0,
        )
        EpisodeContributor.objects.create(
            episode=episode,
            contributor=contributor,
            role=EpisodeContributor.ROLE_GUEST,
            link=link,
            sort_order=index,
        )
    post_queryset = (
        Episode.objects.live()
        .descendant_of(episode.podcast)
        .select_related("podcast_audio__transcript")
        .filter(podcast_audio__isnull=False)
        .order_by("-visible_date")
    )
    repository = FeedContext.create_from_django_models(
        request=rf.get("/"),
        blog=episode.podcast,
        post_queryset=post_queryset,
        template_base_dir="bootstrap4",
    )
    feed_url = reverse("cast:podcast_feed_rss", kwargs={"slug": episode.podcast.slug, "audio_format": "m4a"})
    request = rf.get(feed_url)
    django_site = DjangoSite(domain="testserver", name="testserver")
    sites_models.SITE_CACHE[1] = django_site

    reset_queries()
    with connection.execute_wrapper(blocker):
        response = RssPodcastFeed(repository=repository)(request, slug=episode.podcast.slug, audio_format="m4a")

    html = response.content.decode("utf-8")
    assert "Feed Guest 0" in html
    assert "Feed Guest 1" in html
    assert "Feed Guest 2" in html
    assert len(connection.queries) == 0


@pytest.mark.django_db
def test_post_queryset_snapshot_caches_episode_contributors_for_base_post_queryset(rf, episode):
    contributor = Contributor.objects.create(display_name="Mixed Feed Guest", slug="mixed-feed-guest")
    EpisodeContributor.objects.create(
        episode=episode,
        contributor=contributor,
        role=EpisodeContributor.ROLE_GUEST,
        sort_order=0,
    )
    post_queryset = Post.objects.live().descendant_of(episode.podcast).order_by("-visible_date")

    queryset_data = PostQuerySnapshot.create_from_post_queryset(
        request=rf.get("/"),
        site=episode.podcast.get_site(),
        queryset=post_queryset,
    )
    snapshot_episode = queryset_data.post_by_id[episode.pk]

    reset_queries()
    with connection.execute_wrapper(blocker):
        assignments = snapshot_episode.visible_contributor_assignments

    assert [assignment.display_name for assignment in assignments] == ["Mixed Feed Guest"]
    assert len(connection.queries) == 0


@pytest.mark.django_db
def test_post_queryset_snapshot_primes_repeated_contributor_avatar_once(rf, episode, mocker):
    contributor = Contributor.objects.create(display_name="Repeat Guest", slug="repeat-guest")
    EpisodeContributor.objects.create(
        episode=episode,
        contributor=contributor,
        role=EpisodeContributor.ROLE_GUEST,
        sort_order=0,
    )
    other_episode = EpisodeFactory(
        owner=episode.owner,
        parent=episode.podcast,
        title="other podcast episode",
        slug="other-podcast-entry",
        podcast_audio=episode.podcast_audio,
        body=episode.body,
    )
    EpisodeContributor.objects.create(
        episode=other_episode,
        contributor=contributor,
        role=EpisodeContributor.ROLE_GUEST,
        sort_order=0,
    )
    compute_avatar_rendition_url = mocker.patch(
        "cast.models.contributors.Contributor._compute_avatar_rendition_url",
        return_value="/media/avatar.webp",
    )
    post_queryset = Post.objects.live().descendant_of(episode.podcast).order_by("-visible_date")

    queryset_data = PostQuerySnapshot.create_from_post_queryset(
        request=rf.get("/"),
        site=episode.podcast.get_site(),
        queryset=post_queryset,
    )
    assignments = [
        queryset_data.post_by_id[episode.pk].visible_contributor_assignments[0],
        queryset_data.post_by_id[other_episode.pk].visible_contributor_assignments[0],
    ]

    assert compute_avatar_rendition_url.call_count == 1
    assert assignments[0].contributor is assignments[1].contributor
    assert [assignment.get_avatar_rendition_url() for assignment in assignments] == [
        "/media/avatar.webp",
        "/media/avatar.webp",
    ]


@pytest.mark.django_db
def test_feed_repository_last_build_date_uses_newest_visible_date(rf, episode):
    older_date = timezone.now() - timezone.timedelta(days=2)
    newer_date = timezone.now()
    episode.visible_date = older_date
    episode.save()
    newer_episode = EpisodeFactory(
        owner=episode.owner,
        parent=episode.podcast,
        title="newer podcast episode",
        slug="newer-podcast-entry",
        visible_date=newer_date,
        podcast_audio=episode.podcast_audio,
        body=episode.body,
    )
    post_queryset = Episode.objects.live().descendant_of(episode.podcast).order_by("visible_date")

    repository = FeedContext.create_from_django_models(
        request=rf.get("/"),
        blog=episode.podcast,
        post_queryset=post_queryset,
        template_base_dir="bootstrap4",
    )
    data = data_for_blog_cachable(
        request=rf.get("/"),
        blog=episode.podcast,
        is_paginated=False,
        post_queryset=post_queryset,
    )

    assert repository.blog.last_build_date == newer_episode.visible_date
    assert data["last_build_date"] == newer_episode.visible_date


# Small tests for repository coverage


def test_serialize_renditions():
    rendition = Rendition(file="foo.jpg", filter_spec="foobarfilter", width=100, height=200)
    renditions = serialize_renditions({1: [rendition]})
    rendition = Rendition(**renditions[1][0])
    assert rendition.file == "foo.jpg"


def test_serialize_media_helpers():
    audio = Audio(
        id=1,
        collection=None,
        duration=None,
        title="Some audio",
        subtitle="Some subtitle",
        data={},
        m4a=StubFile("audio.m4a"),
        mp3=StubFile("audio.mp3"),
        oga=StubFile("audio.oga"),
        opus=StubFile("audio.opus"),
    )
    video = Video(
        id=1,
        collection=None,
        title="Some video",
        original=StubFile("video.mp4"),
        poster=StubFile("poster.jpg"),
        poster_seconds=1,
    )
    image = Image(id=1, title="Some image", collection=None, file=StubFile("image.jpg"), width=100, height=200)

    class Podlove:
        name = "podlove.json"

    class TranscriptFile:
        name = "transcript.vtt"

    class TranscriptStub:
        pk = 1
        audio_id = 1
        podlove = Podlove()
        vtt = TranscriptFile()
        dote = TranscriptFile()
        collection_id = None

    transcript = TranscriptStub()

    assert serialize_audio(audio)["m4a"] == "audio.m4a"
    assert serialize_video(video)["original"] == "video.mp4"
    assert serialize_image(image)["file"] == "image.jpg"
    assert serialize_transcript(transcript)["podlove"] == "podlove.json"


@pytest.mark.django_db
def test_serialize_episode_contributor_roundtrip(episode, image):
    contributor = Contributor.objects.create(
        display_name="Episode Guest",
        slug="episode-guest",
        avatar=image,
        default_role=EpisodeContributor.ROLE_HOST,
    )
    contributor._avatar_rendition_url = "/media/images/test.fill-80x80.format-webp.webp"
    link = ContributorLink.objects.create(
        contributor=contributor,
        service=ContributorLink.SERVICE_WEBSITE,
        url="https://example.com/guest",
        sort_order=0,
    )
    assignment = EpisodeContributor.objects.create(
        episode=episode,
        contributor=contributor,
        role=EpisodeContributor.ROLE_GUEST,
        link=link,
        sort_order=0,
    )
    # Carry the precomputed rendition URL through serialization, not the live FK instance.
    assignment.contributor = contributor

    data = serialize_episode_contributor(assignment)
    rebuilt = deserialize_episode_contributor(data)
    assert rebuilt.contributor.get_avatar_rendition_url() == "/media/images/test.fill-80x80.format-webp.webp"

    assert rebuilt.display_name == "Episode Guest"
    assert rebuilt.contributor.default_role == EpisodeContributor.ROLE_HOST
    assert rebuilt.href == "https://example.com/guest"
    assert rebuilt.contributor_id == contributor.pk
    assert rebuilt.link.contributor_id == contributor.pk
    assert rebuilt.link.contributor is rebuilt.contributor
    assert rebuilt.link.service == ContributorLink.SERVICE_WEBSITE
    assert rebuilt.sort_order == 0
    rebuilt.clean()


@pytest.mark.django_db
def test_serialize_episode_contributor_without_avatar_rendition(episode):
    contributor = Contributor.objects.create(display_name="Plain Guest", slug="plain-guest")
    assignment = EpisodeContributor.objects.create(
        episode=episode,
        contributor=contributor,
        role=EpisodeContributor.ROLE_GUEST,
        sort_order=0,
    )

    data = serialize_episode_contributor(assignment)
    rebuilt = deserialize_episode_contributor(data)

    assert "avatar_rendition_url" not in data["contributor"]
    assert rebuilt.contributor.get_avatar_rendition_url() == ""
    assert rebuilt.href == ""


def test_get_facet_choices():
    class Facet:
        choices = [("foo", "Foo"), ("bar", "Bar")]

    # choices are found
    choices = get_facet_choices({"foobar": Facet()}, "foobar")
    assert choices == Facet.choices


@pytest.mark.django_db
def test_deserialize_blog_returns_blog(blog):
    data = serialize_blog(blog)
    rebuilt = deserialize_blog(data)
    assert isinstance(rebuilt, Blog)
    assert not isinstance(rebuilt, Podcast)
    assert rebuilt.title == blog.title
    assert rebuilt.subtitle == blog.subtitle


@pytest.mark.django_db
def test_serialize_deserialize_blog_roundtrip_podcast(podcast_with_artwork):
    podcast_with_artwork.itunes_categories = "Technology"
    podcast_with_artwork.keywords = "foo,bar"
    podcast_with_artwork.explicit = 2
    podcast_with_artwork.subtitle = "Test subtitle"
    podcast_with_artwork.save(update_fields=["itunes_categories", "keywords", "explicit", "subtitle"])

    data = serialize_blog(podcast_with_artwork)
    rebuilt = deserialize_blog(data)

    assert isinstance(rebuilt, Podcast)
    assert rebuilt.title == podcast_with_artwork.title
    assert rebuilt.subtitle == podcast_with_artwork.subtitle
    assert rebuilt.itunes_categories == podcast_with_artwork.itunes_categories
    assert rebuilt.keywords == podcast_with_artwork.keywords
    assert rebuilt.explicit == podcast_with_artwork.explicit
    assert rebuilt.itunes_artwork is not None
    assert rebuilt.itunes_artwork.original.name == podcast_with_artwork.itunes_artwork.original.name

    # no choices found
    choices = get_facet_choices({}, "foobar")
    assert choices == []


@pytest.mark.django_db
def test_deserialize_blog_roundtrip(blog):
    data = serialize_blog(blog)
    rebuilt = deserialize_blog(data)
    assert isinstance(rebuilt, Blog)
    assert rebuilt.title == blog.title
    assert rebuilt.slug == blog.slug


def test_deserialize_canonical_media_types():
    audio = deserialize_audio(
        {
            "id": 1,
            "duration": None,
            "title": "Some audio",
            "subtitle": "Some subtitle",
            "data": {},
            "m4a": "audio.m4a",
            "mp3": "audio.mp3",
            "oga": "audio.oga",
            "opus": "audio.opus",
            "collection": None,
        }
    )
    transcript = deserialize_transcript(
        {
            "id": 1,
            "audio_id": 1,
            "podlove": "podlove.json",
            "vtt": "transcript.vtt",
            "dote": "transcript.dote",
            "collection": None,
        }
    )
    video = deserialize_video(
        {
            "id": 1,
            "title": "Some video",
            "original": "video.mp4",
            "poster": "poster.jpg",
            "poster_seconds": 1,
            "collection": None,
        }
    )
    image = deserialize_image(
        {
            "pk": 1,
            "title": "Some image",
            "file": "image.jpg",
            "width": 100,
            "height": 200,
            "collection": None,
        }
    )
    post = deserialize_post(
        {
            "id": 1,
            "pk": 1,
            "uuid": "d9f1825b-6f86-4d24-8455-7c3eef4da36f",
            "slug": "post-slug",
            "title": "Post title",
            "visible_date": None,
            "comments_enabled": True,
            "body": "[]",
        }
    )
    episode = deserialize_episode(
        {
            "id": 2,
            "pk": 2,
            "uuid": "b9a1947f-2581-4f8d-b2be-26247ea2f30f",
            "slug": "episode-slug",
            "title": "Episode title",
            "visible_date": None,
            "comments_enabled": True,
            "body": "[]",
            "podcast_audio": {
                "id": 1,
                "duration": None,
                "title": "Some audio",
                "subtitle": "Some subtitle",
                "data": {},
                "m4a": "audio.m4a",
                "mp3": "audio.mp3",
                "oga": "audio.oga",
                "opus": "audio.opus",
                "collection": None,
            },
            "keywords": "",
            "explicit": 0,
            "block": False,
        }
    )
    episode_without_podcast_audio = deserialize_episode(
        {
            "id": 3,
            "pk": 3,
            "uuid": "f05b2e72-9330-472e-9930-84475e912aaf",
            "slug": "episode-without-audio-slug",
            "title": "Episode without audio",
            "visible_date": None,
            "comments_enabled": True,
            "body": "[]",
            "keywords": "",
            "explicit": 0,
            "block": False,
        }
    )

    assert isinstance(audio, Audio)
    assert isinstance(transcript, Transcript)
    assert isinstance(video, Video)
    assert isinstance(image, Image)
    assert isinstance(post, Post)
    assert isinstance(episode, Episode)
    assert isinstance(episode_without_podcast_audio, Episode)


def test_serialize_deserialize_roundtrip_for_media_types():
    audio = Audio(
        id=1,
        collection=None,
        duration=None,
        title="Some audio",
        subtitle="Some subtitle",
        data={},
        m4a=StubFile("audio.m4a"),
        mp3=StubFile("audio.mp3"),
        oga=StubFile("audio.oga"),
        opus=StubFile("audio.opus"),
    )
    audio_data = serialize_audio(audio)
    assert serialize_audio(deserialize_audio(audio_data)) == audio_data

    class Podlove:
        name = "podlove.json"

    class TranscriptFile:
        name = "transcript.vtt"

    class TranscriptStub:
        pk = 1
        audio_id = 1
        podlove = Podlove()
        vtt = TranscriptFile()
        dote = TranscriptFile()
        collection_id = None

    transcript_data = serialize_transcript(TranscriptStub())
    assert serialize_transcript(deserialize_transcript(transcript_data)) == transcript_data

    video = Video(
        id=1,
        collection=None,
        title="Some video",
        original=StubFile("video.mp4"),
        poster=StubFile("poster.jpg"),
        poster_seconds=1,
    )
    video_data = serialize_video(video)
    assert serialize_video(deserialize_video(video_data)) == video_data

    image = Image(id=1, title="Some image", collection=None, file=StubFile("image.jpg"), width=100, height=200)
    image_data = serialize_image(image)
    assert serialize_image(deserialize_image(image_data)) == image_data


@pytest.mark.django_db
def test_serialize_deserialize_roundtrip_for_post_types(post, episode):
    post_data = serialize_post(post)
    assert serialize_post(deserialize_post(post_data)) == post_data

    episode_data = serialize_episode(episode)
    assert serialize_episode(deserialize_episode(episode_data)) == episode_data


@pytest.mark.django_db
def test_create_from_cachable_data_use_audio_player_false():
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
    repository = BlogIndexContext.create_from_cachable_data(data=data)
    assert repository.use_audio_player is False


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
