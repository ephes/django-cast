"""
This file contains tests for the post data cache. Make sure
all queries happen in one place and there are no additional
queries when rendering posts.
"""

import json
import pickle
from pathlib import Path
from typing import NamedTuple

import pytest
import sqlparse
from django.contrib.contenttypes.models import ContentType
from django.contrib.sites import models as sites_models
from django.contrib.sites.models import Site as DjangoSite
from django.db import connection, reset_queries
from django.urls import reverse
from wagtail.images.models import Image, Rendition

from cast.devdata import create_python_body, generate_blog_with_media
from cast.feeds import LatestEntriesFeed
from cast.filters import PostFilterset
from cast.models import Audio, Blog, Post, Video
from cast.models.repository import (
    BlogIndexRepository,
    FeedRepository,
    PostDetailRepository,
    QuerysetData,
    get_facet_choices,
    serialize_renditions,
)
from cast.wagtail_hooks import PageLinkHandlerWithCache


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
        renditions_for_posts={},
    )
    defaults.update(kwargs)
    return PostDetailRepository(**defaults)


def queryset_data(**kwargs):
    defaults = dict(
        post_queryset=[],
        post_by_id={},
        audios={},
        images={},
        videos={},
        audios_by_post_id={},
        videos_by_post_id={},
        images_by_post_id={},
        owner_username_by_id={},
        has_audio_by_id={},
        renditions_for_posts={},
        page_url_by_id={},
        absolute_page_url_by_id={},
    )
    defaults.update(kwargs)
    return QuerysetData(**defaults)


def blog_index_repository(**kwargs):
    defaults = dict(
        template_base_dir="bootstrap4",
        filterset=PostFilterset(None),
        queryset_data=queryset_data(),
        pagination_context={"object_list": []},
        root_nav_links=[],
        use_audio_player=False,
    )
    defaults.update(kwargs)
    return BlogIndexRepository(**defaults)


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
    return FeedRepository(**defaults)


# Test page link handler with cache


@pytest.mark.django_db
def test_internal_page_link_is_not_cached():
    """
    Make sure the right page is returned from the page link handler, especially
    if it's not in the cache.
    """
    tag = PageLinkHandlerWithCache.expand_db_attributes({"id": 23})  # get page with non-existing id
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
        pagination_context={"object_list": [post]},
        queryset_data=queryset_data(page_url_by_id={post.id: page_url}),  # this will cache the page url
    )
    request = rf.get("/blog-index/")
    request.htmx = False
    reset_queries()
    # When we render the blog index page
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


def get_media_post(rf, blog):
    post = blog.unfiltered_published_posts.first()
    _ = post.serve(rf.get("/")).render()  # force renditions to be created
    post_queryset = blog.unfiltered_published_posts
    repository = FeedRepository.create_from_post_queryset(
        request=rf.get("/"), blog=blog, post_queryset=post_queryset, template_base_dir="bootstrap4"
    )

    class MediaPost(NamedTuple):
        post: Post
        blog: Blog
        repository: FeedRepository

    return MediaPost(post=post, blog=blog, repository=repository)


@pytest.fixture
def post_of_blog(rf, settings):
    settings.DEFAULT_FILE_STORAGE = "django.core.files.storage.FileSystemStorage"
    blog = generate_blog_with_media(number_of_posts=1)
    post = blog.unfiltered_published_posts.first()
    _ = post.serve(rf.get("/")).render()  # force renditions to be created
    teardown_paths = [Path(post.videos.first().original.path)]
    yield post
    # teardown - remove the files created during the test
    for path in teardown_paths:
        if path.exists():
            path.unlink()


@pytest.fixture
def gallery_post(rf):
    blog = generate_blog_with_media(number_of_posts=1, media_numbers={"galleries": 1, "images_in_galleries": 3})
    post = blog.unfiltered_published_posts.first()
    _ = post.serve(rf.get("/")).render()  # force renditions to be created
    yield post


@pytest.mark.django_db
def test_render_gallery_post_without_hitting_the_database(rf, gallery_post):
    # Given a post with a gallery
    post = gallery_post
    request = rf.get(post.get_url())
    repository = PostDetailRepository.create_from_django_models(request=request, post=post)
    reset_queries()
    # When we render the post
    # with connection.execute_wrapper(blocker):
    response = post.serve(request, repository=repository).render()
    # Then the gallery should be rendered
    html = response.content.decode("utf-8")
    assert 'class="cast-gallery-modal"' in html
    # And the database should not be hit
    show_queries(connection.queries)
    assert len(connection.queries) == 0


