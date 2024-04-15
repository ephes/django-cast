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
from django.db import connection, reset_queries
from django.urls import reverse
from wagtail.images.models import Image, Rendition
from wagtail.models import Site

from cast.devdata import (
    create_blog,
    create_post,
    create_python_body,
    generate_blog_with_media,
)
from cast.feeds import LatestEntriesFeed
from cast.models import Audio, Blog, Post, Video
from cast.models.repository import (
    BlogIndexRepository,
    PostDetailRepository,
    PostRepositoryForFeed,
    QuerysetData,
    get_facet_choices,
    serialize_renditions,
)


def show_queries(queries):
    for num, query in enumerate(queries, 1):
        print(f"{num} ----------------------------------")
        formatted_sql = sqlparse.format(query["sql"], reindent=True, keyword_case="upper")
        print(formatted_sql)


def blocker(*args):
    raise Exception("No database access allowed here.")


@pytest.fixture(autouse=True)
def debug_settings(settings):
    settings.DEBUG = True


@pytest.mark.django_db
def test_post_data_repr(rf, blog, site):
    request = rf.get("/")
    post_data = PostRepositoryForFeed.create_from_post_queryset(
        request=request, blog=blog, site=site, post_queryset=Post.objects.none(), template_base_dir="bootstrap4"
    )
    assert repr(post_data) == "PostData(renditions_for_posts=0, template_base_dir=bootstrap4)"


@pytest.mark.django_db
def test_queryset_data_patch_page_link_handler_page_not_cached():
    page_link_handler = QuerysetData.patch_page_link_handler({})
    root = page_link_handler.get_instance({"id": 1})
    assert root.id == 1


def test_render_empty_post_without_hitting_the_database(rf):
    """
    Interesting - did not expect that calling Post() would hit the database.
    Providing a content_type did help.
    """
    reset_queries()
    post = Post(content_type=ContentType("cast", "post"))
    root_nav_links = [("/home/", "Home"), ("/about/", "About")]
    page_url = "/foo-bar-baz/"
    absolute_page_url = "http://testserver/foo-bar-baz/"
    queryset_data = QuerysetData(
        post_by_id={},
        images={},
        renditions_for_posts={},
        has_audio_by_id={post.pk: False},
        videos={},
        audios={},
        audios_by_post_id={},
        videos_by_post_id={},
        images_by_post_id={},
        post_queryset=[post],
        owner_username_by_id={post.pk: "owner"},
    )
    repository = PostRepositoryForFeed(
        site=object(),
        blog=None,
        root_nav_links=root_nav_links,
        page_url_by_id={post.pk: page_url},
        absolute_page_url_by_id={post.pk: absolute_page_url},
        blog_url="/blog/",
        queryset_data=queryset_data,
    )
    request = rf.get(page_url)
    post.serve(request, repository=repository).render()
    show_queries(connection.queries)
    assert len(connection.queries) == 0


@pytest.fixture
def linked_posts():
    blog = create_blog()
    target = create_post(blog=blog, num=1)
    source_body = [
        {
            "type": "overview",
            "value": [
                {
                    "type": "paragraph",
                    "value": f'<a id="{target.pk}" linktype="page">just an internal link</a>',
                }
            ],
        },
    ]
    source = create_post(body=json.dumps(source_body), blog=blog, num=2)
    site = Site.objects.first()
    root_nav_links = [(p.get_url(), p.title) for p in site.root_page.get_children().live()]
    queryset_data = QuerysetData(
        post_by_id={target.pk: target.specific},
        images={},
        videos={},
        audios={},
        audios_by_post_id={},
        videos_by_post_id={},
        images_by_post_id={},
        renditions_for_posts={},
        has_audio_by_id={source.pk: False, target.pk: False},
        post_queryset=list[source],
        owner_username_by_id={source.pk: source.owner.username, target.pk: target.owner.username},
    )
    repository = PostRepositoryForFeed(
        site=site,
        blog=blog,
        root_nav_links=root_nav_links,
        page_url_by_id={source.pk: source.get_url(), target.pk: target.get_url()},
        absolute_page_url_by_id={source.pk: source.full_url, target.pk: target.full_url},
        blog_url=blog.get_url(),
        queryset_data=queryset_data,
    )

    class LinkedPosts(NamedTuple):
        source: Post
        target: Post
        repository: PostRepositoryForFeed

    linked_posts = LinkedPosts(source=source, target=target, repository=repository)
    return linked_posts


@pytest.mark.django_db
def test_internal_page_link_is_cached(rf, linked_posts):
    # Given two posts in a blog, one of which (source) links to the other (target)
    page_path = linked_posts.source.get_url_parts(None)[-1]
    request = rf.get(page_path)
    reset_queries()
    # When we render the source post
    # with connection.execute_wrapper(blocker):
    response = linked_posts.source.serve(request, repository=linked_posts.repository).render()
    html = response.content.decode("utf-8")
    # Then the internal link should be rendered
    assert '<a href="/test-blog/test-post-1/">just an internal link</a>' in html
    # And the database should not be hit
    assert len(connection.queries) == 0


