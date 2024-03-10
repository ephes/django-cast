"""
This file contains tests for the number of queries. Make sure
that the number of queries stays low for fetching single posts,
lists of posts, feeds etc.
"""
import pytest
import sqlparse
from django.db import connection, reset_queries
from django_htmx.middleware import HtmxDetails

from cast.devdata import generate_blog_with_media
from cast.feeds import LatestEntriesFeed


def show_queries(queries):
    for num, query in enumerate(queries, 1):
        print(f"{num} ----------------------------------")
        formatted_sql = sqlparse.format(query["sql"], reindent=True, keyword_case="upper")
        print(formatted_sql)


# Tests for single posts


@pytest.mark.skip(reason="not able to test this now")
@pytest.mark.django_db
def test_single_post_without_media(settings, rf, post):
    """
    Fetching a single post results in 11 queries:
        - 1 for fetching the blog
        - 1 for fetching the site
        - 3 for template_base_directory (theme) - this does also one insert and one savepoint, wot?
        - 1 for site again
        - 1 for post as page
        - 1 for pages between post and root?
        - 1 for pages with blog slug?
        - 1 for the count of cast post audios
        - ?
    """
    settings.DEBUG = True
    # Given the path of a single post
    page_path = post.get_url_parts(None)[-1]
    request = rf.get(page_path)
    # When the post is served
    reset_queries()
    _ = post.serve(request).render()
    show_queries(connection.queries)
    # Then the number of queries is eleven
    assert len(connection.queries) == 9


# @pytest.mark.django_db
# def test_single_post_with_an_image(settings, rf, post_with_image):
#     """
#     Don't know why this needs 20 queries, but it does.
#     """
#     settings.DEBUG = True
#     # Given the path of a single post
#     page_path = post_with_image.get_url_parts(None)[-1]
#     request = rf.get(page_path)
#     # When the post is served
#     reset_queries()
#     _ = post_with_image.serve(request).render()
#     assert len(connection.queries) == 20


@pytest.mark.skip(reason="not able to test this now")
@pytest.mark.django_db
def test_single_post_with_an_audio(settings, rf, post_with_audio):
    """
    Don't know why this needs 22 queries, but it does.
    """
    settings.DEBUG = True
    # Given the path of a single post
    page_path = post_with_audio.get_url_parts(None)[-1]
    request = rf.get(page_path)
    # When the post is served
    reset_queries()
    _ = post_with_audio.serve(request).render()
    assert len(connection.queries) == 13


# Tests for post lists (blog)


@pytest.mark.django_db
def test_post_list_without_media(settings, rf, blog):
    settings.DEBUG = True
    # Given the path of a post list
    page_path = blog.get_url_parts(None)[-1]
    request = rf.get(page_path)
    request.htmx = HtmxDetails(request)
    # When the post list is served
    reset_queries()
    _ = blog.serve(request).render()
    # show_queries(connection.queries)
    # Then the number of queries is 13
    assert len(connection.queries) == 13


@pytest.fixture
def big_blog():
    return generate_blog_with_media()


# @pytest.mark.django_db
# def test_post_list_with_all_media(settings, rf, big_blog):
#     settings.DEBUG = True
#     # Given the path of a post list
#     page_path = big_blog.get_url_parts(None)[-1]
#     request = rf.get(page_path)
#     request.htmx = HtmxDetails(request)
#     # When the post list is served
#     reset_queries()
#     _ = big_blog.serve(request).render()
#     # show_queries(connection.queries)
#     # Then the number of queries is 13
#     assert len(connection.queries) == 13
#     assert False


# feed number of queries


@pytest.mark.skip(reason="not able to test this now")
@pytest.mark.django_db
def test_latest_entries_feed(settings, rf, big_blog):
    settings.DEBUG = True
    blog_slug = big_blog.slug
    reset_queries()
    request = rf.get(f"/blogs/{blog_slug}/feed/rss.xml")
    response = LatestEntriesFeed()(request, slug=blog_slug)
    content = response.content.decode("utf-8")
    print("content: ", len(content))
    print("queries: ", len(connection.queries))
    # show_queries(connection.queries)
    assert len(connection.queries) > 90