@pytest.fixture(scope="function")
def media_post(rf, settings):
    QuerysetData.unset_queryset_data_for_blocks()
    settings.DEFAULT_FILE_STORAGE = "django.core.files.storage.FileSystemStorage"
    blog = generate_blog_with_media(number_of_posts=1)
    media_post = get_media_post(rf, blog)
    teardown_paths = [Path(media_post.post.videos.first().original.path)]
    yield media_post
    # teardown - remove the files created during the test
    QuerysetData.unset_queryset_data_for_blocks()  # omitting this line will cause a test failure elsewhere
    for path in teardown_paths:
        if path.exists():
            path.unlink()


@pytest.mark.django_db
def test_render_post_detail_without_hitting_the_database_duplicate(rf, post_of_blog):
    # Given a post with a gallery, an image, a video and an audio
    post = post_of_blog
    request = rf.get(post.get_url())
    # When we render the post
    # with connection.execute_wrapper(blocker):
    repository = PostDetailRepository.create_from_django_models(request=request, post=post)
    reset_queries()
    response = post.serve(request, repository=repository).render()
    # Then the media should be rendered
    html = response.content.decode("utf-8")
    assert 'class="cast-image"' in html
    assert 'class="cast-gallery-modal"' in html
    assert 'class="block-video"' in html
    assert 'class="block-audio"' in html
    # And the database should not be hit
    show_queries(connection.queries)
    assert len(connection.queries) == 0


@pytest.mark.django_db
def test_render_feed_without_hitting_the_database(rf, post_of_blog):
    # Given a post with media and a feed
    post = post_of_blog
    blog = post.blog
    post_queryset = blog.unfiltered_published_posts
    repository = FeedRepository.create_from_post_queryset(
        request=rf.get("/"), blog=blog, post_queryset=post_queryset, template_base_dir="bootstrap4"
    )
    # Given a post with media and a feed
    feed_url = reverse("cast:latest_entries_feed", kwargs={"slug": blog.slug})
    # When we render the feed
    request = rf.get(feed_url)
    view = LatestEntriesFeed(repository=repository)
    # first call is just to populate SITE_CACHE
    view(request, slug=blog.slug)
    reset_queries()
    # now count the queries
    # with connection.execute_wrapper(blocker):
    response = view(request, slug=blog.slug)
    # Then the media should be rendered
    html = response.content.decode("utf-8")
    assert post.title in html
    # And the database should not be hit
    show_queries(connection.queries)
    assert len(connection.queries) == 0


@pytest.mark.django_db
def test_render_blog_index_without_hitting_the_database(rf, post_of_blog):
    # Given a post with media in a blog
    post = post_of_blog
    blog = post.blog
    # When we render the blog index
    request = rf.get(blog.get_url())
    request.htmx = False
    # call this once without blocker to populate SITE_CACHE
    repository = BlogIndexRepository.create_from_blog_index_request(request=rf.get("/"), blog=blog)
    blog.serve(request, repository=repository).render()
    reset_queries()
    # with connection.execute_wrapper(blocker):
    response = blog.serve(request, repository=repository).render()
    # Then the media should be rendered
    html = response.content.decode("utf-8")
    assert 'class="cast-image"' in html
    assert 'class="cast-gallery-modal"' in html
    assert 'class="block-video"' in html
    assert 'class="block-audio"' in html
    # And the database should not be hit
    show_queries(connection.queries)
    assert len(connection.queries) == 0


@pytest.mark.django_db
def test_render_blog_index_with_django_models_repository(rf, post, settings):
    # Given a blog with a post
    settings.DEFAULT_FILE_STORAGE = "django.core.files.storage.FileSystemStorage"
    blog = post.blog
    author_name = post.owner.username.capitalize()
    post_detail_url = post.get_url()
    request = rf.get(blog.get_url())
    request.htmx = False

    # When we render the blog index
    repository = BlogIndexRepository.create_from_django_models(request=request, blog=blog)
    response = blog.serve(request, repository=repository).render()
    # Then post data should be generated on the fly and the media should be rendered
    assert isinstance(response.context_data["repository"], BlogIndexRepository)
    html = response.content.decode("utf-8")
    assert author_name in html
    assert post_detail_url in html
    assert response.context_data["is_paginated"] is False
    # And the database should be hit
    assert len(connection.queries) > 0


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
    _ = post.serve(rf.get("/")).render()  # force renditions to be created

    # Set up the cache
    cachable_data = BlogIndexRepository.data_for_blog_index_cachable(request=request, blog=blog)
    pickled = pickle.dumps(cachable_data)  # make sure it's really cachable by pickling it
    cachable_data = pickle.loads(pickled)
    repository = BlogIndexRepository.create_from_cachable_data(data=cachable_data)

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


