"""Cached feeds must stop listing an entry once a view restriction on it commits.

The built-in feed routes sit behind a five-minute response cache. A committed
``PageViewRestriction`` change rotates the feed cache generation, and each
request reads that generation before rendering. A render that was already in
flight during the change therefore stores its stale response under the old
generation, where no later request looks for it.
"""

from typing import Any

import pytest
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from wagtail.models import PageViewRestriction

from cast import feeds

FEED_ROUTES = {
    "latest_entries_feed": feeds.LatestEntriesFeed,
    "latest_entries_atom_feed": feeds.LatestEntriesAtomFeed,
    "podcast_feed_rss": feeds.RssPodcastFeed,
    "podcast_feed_atom": feeds.AtomPodcastFeed,
}


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture(params=sorted(FEED_ROUTES))
def route(request):
    return request.param


@pytest.fixture
def entry(route, post, episode):
    return episode if route.startswith("podcast_") else post


@pytest.fixture
def feed_url(route, entry):
    kwargs = {"slug": entry.blog.slug}
    if route.startswith("podcast_"):
        kwargs["audio_format"] = "m4a"
    return reverse(f"cast:{route}", kwargs=kwargs)


def _create_restriction(page, kind: str) -> PageViewRestriction:
    if kind == "password":
        return PageViewRestriction.objects.create(
            page=page, restriction_type=PageViewRestriction.PASSWORD, password="sesame"
        )
    return PageViewRestriction.objects.create(page=page, restriction_type=PageViewRestriction.LOGIN)


def restrict(page, kind: str = "login") -> PageViewRestriction:
    # Each test runs inside a transaction; run on-commit callbacks as a real
    # commit would.
    with TestCase.captureOnCommitCallbacks(execute=True):
        return _create_restriction(page, kind)


def lists(response, entry) -> bool:
    assert response.status_code == 200
    return entry.title in response.content.decode()


@pytest.mark.django_db
@pytest.mark.parametrize("kind", ["login", "password"])
def test_warm_feed_cache_drops_entry_once_restriction_commits(client, feed_url, entry, kind):
    assert lists(client.get(feed_url), entry)
    assert lists(client.get(feed_url), entry)  # served from the cache

    restrict(entry, kind)

    assert not lists(client.get(feed_url), entry)


@pytest.mark.django_db
def test_feed_render_in_flight_during_restriction_is_not_served_later(client, feed_url, route, entry, monkeypatch):
    feed_class = FEED_ROUTES[route]
    original_call = feed_class.__call__
    restricted: list[PageViewRestriction] = []

    def render_then_restrict(self: Any, request: Any, *args: Any, **kwargs: Any) -> Any:
        # The public feed is rendered, then the restriction commits before the
        # response cache stores that (now stale) response.
        response = original_call(self, request, *args, **kwargs)
        if not restricted:
            restricted.append(restrict(entry))
        return response

    monkeypatch.setattr(feed_class, "__call__", render_then_restrict)

    assert lists(client.get(feed_url), entry)
    assert restricted

    assert not lists(client.get(feed_url), entry)


@pytest.mark.django_db
def test_generation_is_read_before_the_restricted_root_guard_queries(client, feed_url, route, monkeypatch):
    # Under ATOMIC_REQUESTS with snapshot isolation the guard's query fixes the
    # request's snapshot. A rotation committed after that query must not be the
    # generation the (pre-restriction) render is cached under.
    from cast import site_lookup

    original_guard = site_lookup.get_site_specific_unrestricted_page_or_404
    rotated: list[bool] = []

    def guard_then_rotate(*args: Any, **kwargs: Any) -> Any:
        page = original_guard(*args, **kwargs)
        if not rotated:
            rotated.append(True)
            feeds.rotate_feed_cache_generation()
        return page

    monkeypatch.setattr(site_lookup, "get_site_specific_unrestricted_page_or_404", guard_then_rotate)
    feed_class = FEED_ROUTES[route]
    original_call = feed_class.__call__
    renders: list[bool] = []

    def counting_call(self: Any, request: Any, *args: Any, **kwargs: Any) -> Any:
        renders.append(True)
        return original_call(self, request, *args, **kwargs)

    monkeypatch.setattr(feed_class, "__call__", counting_call)

    client.get(feed_url)
    client.get(feed_url)

    # The first response was stored under the pre-rotation generation, so the
    # second request (reading the rotated one) renders afresh.
    assert rotated
    assert len(renders) == 2


@pytest.mark.django_db
def test_feed_lists_entry_again_once_restriction_removal_commits(client, feed_url, entry):
    restriction = restrict(entry)
    assert not lists(client.get(feed_url), entry)

    with TestCase.captureOnCommitCallbacks(execute=True):
        restriction.delete()

    assert lists(client.get(feed_url), entry)


@pytest.mark.django_db
def test_generation_rotates_only_after_restriction_commits(post):
    generation = feeds.feed_cache_generation()

    with TestCase.captureOnCommitCallbacks(execute=False) as callbacks:
        _create_restriction(post, "login")
        assert feeds.feed_cache_generation() == generation

    assert callbacks
    for callback in callbacks:
        callback()
    assert feeds.feed_cache_generation() != generation


def test_feed_cache_generation_is_created_once_and_reused():
    generation = feeds.feed_cache_generation()

    assert generation
    assert feeds.feed_cache_generation() == generation
    feeds.rotate_feed_cache_generation()
    assert feeds.feed_cache_generation() != generation


def test_feed_cache_generation_falls_back_when_cache_drops_the_key(mocker):
    # A cache that does not keep the key (e.g. it is evicted at once) still
    # yields a usable generation for this request.
    mocker.patch.object(cache, "get", return_value=None)

    assert feeds.feed_cache_generation()


def test_feed_cache_key_prefix_keeps_the_configured_middleware_prefix(settings, mocker):
    settings.CACHE_MIDDLEWARE_KEY_PREFIX = "site-a"
    cache_page = mocker.patch("cast.feeds.cache_page", return_value=lambda view: view)
    view = feeds.restriction_aware_cache_page(60)(lambda request: "response")

    assert view("request") == "response"

    _, kwargs = cache_page.call_args
    assert kwargs["key_prefix"] == f"site-a:cast-feed:{feeds.feed_cache_generation()}"
