"""
This file contains tests for the post data cache. Make sure
all queries happen in one place and there are no additional
queries when rendering posts.
"""

import pytest
from django.contrib.sites import models as sites_models
from django.contrib.sites.models import Site as DjangoSite
from django.db import connection, reset_queries
from wagtail import hooks
from wagtail.rich_text.feature_registry import FeatureRegistry

import cast.models.repository as repository_module
from cast.feeds import LatestEntriesFeed
from cast.models import (
    Blog,
)
from cast.wagtail_hooks import PageLinkHandlerWithCache, register_page_link
from tests.factories import PostFactory
from tests.repository.helpers import (
    blog_index_repository,
    feed_repository,
    post_detail_repository,
    queryset_data,
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


def test_page_link_handler_override_does_not_depend_on_hook_registration_order(monkeypatch):
    """
    Wagtail searches for hooks lazily. When ``cast.wagtail_hooks`` is imported
    first, its hook is registered before Wagtail's core rich text features, which
    must not restore Wagtail's default page link handler.
    """
    hook_name = "register_rich_text_features"
    hooks.get_hooks(hook_name)  # make sure Wagtail has searched for hooks
    registered = hooks._hooks[hook_name]
    cast_first = [entry for entry in registered if entry[0] is register_page_link] + [
        entry for entry in registered if entry[0] is not register_page_link
    ]
    monkeypatch.setitem(hooks._hooks, hook_name, cast_first)

    assert FeatureRegistry().get_link_types()["page"] is PageLinkHandlerWithCache


@pytest.mark.django_db
def test_internal_page_link_is_not_cached():
    """
    Make sure the right page is returned from the page link handler, especially
    if it's not in the cache.
    """
    # Use a high ID to avoid collisions with styleguide pages created in tests.
    tag = PageLinkHandlerWithCache.expand_db_attributes({"id": 99999})  # get page with non-existing id
    assert tag == "<a>"


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
        queryset_data=queryset_data(
            page_url_by_id={post.id: page_url},  # this will cache the page url
            absolute_page_url_by_id={post.id: f"http://testserver{page_url}"},
        ),
    )
    request = rf.get("/blog-index/")
    request.htmx = False
    reset_queries()
    # When we render the blog index page
    # with connection.execute_wrapper(blocker):
    response = blog.serve(request, repository=repository).render()
    html = response.content.decode("utf-8")
    # Then the internal link should be rendered relative, even though an absolute url is cached too
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
    # Then the internal link should be rendered with an absolute url for feed readers
    html = response.content.decode("utf-8")
    assert f'&lt;a href="http://testserver{page_url}"&gt;just an internal link&lt;/a&gt;' in html
    # And the database should not be hit
    assert len(connection.queries) == 0


# Test render post detail, blog index and blog feed with data from database


def test_cached_page_link_is_absolute_only_inside_absolute_urls_block():
    PageLinkHandlerWithCache.clear_cache()
    PageLinkHandlerWithCache.cache_url(1, "/a/?x=1&y=2", "https://example.com/a/?x=1&y=2")
    PageLinkHandlerWithCache.cache_url(2, "/b/")  # no absolute url known

    assert PageLinkHandlerWithCache.expand_db_attributes({"id": 1}) == '<a href="/a/?x=1&amp;y=2">'
    with PageLinkHandlerWithCache.absolute_urls():
        assert PageLinkHandlerWithCache.expand_db_attributes({"id": 1}) == (
            '<a href="https://example.com/a/?x=1&amp;y=2">'
        )
    assert PageLinkHandlerWithCache.expand_db_attributes({"id": 1}) == '<a href="/a/?x=1&amp;y=2">'


@pytest.mark.django_db
def test_uncached_page_link_falls_back_to_full_url_inside_absolute_urls_block(blog):
    post = PostFactory(owner=blog.owner, parent=blog, title="linked", slug="linked")
    PageLinkHandlerWithCache.clear_cache()

    relative = PageLinkHandlerWithCache.expand_db_attributes({"id": post.id})
    with PageLinkHandlerWithCache.absolute_urls():
        absolute, missing = PageLinkHandlerWithCache.expand_db_attributes_many([{"id": post.id}, {"id": 99999}])

    assert relative == f'<a href="{post.url}">'
    assert absolute == f'<a href="{post.full_url}">'
    assert post.full_url.startswith("http")
    assert missing == "<a>"


@pytest.mark.django_db
def test_clear_cached_page_urls_clears_absolute_urls():
    from cast.models.repository.snapshot import cache_page_url, clear_cached_page_urls

    cache_page_url(99999, "/a/", "https://example.com/a/")
    clear_cached_page_urls()

    assert 99999 not in PageLinkHandlerWithCache.cache
    assert 99999 not in PageLinkHandlerWithCache.absolute_cache