def test_serialize_renditions():
    rendition = Rendition(file="foo.jpg", filter_spec="foobarfilter", width=100, height=200)
    renditions = serialize_renditions({1: [rendition]})
    rendition = Rendition(**renditions[1][0])
    assert rendition.file == "foo.jpg"


def test_get_facet_choices():
    class Facet:
        choices = [("foo", "Foo"), ("bar", "Bar")]

    # choices are found
    choices = get_facet_choices({"foobar": Facet()}, "foobar")
    assert choices == Facet.choices

    # no choices found
    choices = get_facet_choices({}, "foobar")
    assert choices == []


@pytest.mark.django_db
def test_create_from_cachable_data_use_audio_player_false():
    data = {
        "template_base_dir": "bootstrap4",
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
    repository = BlogIndexRepository.create_from_cachable_data(data=data)
    assert repository.use_audio_player is False


@pytest.mark.django_db
def test_blog_index_repo_simple_has_audio_true(rf, post_with_audio):
    request = rf.get("/")
    repository = BlogIndexRepository.create_from_django_models(request=request, blog=post_with_audio.blog)
    assert repository.use_audio_player is True


# Just create html pages without hitting the database
# - post detail
# - blog index
# - feed


@pytest.mark.django_db
def test_render_post_detail_with_hitting_the_database(rf):
    """
    This test should just use the default repository and fetch all data from the database.
    """
    blog = generate_blog_with_media(
        number_of_posts=1,
        media_numbers={
            "galleries": 1,
            "images_in_galleries": 3,
            "images": 1,
            "videos": 1,
            "audios": 1,
        },
    )
    post = blog.unfiltered_published_posts.first()
    post_url = post.get_url()
    request = rf.get(post_url)
    reset_queries()
    repository = PostDetailRepository.create_from_django_models(request=request, post=post)
    print("has audio: ", repository.has_audio)
    response = post.serve(request, repository=repository).render()
    html = response.content.decode("utf-8")
    assert "web-player/embed.4.js" in html  # audio player because has_audio is True
    assert post.title in html
    assert repository.page_url in html
    assert repository.owner_username.capitalize() in html
    assert "audio_1" in html
    assert "<video" in html
    assert '<section class="block-image">' in html
    assert '<section class="block-gallery">' in html
    assert len(connection.queries) > 50  # just wow!


def test_render_post_detail_without_hitting_the_database(rf):
    """
    Given a post with media which is not in the database. And a repository
    containing the media needed to render the post detail.

    When we render the post detail, then the media should be rendered and
    the database should not be hit.
    """

    class StubFile:
        def __init__(self, name):
            self.name = name
            self.url = f"/media/{name}"

    repository = PostDetailRepository(
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
        audio_by_id={1: Audio(id=1, title="Some audio", collection=None)},
        video_by_id={1: Video(id=1, title="Some video", collection=None, original=StubFile("foo.mp4"))},
        image_by_id={
            1: Image(id=1, title="Some image", collection=None, file=StubFile("foo.jpg"), width=2000, height=1000)
        },
        renditions_for_posts={
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
        },
    )
    body = create_python_body()
    body[0]["value"].append({"type": "audio", "value": 1})
    body[0]["value"].append({"type": "video", "value": 1})
    body[0]["value"].append({"type": "image", "value": 1})
    gallery_with_layout = {"layout": "default", "gallery": [{"id": 1, "type": "item", "value": 1}]}
    body[0]["value"].append({"id": 1, "type": "gallery", "value": gallery_with_layout})
    serialized_body = json.dumps(body)
    post = Post(id=1, title="Some post", body=serialized_body)
    request = rf.get("/some-post/")
    request.htmx = False
    reset_queries()
    # with connection.execute_wrapper(blocker):
    response = post.serve(request, repository=repository).render()
    # Then the media should be rendered
    html = response.content.decode("utf-8")
    assert "web-player/embed.4.js" in html  # audio player because has_audio is True
    assert post.title in html
    assert repository.page_url in html
    assert repository.owner_username.capitalize() in html
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
    assert len(connection.queries) == 0
