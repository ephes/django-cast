"""
This file contains tests for the post data cache. Make sure
all queries happen in one place and there are no additional
queries when rendering posts.
"""

import json
from pathlib import Path
from typing import NamedTuple

import pytest
import sqlparse
from django.contrib.contenttypes.models import ContentType
from django.db import connection, reset_queries
from django.urls import reverse
from wagtail.models import Site

from cast.cache import PostData
from cast.devdata import create_blog, create_post, generate_blog_with_media
from cast.feeds import LatestEntriesFeed
from cast.models import Blog, Post


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
    post_data = PostData.create_from_post_queryset(
        request=request, blog=blog, site=site, post_queryset=Post.objects.none(), template_base_dir="bootstrap4"
    )
    assert repr(post_data) == "PostData(renditions_for_posts=0, template_base_dir=bootstrap4)"


@pytest.mark.django_db
def test_post_data_patch_page_link_handler_page_not_cached():
    page_link_handler = PostData.patch_page_link_handler({})
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
    post_data = PostData(
        site=object(),
        blog=None,
        post_by_id={},
        images={},
        renditions_for_posts={},
        root_nav_links=root_nav_links,
        has_audio_by_id={post.pk: False},
        page_url_by_id={post.pk: page_url},
        owner_username_by_id={post.pk: "owner"},
        blog_url="/blog/",
        videos={},
        audios={},
        audios_by_post_id={},
        post_queryset=[post],
    )
    request = rf.get(page_url)
    post.serve(request, post_data=post_data).render()
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
    post_data = PostData(
        site=site,
        blog=blog,
        post_by_id={target.pk: target.specific},
        images={},
        renditions_for_posts={},
        root_nav_links=root_nav_links,
        has_audio_by_id={source.pk: False, target.pk: False},
        page_url_by_id={source.pk: source.get_url(), target.pk: target.get_url()},
        owner_username_by_id={source.pk: source.owner.username, target.pk: target.owner.username},
        videos={},
        audios={},
        audios_by_post_id={},
        blog_url=blog.get_url(),
        post_queryset=list[source],
    )

    class LinkedPosts(NamedTuple):
        source: Post
        target: Post
        post_data: PostData

    linked_posts = LinkedPosts(source=source, target=target, post_data=post_data)
    return linked_posts


@pytest.mark.django_db
def test_internal_page_link_is_cached(rf, linked_posts):
    # Given two posts in a blog, one of which (source) links to the other (target)
    page_path = linked_posts.source.get_url_parts(None)[-1]
    request = rf.get(page_path)
    reset_queries()
    # When we render the source post
    # with connection.execute_wrapper(blocker):
    response = linked_posts.source.serve(request, post_data=linked_posts.post_data).render()
    html = response.content.decode("utf-8")
    # Then the internal link should be rendered
    assert '<a href="/test-blog/test-post-1/">just an internal link</a>' in html
    # And the database should not be hit
    assert len(connection.queries) == 0


def get_media_post(rf, blog):
    post = blog.unfiltered_published_posts.first()
    _ = post.serve(rf.get("/")).render()  # force renditions to be created
    post_queryset = blog.unfiltered_published_posts
    post_data = PostData.create_from_post_queryset(
        request=rf.get("/"), blog=blog, post_queryset=post_queryset, template_base_dir="bootstrap4"
    )

    class MediaPost(NamedTuple):
        post: Post
        blog: Blog
        post_data: PostData

    return MediaPost(post=post, blog=blog, post_data=post_data)


@pytest.fixture
def gallery_post(rf):
    blog = generate_blog_with_media(number_of_posts=1, media_numbers={"galleries": 1, "images_in_galleries": 3})
    return get_media_post(rf, blog)


@pytest.mark.django_db
def test_render_gallery_post_without_hitting_the_database(rf, gallery_post):
    # Given a post with a gallery
    request = rf.get(gallery_post.post_data.page_url_by_id[gallery_post.post.pk])
    reset_queries()
    # When we render the post
    # with connection.execute_wrapper(blocker):
    # response = gallery_post.post.serve(request, post_data=gallery_post.post_data).render()
    response = gallery_post.post.serve(request, post_data=gallery_post.post_data).render()
    # Then the gallery should be rendered
    html = response.content.decode("utf-8")
    assert 'class="cast-gallery-modal"' in html
    # And the database should not be hit
    show_queries(connection.queries)
    assert len(connection.queries) == 0


@pytest.fixture
def media_post(rf, settings):
    settings.DEFAULT_FILE_STORAGE = "django.core.files.storage.FileSystemStorage"
    blog = generate_blog_with_media(number_of_posts=1)
    media_post = get_media_post(rf, blog)
    teardown_paths = [Path(media_post.post.videos.first().original.path)]
    yield media_post
    # teardown - remove the files created during the test
    for path in teardown_paths:
        if path.exists():
            path.unlink()


@pytest.mark.django_db
def test_render_media_post_without_hitting_the_database(rf, media_post):
    # Given a post with a gallery, an image, a video and an audio
    request = rf.get(media_post.post_data.page_url_by_id[media_post.post.pk])
    reset_queries()
    # When we render the post
    # with connection.execute_wrapper(blocker):
    # response = media_post.post.serve(request).render()  # to check that the post_data is needed
    response = media_post.post.serve(request, post_data=media_post.post_data).render()
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
    # Given a post with media and a feed
    feed_url = reverse("cast:latest_entries_feed", kwargs={"slug": media_post.blog.slug})
    # When we render the feed
    request = rf.get(feed_url)
    view = LatestEntriesFeed(post_data=media_post.post_data)
    # first call is just to populate SITE_CACHE
    view(request, slug=media_post.blog.slug)
    reset_queries()
    # now count the queries
    response = view(request, slug=media_post.blog.slug)
    # Then the media should be rendered
    html = response.content.decode("utf-8")
    media_post.post.title in html
    # And the database should not be hit
    show_queries(connection.queries)
    assert len(connection.queries) == 0