@pytest.mark.django_db
@pytest.mark.parametrize("count", [1, 20])
def test_mixed_link_misses_are_cached_without_refetching_hits(blog, count, django_assert_num_queries, mocker):
    from django.core.cache import cache
    from django.utils.html import escape

    warm = PostFactory(owner=blog.owner, parent=blog, title="Warm", slug="warm")
    cold = [PostFactory(owner=blog.owner, parent=blog, title=f"Cold {i}", slug=f"cold-{i}") for i in range(count)]
    attrs = [{"id": warm.pk}] + [{"id": post.pk} for post in cold] + [{"id": 99999999}, {"id": cold[0].pk}]
    cache.clear()
    PageLinkHandlerWithCache.clear_cache()
    PageLinkHandlerWithCache.cache_url(warm.pk, "/cached/?x=1&y=2", "https://example.com/cached/?x=1&y=2")
    lookup = mocker.spy(PageLinkHandlerWithCache, "get_many")
    relative = PageLinkHandlerWithCache.expand_db_attributes_many(attrs)
    assert lookup.call_args.args[0] == attrs[1:]
    assert relative == ['<a href="/cached/?x=1&amp;y=2">'] + [f'<a href="{escape(post.url)}">' for post in cold] + [
        "<a>",
        f'<a href="{escape(cold[0].url)}">',
    ]
    with django_assert_num_queries(0):
        for _ in range(5):
            assert PageLinkHandlerWithCache.expand_db_attributes_many(attrs) == relative
        with PageLinkHandlerWithCache.absolute_urls():
            absolute = PageLinkHandlerWithCache.expand_db_attributes_many(attrs)
            assert absolute[0] == '<a href="https://example.com/cached/?x=1&amp;y=2">'
            assert absolute[-2] == "<a>"
    assert absolute[1] == f'<a href="{escape(cold[0].full_url)}">'


@pytest.mark.django_db
def test_missed_link_cache_stays_context_local(blog, django_assert_num_queries, mocker):
    from contextvars import Context

    post = PostFactory(owner=blog.owner, parent=blog, title="Context", slug="context")
    attrs = [{"id": post.pk}, {"id": 99999999}]
    one, two = Context(), Context()
    lookup = mocker.spy(PageLinkHandlerWithCache, "get_many")
    expected = one.run(PageLinkHandlerWithCache.expand_db_attributes_many, attrs)
    assert two.run(PageLinkHandlerWithCache.expand_db_attributes_many, attrs) == expected
    assert lookup.call_count == 2
    with django_assert_num_queries(0):
        assert one.run(PageLinkHandlerWithCache.expand_db_attributes_many, attrs) == expected
        assert two.run(PageLinkHandlerWithCache.expand_db_attributes_many, attrs) == expected


@pytest.mark.django_db
def test_missed_links_keep_language_and_absolute_url_semantics(blog, settings, django_assert_num_queries):
    from django.utils import translation
    from django.utils.html import escape
    from wagtail.models import Locale

    settings.WAGTAIL_I18N_ENABLED = True
    settings.LANGUAGES = [("en-us", "English"), ("de", "German")]
    settings.WAGTAIL_CONTENT_LANGUAGES = settings.LANGUAGES
    post = PostFactory(owner=blog.owner, parent=blog, title="Original", slug="original")
    german, _ = Locale.objects.get_or_create(language_code="de")
    translated = post.copy_for_translation(german, copy_parents=True)
    translated.slug = "uebersetzt"
    translated.live = True
    translated.save()
    attrs = [{"id": post.pk}, {"id": 99999999}]
    PageLinkHandlerWithCache.clear_cache()
    with translation.override("en-us"):
        english = PageLinkHandlerWithCache.expand_db_attributes_many(attrs)
        assert english[0] == f'<a href="{escape(post.url)}">'
    with translation.override("de"):
        localized = PageLinkHandlerWithCache.expand_db_attributes_many(attrs)
        assert localized[0] == f'<a href="{escape(translated.url)}">'
        assert localized != english
        with django_assert_num_queries(0):
            assert PageLinkHandlerWithCache.expand_db_attributes_many(attrs) == localized
            with PageLinkHandlerWithCache.absolute_urls():
                absolute = PageLinkHandlerWithCache.expand_db_attributes_many(attrs)
        assert absolute == [f'<a href="{escape(translated.full_url)}">', "<a>"]


@pytest.mark.django_db
def test_link_misses_do_not_survive_wsgi_requests(blog, client, settings, django_assert_num_queries):
    from types import ModuleType

    from django.http import HttpResponse
    from django.urls import include, path
    from django.utils.html import escape

    post = PostFactory(owner=blog.owner, parent=blog, title="Request scoped", slug="before")
    target = post.pk

    def render(request):
        attrs = [{"id": target}]
        result = PageLinkHandlerWithCache.expand_db_attributes_many(attrs)
        with django_assert_num_queries(0):
            assert PageLinkHandlerWithCache.expand_db_attributes_many(attrs) == result
        return HttpResponse(result[0])

    urls = ModuleType("link_cache_request_urls")
    urls.urlpatterns = [path("render/", render), path("", include("tests.urls"))]
    settings.ROOT_URLCONF = urls
    first_url = post.url
    assert first_url is not None
    assert client.get("/render/").content.decode() == f'<a href="{escape(first_url)}">'
    assert len(PageLinkHandlerWithCache.cache) == 0
    post.slug = "after"
    post.save()
    assert post.url != first_url
    assert client.get("/render/").content.decode() == f'<a href="{escape(post.url)}">'
    post.delete()
    assert client.get("/render/").content.decode() == "<a>"


@pytest.mark.django_db(transaction=True)
def test_request_signals_clear_positive_and_negative_link_entries():
    from django.core.signals import request_finished, request_started

    for signal in (request_started, request_finished):
        PageLinkHandlerWithCache.cache_url(123, "/stale/", "https://example.com/stale/")
        PageLinkHandlerWithCache.cache[456] = None
        PageLinkHandlerWithCache.absolute_cache[456] = None
        signal.send(sender=object)
        assert len(PageLinkHandlerWithCache.cache) == 0
        assert len(PageLinkHandlerWithCache.absolute_cache) == 0