def get_media_post(rf, blog):
    post = blog.unfiltered_published_posts.first()
    _ = post.serve(rf.get("/")).render()  # force renditions to be created
    post_queryset = blog.unfiltered_published_posts
    repository = PostRepositoryForFeed.create_from_post_queryset(
        request=rf.get("/"), blog=blog, post_queryset=post_queryset, template_base_dir="bootstrap4"
    )

    class MediaPost(NamedTuple):
        post: Post
        blog: Blog
        repository: PostRepositoryForFeed

    return MediaPost(post=post, blog=blog, repository=repository)


@pytest.fixture
def gallery_post(rf):
    QuerysetData.unset_queryset_data_for_blocks()
    blog = generate_blog_with_media(number_of_posts=1, media_numbers={"galleries": 1, "images_in_galleries": 3})
    yield get_media_post(rf, blog)
    QuerysetData.unset_queryset_data_for_blocks()  # omitting this line will cause a test failure elsewhere


@pytest.mark.django_db
def test_render_gallery_post_without_hitting_the_database(rf, gallery_post):
    # Given a post with a gallery
    request = rf.get(gallery_post.repository.page_url_by_id[gallery_post.post.pk])
    reset_queries()
    # When we render the post
    # with connection.execute_wrapper(blocker):
    # response = gallery_post.post.serve(request, post_data=gallery_post.post_data).render()
    response = gallery_post.post.serve(request, repository=gallery_post.repository).render()
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
def test_render_media_post_without_hitting_the_database(rf, media_post):
    # Given a post with a gallery, an image, a video and an audio
    request = rf.get(media_post.repository.page_url_by_id[media_post.post.pk])
    # make sure renditions are created
    media_post.post.serve(request, repository=media_post.repository).render()
    reset_queries()
    # When we render the post
    # with connection.execute_wrapper(blocker):
    # response = media_post.post.serve(request).render()  # to check that the post_data is needed
    response = media_post.post.serve(request, repository=media_post.repository).render()
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
def test_render_feed_without_hitting_the_database(rf, media_post):
    # Set up the cache
    media_post.repository.queryset_data.set_queryset_data_for_blocks()
    # Given a post with media and a feed
    feed_url = reverse("cast:latest_entries_feed", kwargs={"slug": media_post.blog.slug})
    # When we render the feed
    request = rf.get(feed_url)
    view = LatestEntriesFeed(repository=media_post.repository)
    # first call is just to populate SITE_CACHE
    view(request, slug=media_post.blog.slug)
    reset_queries()
    # now count the queries
    # with connection.execute_wrapper(blocker):
    response = view(request, slug=media_post.blog.slug)
    # Then the media should be rendered
    html = response.content.decode("utf-8")
    assert media_post.post.title in html
    # And the database should not be hit
    show_queries(connection.queries)
    assert len(connection.queries) == 0


def get_paginated_repository(rf, blog):
    post = blog.unfiltered_published_posts.first()
    _ = post.serve(rf.get("/")).render()  # force renditions to be created
    repository = BlogIndexRepository.create_from_blog_index_request(request=rf.get("/"), blog=blog)

    class PaginatedRepository(NamedTuple):
        post: Post
        blog: Blog
        repository: BlogIndexRepository

    return PaginatedRepository(post=post, blog=blog, repository=repository)


@pytest.fixture(scope="function")
def paginated_repo(rf, settings):
    QuerysetData.unset_queryset_data_for_blocks()
    settings.DEFAULT_FILE_STORAGE = "django.core.files.storage.FileSystemStorage"
    blog = generate_blog_with_media(number_of_posts=1)
    paginated_repo = get_paginated_repository(rf, blog)
    teardown_paths = [Path(paginated_repo.post.videos.first().original.path)]
    yield paginated_repo
    # teardown - remove the files created during the test
    QuerysetData.unset_queryset_data_for_blocks()  # omitting this line will cause a test failure elsewhere
    for path in teardown_paths:
        if path.exists():
            path.unlink()


@pytest.mark.django_db
def test_render_blog_index_without_hitting_the_database(rf, paginated_repo):
    # Given a post with media in a blog
    blog = paginated_repo.blog
    # When we render the blog index
    request = rf.get(blog.get_url())
    request.htmx = False
    # call this once without blocker to populate SITE_CACHE
    blog.serve(request, repository=paginated_repo.repository).render()
    reset_queries()
    # with connection.execute_wrapper(blocker):
    response = blog.serve(request, repository=paginated_repo.repository).render()
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
    # with connection.execute_wrapper(blocker):
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
    repository = BlogIndexRepository.create_from_blog(request=request, blog=post_with_audio.blog)
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
    repository.link_to_blocks()
    body = create_python_body()
    body[0]["value"].append({"type": "audio", "value": 1})
    body[0]["value"].append({"type": "video", "value": 1})
    body[0]["value"].append({"type": "image", "value": 1})
    gallery_with_layout = {"layout": "default", "gallery": [1]}
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
