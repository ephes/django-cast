"""Public paged feed routes: response cache, HTTP validators and the final middleware hook."""

import gzip

import django.test.client as test_client_module
import pytest
from django.core.cache import cache
from django.core.checks import Error
from django.core.exceptions import ImproperlyConfigured
from django.middleware.cache import CacheMiddleware, FetchFromCacheMiddleware, UpdateCacheMiddleware
from django.middleware.gzip import GZipMiddleware
from django.test import RequestFactory
from django.utils import timezone as django_timezone, translation
from wagtail.models import PageViewRestriction

from cast import appsettings, checks, paged_feeds
from cast.middleware import MIDDLEWARE_PATH, PagedFeedCacheMiddleware, paged_feed_middleware_errors
from cast.paged_feeds import (
    CACHE_NAMESPACE,
    CachedPagedFeed,
    admit_paged_feed_request,
    paged_feed_cache_key,
    paged_feed_etag,
)
from tests.paged_feed_middleware import LITERAL_COOKIE
from tests.paged_feeds_test import (
    FEEDS,
    HOST,
    config,
    items,
    legacy_url,
    links,
    make_entries,
    paged_url,
    root_for,
)

PUBLIC = "public, max-age=300"
PROVOKING = "tests.paged_feed_middleware.ProvokingMiddleware"
FULL_STACK = [
    MIDDLEWARE_PATH,
    "django.middleware.gzip.GZipMiddleware",
    "django.middleware.http.ConditionalGetMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "wagtail.contrib.redirects.middleware.RedirectMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
    PROVOKING,
]
# Both relative orders of GZipMiddleware and ConditionalGetMiddleware.
ORDERS = {
    "gzip-outer": FULL_STACK,
    "conditional-outer": [FULL_STACK[0], FULL_STACK[2], FULL_STACK[1], *FULL_STACK[3:]],
}
UNVERIFIABLE_CURSOR = "a:" + "A" * 43

pytestmark = pytest.mark.urls("tests.paged_feed_urls")


@pytest.fixture()
def paged(settings):
    settings.CAST_FEED_PAGINATION = [config("/test_blog/"), config("/test_podcast/")]
    settings.MIDDLEWARE = [MIDDLEWARE_PATH, *settings.MIDDLEWARE]
    cache.clear()
    yield settings
    cache.clear()


@pytest.fixture()
def full_stack(paged):
    """Real session/CSRF/locale/conditional/gzip middleware; restores the language LocaleMiddleware leaves active."""
    paged.MIDDLEWARE = FULL_STACK
    with translation.override(translation.get_language()):
        yield paged
    django_timezone.deactivate()


@pytest.fixture()
def raw_client(client, monkeypatch):
    """Test client without its own HEAD body removal: responses are exactly what the handler returned."""
    monkeypatch.setattr(test_client_module, "conditional_content_removal", lambda request, response: response)
    return client


@pytest.fixture()
def fixed_gzip(monkeypatch):
    """Disable GZipMiddleware's random BREACH padding, so independent requests compress identically."""
    monkeypatch.setattr(GZipMiddleware, "max_random_bytes", 0, raising=False)


@pytest.fixture(params=["default", "django"])
def repository_mode(request, monkeypatch):
    monkeypatch.setattr(appsettings, "CAST_REPOSITORY", request.param)
    return request.param


class Clock:
    def __init__(self, monkeypatch):
        self.now = 1_000_000.0
        monkeypatch.setattr(paged_feeds, "_now", lambda: self.now)


@pytest.fixture()
def clock(monkeypatch):
    return Clock(monkeypatch)


@pytest.fixture()
def spies(monkeypatch):
    """Count selections and cache writes without changing behavior."""
    calls = {"select": 0, "set": [], "touch": 0}
    select = paged_feeds.select_paged_feed
    cache_set = cache.set

    def counting_select(target):
        calls["select"] += 1
        return select(target)

    def recording_set(key, value, timeout=None, **kwargs):
        if key.startswith(CACHE_NAMESPACE):
            calls["set"].append((key, timeout))
        return cache_set(key, value, timeout, **kwargs)

    def counting_touch(*args, **kwargs):
        calls["touch"] += 1

    monkeypatch.setattr(paged_feeds, "select_paged_feed", counting_select)
    monkeypatch.setattr(cache, "set", recording_set)
    monkeypatch.setattr(cache, "touch", counting_touch)
    return calls


def stored_keys():
    # LocMemCache internals, test-only: strip the ":<version>:" prefix of stored keys.
    return [key.split(":", 2)[2] for key in cache._cache if CACHE_NAMESPACE in key]


def target_for(url, **extra):
    request = RequestFactory().get(url, **{**HOST, **extra})
    return admit_paged_feed_request(request, slug="test_blog", kind="blog", representation="rss")


def assert_uncached_error(response):
    assert response["Cache-Control"] == "no-store"
    for header in ("ETag", "Last-Modified", "Age", "Expires"):
        assert not response.has_header(header)


def assert_private(response):
    assert response["Cache-Control"] == "private, no-store"
    for header in ("ETag", "Last-Modified", "Age"):
        assert not response.has_header(header)


def vary_tokens(response):
    return {token.strip() for token in response.get("Vary", "").split(",") if token.strip()}


# All four routes, both repository modes


@pytest.mark.parametrize("kind,representation", list(FEEDS))
def test_routes_cache_serialized_representations(
    client, paged, repository_mode, blog, podcast, spies, clock, kind, representation
):
    root = root_for(kind, blog, podcast)
    make_entries(root, kind, 3)
    url = paged_url(kind, representation, root)
    cold = client.get(url, **HOST)
    assert cold.status_code == 200
    assert cold["Cache-Control"] == PUBLIC and cold["Age"] == "0"
    assert cold["ETag"] == paged_feed_etag(cold.content, f"http://localhost{url}")
    assert not cold.has_header("Last-Modified")
    assert spies["select"] == 1 and [timeout for _, timeout in spies["set"]] == [300]
    clock.now += 42
    warm = client.get(url, **HOST)
    head = client.head(url, **HOST)
    assert warm.content == cold.content and head.content == b""
    assert warm["ETag"] == head["ETag"] == cold["ETag"]
    assert warm["Age"] == head["Age"] == "42"
    assert head["Content-Type"] == warm["Content-Type"] == cold["Content-Type"]
    # Warm hits neither select, hydrate nor renew the TTL.
    assert spies["select"] == 1 and len(spies["set"]) == 1 and spies["touch"] == 0
    next_url = links(cold.content)["next"][0][0]
    assert client.get(next_url, **HOST).status_code == 200
    assert len(stored_keys()) == 2


def test_cold_head_builds_and_stores_the_full_representation(client, paged, blog):
    make_entries(blog, "blog", 1)
    url = paged_url("blog", "rss", blog)
    head = client.head(url, **HOST)
    assert head.status_code == 200 and head.content == b""
    (key,) = stored_keys()
    entry = CachedPagedFeed.from_cache_value(cache.get(key))
    assert entry.content.startswith(b"<?xml") and entry.etag == head["ETag"]


# Cache key partitioning and validators


def test_cache_key_partitions_every_representation_input(paged, blog, podcast, monkeypatch):
    make_entries(blog, "blog", 1)
    head = paged_url("blog", "rss", blog)
    base = paged_feed_cache_key(target_for(head))
    assert base.startswith(f"{CACHE_NAMESPACE}:") and len(base) == len(CACHE_NAMESPACE) + 65
    assert paged_feed_cache_key(target_for(head)) == base
    variants = {paged_feed_cache_key(target_for(f"{head}?cursor=abc"))}
    with monkeypatch.context() as patch:
        patch.setattr(
            appsettings, "CAST_REPOSITORY", "django" if appsettings.CAST_REPOSITORY != "django" else "default"
        )
        variants.add(paged_feed_cache_key(target_for(head)))
    for name, value in (("LANGUAGE_CODE", "de"), ("TIME_ZONE", "Asia/Tokyo"), ("SECRET_KEY", "rotated-" * 8)):
        original = getattr(paged, name)
        setattr(paged, name, value)
        variants.add(paged_feed_cache_key(target_for(head)))
        setattr(paged, name, original)
    paged.CAST_FEED_PAGINATION = [config("/test_blog/", page_size=3)]
    variants.add(paged_feed_cache_key(target_for(head)))
    assert base not in variants and len(variants) == 6


def test_cache_key_and_etag_never_contain_the_signing_key(paged, blog):
    make_entries(blog, "blog", 1)
    key = paged_feed_cache_key(target_for(paged_url("blog", "rss", blog)))
    assert paged.SECRET_KEY not in key


def test_etag_includes_url_and_fixed_locale_settings(settings):
    base = paged_feed_etag(b"<rss/>", "http://localhost/a")
    assert base.startswith('W/"') and base.endswith('"')
    assert paged_feed_etag(b"<rss />", "http://localhost/a") != base
    assert paged_feed_etag(b"<rss/>", "http://localhost/b") != base
    settings.LANGUAGE_CODE = "de"
    assert paged_feed_etag(b"<rss/>", "http://localhost/a") != base
    settings.LANGUAGE_CODE = "en-us"
    settings.TIME_ZONE = "Asia/Tokyo"
    assert paged_feed_etag(b"<rss/>", "http://localhost/a") != base


@pytest.mark.parametrize(
    "value",
    [
        None,
        ("other.v0", b"x", "t", "e", 1.0),
        (CACHE_NAMESPACE, "x", "t", "e", 1.0),
        (CACHE_NAMESPACE, b"x", "t", "e", 1),
        (CACHE_NAMESPACE, b"x", "t", "e"),
    ],
)
def test_unrecognized_cache_values_are_misses(value):
    assert CachedPagedFeed.from_cache_value(value) is None


def test_entries_from_the_future_or_older_than_300_seconds_are_regenerated(client, paged, blog, clock, spies):
    make_entries(blog, "blog", 1)
    url = paged_url("blog", "rss", blog)
    client.get(url, **HOST)
    clock.now -= 10
    assert client.get(url, **HOST)["Age"] == "0" and spies["select"] == 2
    clock.now += 310
    assert client.get(url, **HOST)["Age"] == "0" and spies["select"] == 3


# Cursor, root and configuration checks precede cache lookup


def test_signing_key_rotation_and_removal_apply_to_warm_entries(client, paged, blog, spies):
    make_entries(blog, "blog", 3)
    head = "http://localhost" + paged_url("blog", "rss", blog)
    first = client.get(head, **HOST)
    next_url = links(first.content)["next"][0][0]
    assert client.get(next_url, **HOST).status_code == 200
    old_key = paged.SECRET_KEY
    paged.SECRET_KEY = "rotated-signing-key-" * 3
    paged.SECRET_KEY_FALLBACKS = [old_key]
    # The fallback still verifies the old cursor, but rotation partitions the cache.
    rotated_head = client.get(head, **HOST)
    assert spies["select"] == 3
    assert links(rotated_head.content)["next"][0][0] != next_url
    assert client.get(next_url, **HOST).status_code == 200
    assert spies["select"] == 4
    paged.SECRET_KEY_FALLBACKS = []
    removed = client.get(next_url, **HOST)
    assert removed.status_code == 302 and removed["Location"] == head
    assert_uncached_error(removed)
    assert spies["select"] == 4


@pytest.mark.parametrize("change", ["unpublish", "restrict", "unconfigure", "disable"])
def test_fresh_root_and_config_checks_precede_warm_hits(client, paged, blog, change):
    make_entries(blog, "blog", 1)
    url = paged_url("blog", "rss", blog)
    assert client.get(url, **HOST).status_code == 200 and stored_keys()
    if change == "unpublish":
        blog.unpublish()
    elif change == "restrict":
        PageViewRestriction.objects.create(page=blog, restriction_type=PageViewRestriction.LOGIN)
    elif change == "unconfigure":
        paged.CAST_FEED_PAGINATION = [config("/test_podcast/")]
    else:
        paged.CAST_FEED_PAGINATION = []
    response = client.get(url, HTTP_IF_NONE_MATCH="*", **HOST)
    assert response.status_code == 404
    assert_uncached_error(response)


def test_invalid_cursor_is_rejected_before_cache_lookup(client, paged, blog, monkeypatch):
    make_entries(blog, "blog", 1)
    url = paged_url("blog", "rss", blog)
    monkeypatch.setattr(paged_feeds, "_cached_entry", lambda key: pytest.fail("cache consulted"))
    response = client.get(f"{url}?cursor=not-a-cursor", HTTP_IF_NONE_MATCH="*", **HOST)
    assert response.status_code == 400
    assert_uncached_error(response)


def test_methods_other_than_get_and_head_are_uncached_405(client, paged, blog):
    response = client.post(paged_url("blog", "rss", blog), **HOST)
    assert response.status_code == 405 and response["Allow"] == "GET, HEAD"
    assert_uncached_error(response)
    assert not stored_keys()


# Accepted staleness and expiry


def test_child_edits_are_stale_until_expiry_then_change_the_etag(client, paged, blog, clock):
    older = make_entries(blog, "blog", 2)[-1]
    url = paged_url("blog", "rss", blog)
    cold = client.get(url, **HOST)
    older.title = "edited older entry"
    older.save_revision().publish()
    clock.now += 299
    stale = client.get(url, **HOST)
    assert stale.content == cold.content and stale["ETag"] == cold["ETag"] and stale["Age"] == "299"
    clock.now += 1
    fresh = client.get(url, **HOST)
    assert b"edited older entry" in fresh.content and fresh["Age"] == "0"
    assert fresh["ETag"] != cold["ETag"]
    older.delete()
    clock.now += 300
    assert client.get(url, **HOST)["ETag"] != fresh["ETag"]


# Conditional requests


def test_if_none_match_and_if_modified_since(client, paged, blog, clock):
    make_entries(blog, "blog", 1)
    url = paged_url("blog", "rss", blog)
    etag = client.get(url, **HOST)["ETag"]
    clock.now += 7
    for method, inm in ((client.get, etag), (client.head, etag), (client.get, "*"), (client.get, f'"x", {etag}')):
        response = method(url, HTTP_IF_NONE_MATCH=inm, **HOST)
        assert response.status_code == 304 and response.content == b""
        assert response["ETag"] == etag and response["Cache-Control"] == PUBLIC and response["Age"] == "7"
    strong = client.get(url, HTTP_IF_NONE_MATCH=etag.removeprefix("W/"), **HOST)
    assert strong.status_code == 304
    other = client.get(url, HTTP_IF_NONE_MATCH='W/"other"', **HOST)
    assert other.status_code == 200 and other.content
    ims = client.get(url, HTTP_IF_MODIFIED_SINCE="Sun, 01 Jan 2100 00:00:00 GMT", **HOST)
    assert ims.status_code == 200 and ims.content and not ims.has_header("Last-Modified")


def test_cold_304_stores_the_full_200_candidate(client, paged, blog, spies):
    make_entries(blog, "blog", 1)
    url = paged_url("blog", "rss", blog)
    etag = client.get(url, **HOST)["ETag"]
    cache.clear()
    cold = client.get(url, HTTP_IF_NONE_MATCH=etag, **HOST)
    assert cold.status_code == 304 and cold.content == b""
    (key,) = stored_keys()
    assert CachedPagedFeed.from_cache_value(cache.get(key)).content.startswith(b"<?xml")
    hit = client.get(url, **HOST)
    assert hit.status_code == 200 and hit.content.startswith(b"<?xml") and hit["ETag"] == etag
    assert spies["select"] == 2 and len(spies["set"]) == 2


PAST = "Wed, 01 Jan 2025 00:00:00 GMT"
FUTURE = "Fri, 01 Jan 2100 00:00:00 GMT"


@pytest.mark.parametrize("order", ORDERS)
@pytest.mark.parametrize(
    "headers,status",
    [
        # Without Last-Modified a valid If-Unmodified-Since can never pass, whatever the date.
        ({"HTTP_IF_UNMODIFIED_SINCE": PAST}, 412),
        ({"HTTP_IF_UNMODIFIED_SINCE": FUTURE}, 412),
        # An unparseable date is ignored.
        ({"HTTP_IF_UNMODIFIED_SINCE": "not a date"}, 200),
        # If-Modified-Since alone is ignored.
        ({"HTTP_IF_MODIFIED_SINCE": PAST}, 200),
        # If-Match takes precedence: If-Unmodified-Since is not evaluated when it is present.
        ({"HTTP_IF_MATCH": "*", "HTTP_IF_UNMODIFIED_SINCE": PAST}, 200),
        # The weak ETag never passes the strong If-Match comparison, even when it is echoed.
        ({"HTTP_IF_MATCH": "etag", "HTTP_IF_UNMODIFIED_SINCE": FUTURE}, 412),
    ],
)
def test_date_preconditions_through_the_full_middleware_stack(client, full_stack, blog, order, headers, status):
    full_stack.MIDDLEWARE = ORDERS[order]
    make_entries(blog, "blog", 1)
    url = paged_url("blog", "rss", blog)
    etag = client.get(url, **HOST)["ETag"]
    headers = {name: etag if value == "etag" else value for name, value in headers.items()}
    response = client.get(url, **headers, **HOST)
    assert response.status_code == status
    if status == 412:
        assert_uncached_error(response)
    else:
        assert response.content.startswith(b"<?xml") and response["ETag"] == etag
        assert response["Cache-Control"] == PUBLIC and not response.has_header("Last-Modified")
    assert len(stored_keys()) == 1


# Mandatory outermost middleware and the complete middleware boundary


def test_full_stack_compresses_but_caches_uncompressed_bytes(client, full_stack, blog):
    make_entries(blog, "blog", 3)
    url = paged_url("blog", "rss", blog)
    compressed = client.get(url, HTTP_ACCEPT_ENCODING="gzip", **HOST)
    assert compressed.status_code == 200 and compressed["Content-Encoding"] == "gzip"
    assert compressed["Cache-Control"] == PUBLIC and compressed["ETag"].startswith("W/")
    assert vary_tokens(compressed) == {"Accept-Encoding", "Accept-Language"}
    assert not compressed.cookies
    (key,) = stored_keys()
    entry = CachedPagedFeed.from_cache_value(cache.get(key))
    assert gzip.decompress(compressed.content) == entry.content
    plain = client.get(url, **HOST)
    assert plain.content == entry.content and plain["ETag"] == compressed["ETag"]
    not_modified = client.get(url, HTTP_IF_NONE_MATCH=plain["ETag"], HTTP_ACCEPT_ENCODING="gzip", **HOST)
    assert not_modified.status_code == 304 and not_modified.content == b""
    assert vary_tokens(not_modified) == vary_tokens(compressed) and not_modified["Cache-Control"] == PUBLIC
    precondition = client.get(url, HTTP_IF_MATCH='"nope"', **HOST)
    assert precondition.status_code == 412
    assert_uncached_error(precondition)
    assert len(stored_keys()) == 1


@pytest.mark.parametrize("order", ORDERS)
@pytest.mark.parametrize("method", ["get", "head"])
@pytest.mark.parametrize("warm", [False, True])
def test_304_keeps_representation_vary_in_either_middleware_order(
    raw_client, full_stack, blog, spies, clock, order, method, warm
):
    full_stack.MIDDLEWARE = ORDERS[order]
    make_entries(blog, "blog", 3)
    url = paged_url("blog", "rss", blog)
    ok = raw_client.get(url, HTTP_ACCEPT_ENCODING="gzip", **HOST)
    assert ok["Content-Encoding"] == "gzip" and vary_tokens(ok) == {"Accept-Encoding", "Accept-Language"}
    if not warm:
        cache.clear()
    clock.now += 5
    request = getattr(raw_client, method)
    response = request(url, HTTP_IF_NONE_MATCH=ok["ETag"], HTTP_ACCEPT_ENCODING="gzip", **HOST)
    assert response.status_code == 304 and response.content == b""
    assert vary_tokens(response) == vary_tokens(ok)
    assert response["ETag"] == ok["ETag"] and response["Cache-Control"] == PUBLIC
    assert response["Age"] == ("5" if warm else "0")
    assert not response.has_header("Content-Encoding") and not response.cookies
    # A cold 304 stores the full uncompressed 200 entry, never the 304; a warm 304 neither stores nor renews.
    (key,) = stored_keys()
    assert gzip.decompress(ok.content) == CachedPagedFeed.from_cache_value(cache.get(key)).content
    assert spies["select"] == len(spies["set"]) == (1 if warm else 2) and spies["touch"] == 0


@pytest.mark.parametrize("order", ORDERS)
@pytest.mark.parametrize("encoding", ["identity", "gzip"])
def test_head_has_the_get_representation_headers(raw_client, full_stack, blog, clock, fixed_gzip, order, encoding):
    full_stack.MIDDLEWARE = ORDERS[order]
    make_entries(blog, "blog", 3)
    url = paged_url("blog", "rss", blog)
    cold_head = raw_client.head(url, HTTP_ACCEPT_ENCODING=encoding, **HOST)
    get = raw_client.get(url, HTTP_ACCEPT_ENCODING=encoding, **HOST)
    warm_head = raw_client.head(url, HTTP_ACCEPT_ENCODING=encoding, **HOST)
    assert cold_head.status_code == get.status_code == warm_head.status_code == 200
    assert cold_head.content == warm_head.content == b"" and get.content
    assert dict(cold_head.items()) == dict(get.items()) == dict(warm_head.items())
    assert get["Content-Length"] == str(len(get.content)) and get["Cache-Control"] == PUBLIC
    assert vary_tokens(get) == {"Accept-Encoding", "Accept-Language"}
    assert get.get("Content-Encoding") == ("gzip" if encoding == "gzip" else None)
    assert len(stored_keys()) == 1


@pytest.mark.parametrize("case", ["missing", "invalid", "restart", "disabled"])
def test_head_errors_have_the_get_headers_without_a_body(raw_client, full_stack, blog, fixed_gzip, case):
    make_entries(blog, "blog", 1)
    url = paged_url("blog", "rss", blog)
    if case == "missing":
        url = url.replace("test_blog", "missing")
    elif case == "invalid":
        url = f"{url}?cursor=bad"
    elif case == "restart":
        url = f"{url}?cursor={UNVERIFIABLE_CURSOR}"
    else:
        full_stack.CAST_FEED_PAGINATION = []
    get = raw_client.get(url, HTTP_ACCEPT_ENCODING="gzip", HTTP_IF_NONE_MATCH="*", **HOST)
    head = raw_client.head(url, HTTP_ACCEPT_ENCODING="gzip", HTTP_IF_NONE_MATCH="*", **HOST)
    assert get.status_code == head.status_code == {"restart": 302, "invalid": 400}.get(case, 404)
    assert head.content == b"" and dict(head.items()) == dict(get.items())
    assert_uncached_error(head)
    assert not stored_keys()


@pytest.mark.parametrize("guarded", [True, False])
@pytest.mark.parametrize("method", ["get", "head"])
def test_disabled_routes_are_uncached_404_with_or_without_middleware(raw_client, full_stack, blog, guarded, method):
    """Disabled pagination does not require the middleware; conditional middleware cannot turn the 404 into 304."""
    make_entries(blog, "blog", 1)
    full_stack.CAST_FEED_PAGINATION = []
    if not guarded:
        full_stack.MIDDLEWARE = FULL_STACK[1:]
    response = getattr(raw_client, method)(paged_url("blog", "rss", blog), HTTP_IF_NONE_MATCH="*", **HOST)
    assert response.status_code == 404
    assert_uncached_error(response)
    if guarded and method == "head":
        assert response.content == b""
    assert not stored_keys()


def test_full_stack_ignores_caller_language_and_timezone(client, full_stack, blog, user):
    make_entries(blog, "blog", 1)
    url = paged_url("blog", "rss", blog)
    baseline = client.get(url, **HOST)
    cache.clear()
    client.force_login(user)
    client.cookies["django_language"] = "de"
    other = client.get(url, HTTP_ACCEPT_LANGUAGE="fr", HTTP_X_TEST_TIMEZONE="America/New_York", **HOST)
    assert other.content == baseline.content and other["ETag"] == baseline["ETag"]
    assert other["Cache-Control"] == PUBLIC
    assert f"<language>{full_stack.LANGUAGE_CODE}</language>".encode() in other.content


PROVOCATIONS = [
    {"HTTP_X_TEST_SESSION": "1"},
    {"HTTP_X_TEST_CSRF": "1"},
    {"HTTP_X_TEST_VARY": "Cookie"},
    {"HTTP_X_TEST_VARY": "Accept-Encoding, X-Custom"},
    {"HTTP_X_TEST_VARY": "*"},
    {"HTTP_X_TEST_SET_COOKIE": "1"},
]


def assert_cookies_kept(provocation, response):
    """Cookies set by other middleware stay on private responses, including a literal Set-Cookie header."""
    if "HTTP_X_TEST_SET_COOKIE" in provocation:
        assert response["Set-Cookie"] == LITERAL_COOKIE
    elif "HTTP_X_TEST_VARY" not in provocation:
        assert response.cookies


@pytest.mark.parametrize("order", ORDERS)
@pytest.mark.parametrize("provocation", PROVOCATIONS)
def test_unsafe_cold_responses_are_private_and_not_stored(client, full_stack, blog, provocation, order):
    full_stack.MIDDLEWARE = ORDERS[order]
    make_entries(blog, "blog", 1)
    url = paged_url("blog", "rss", blog)
    response = client.get(url, **HOST, **provocation)
    assert response.status_code == 200 and response.content
    assert_private(response)
    assert_cookies_kept(provocation, response)
    assert not stored_keys()
    etag = client.get(url, **HOST)["ETag"]
    cache.clear()
    not_modified = client.get(url, HTTP_IF_NONE_MATCH=etag, **HOST, **provocation)
    assert not_modified.status_code == 304 and not_modified.content == b""
    assert_private(not_modified)
    assert_cookies_kept(provocation, not_modified)
    assert not stored_keys()


@pytest.mark.parametrize("order", ORDERS)
@pytest.mark.parametrize("provocation", PROVOCATIONS)
@pytest.mark.parametrize("conditional", [False, True])
def test_unsafe_warm_hits_are_private_and_evicted(client, full_stack, blog, provocation, conditional, order):
    full_stack.MIDDLEWARE = ORDERS[order]
    make_entries(blog, "blog", 1)
    url = paged_url("blog", "rss", blog)
    etag = client.get(url, **HOST)["ETag"]
    assert stored_keys()
    extra = {"HTTP_IF_NONE_MATCH": etag} if conditional else {}
    response = client.get(url, **HOST, **provocation, **extra)
    assert response.status_code == (304 if conditional else 200)
    assert_private(response)
    assert_cookies_kept(provocation, response)
    assert not stored_keys()


def test_replaced_responses_are_uncached_errors(client, full_stack, blog):
    make_entries(blog, "blog", 1)
    response = client.get(paged_url("blog", "rss", blog), HTTP_X_TEST_REPLACE="1", **HOST)
    assert response.content == b"replaced"
    assert_uncached_error(response)
    assert not stored_keys()


def test_replaced_streaming_head_is_a_bodyless_uncached_error(raw_client, full_stack, blog):
    make_entries(blog, "blog", 1)
    response = raw_client.head(paged_url("blog", "rss", blog), HTTP_X_TEST_REPLACE="stream", **HOST)
    assert response.streaming and b"".join(response.streaming_content) == b""
    assert_uncached_error(response)
    assert not stored_keys()


def test_final_hook_removes_downstream_date_validators(client, full_stack, blog):
    make_entries(blog, "blog", 1)
    response = client.get(paged_url("blog", "rss", blog), HTTP_X_TEST_VALIDATORS="1", **HOST)
    assert response.status_code == 200 and response["Cache-Control"] == PUBLIC and response.has_header("ETag")
    assert not response.has_header("Last-Modified") and not response.has_header("Expires")


def test_isolated_internal_adapter_stays_uncached(rf, paged, blog, podcast):
    """The internal adapter is used only by direct-call tests and never touches the response cache."""
    make_entries(blog, "blog", 1)
    url = paged_url("blog", "rss", blog)
    kwargs = {"slug": blog.slug, "kind": "blog", "representation": "rss"}
    responses = [
        paged_feeds.internal_paged_feed_response(rf.post(url, **HOST), **kwargs),
        paged_feeds.internal_paged_feed_response(rf.get(f"{url}?cursor=bad", **HOST), **kwargs),
        paged_feeds.internal_paged_feed_response(rf.get(f"{url}?cursor={UNVERIFIABLE_CURSOR}", **HOST), **kwargs),
        paged_feeds.internal_paged_feed_response(rf.head(url, **HOST), **kwargs),
    ]
    assert [response.status_code for response in responses] == [405, 400, 302, 200]
    assert all(response["Cache-Control"] == "no-store" for response in responses)
    assert responses[3].content == b"" and not responses[3].has_header("ETag")
    assert not stored_keys()


def test_raised_404_is_no_store_after_conditional_middleware(client, full_stack, blog):
    response = client.get(paged_url("blog", "rss", blog).replace("test_blog", "missing"), **HOST)
    assert response.status_code == 404
    assert_uncached_error(response)


def test_middleware_is_transparent_for_legacy_feeds(client, paged, blog, settings):
    make_entries(blog, "blog", 1)
    url = legacy_url("blog", "rss", blog)
    guarded = client.get(url, **HOST)
    cache.clear()
    settings.MIDDLEWARE = settings.MIDDLEWARE[1:]
    unguarded = client.get(url, **HOST)
    assert guarded.content == unguarded.content
    assert guarded["Cache-Control"] == unguarded["Cache-Control"] != PUBLIC
    assert not guarded.has_header("Age") and guarded.has_header("Last-Modified")
    assert len(items(guarded.content)) == 1


@pytest.mark.parametrize(
    "urlconf,prefix",
    [("tests.paged_feed_urls", "/blogs/"), ("tests.paged_feed_root_urls", "/"), ("tests.paged_feed_i18n_urls", None)],
)
def test_mounts_and_language_prefixes_are_separate_cache_entries(client, full_stack, blog, urlconf, prefix):
    full_stack.ROOT_URLCONF = urlconf
    make_entries(blog, "blog", 1)
    paths = (
        [f"{prefix}test_blog/feed/paged/rss.xml"]
        if prefix
        else [
            "/de/blogs/test_blog/feed/paged/rss.xml",
            "/en/blogs/test_blog/feed/paged/rss.xml",
        ]
    )
    for path in paths:
        response = client.get(path, **HOST)
        assert response.status_code == 200 and response["Cache-Control"] == PUBLIC
        assert links(response.content)["self"][0][0] == f"http://localhost{path}"
        assert client.get(path, HTTP_IF_NONE_MATCH=response["ETag"], **HOST).status_code == 304
    assert len(stored_keys()) == len(paths)


# Runtime fail-closed placement


@pytest.mark.parametrize(
    "middleware",
    [
        lambda current: current[1:],
        lambda current: [*current[1:], MIDDLEWARE_PATH],
        lambda current: [*current, "django.middleware.cache.UpdateCacheMiddleware"],
    ],
)
def test_misplaced_middleware_fails_closed(client, paged, blog, middleware):
    make_entries(blog, "blog", 1)
    paged.MIDDLEWARE = middleware(list(paged.MIDDLEWARE))
    with pytest.raises(ImproperlyConfigured, match="PagedFeedCacheMiddleware"):
        client.get(paged_url("blog", "rss", blog), **HOST)
    assert not stored_keys()


# Pure placement checks (no database access)


class SiteCache(CacheMiddleware):
    pass


class LaterUpdate(UpdateCacheMiddleware):
    pass


class EarlyFetch(FetchFromCacheMiddleware):
    pass


class Guard(PagedFeedCacheMiddleware):
    pass


HERE = __name__


@pytest.mark.parametrize(
    "middleware,expected",
    [
        ([MIDDLEWARE_PATH, "django.middleware.common.CommonMiddleware"], []),
        ([f"{HERE}.Guard", "missing.module.Middleware"], []),
        (["django.middleware.common.CommonMiddleware"], ["cast.E015"]),
        (["django.middleware.common.CommonMiddleware", MIDDLEWARE_PATH], ["cast.E015"]),
        ([MIDDLEWARE_PATH, MIDDLEWARE_PATH], ["cast.E015"]),
        ([MIDDLEWARE_PATH, "django.middleware.cache.UpdateCacheMiddleware"], ["cast.E016"]),
        ([MIDDLEWARE_PATH, "django.middleware.cache.FetchFromCacheMiddleware"], ["cast.E016"]),
        ([MIDDLEWARE_PATH, f"{HERE}.SiteCache"], ["cast.E016"]),
        ([f"{HERE}.EarlyFetch", MIDDLEWARE_PATH, f"{HERE}.LaterUpdate"], ["cast.E015", "cast.E016", "cast.E016"]),
        ([MIDDLEWARE_PATH, "cast.middleware.MIDDLEWARE_PATH"], []),
    ],
)
def test_placement_checks_are_pure(settings, middleware, expected):
    assert [check_id for check_id, _ in paged_feed_middleware_errors(middleware)] == expected
    settings.CAST_FEED_PAGINATION = [config("/test_blog/")]
    settings.MIDDLEWARE = middleware
    errors = checks.check_feed_pagination_middleware()
    assert [error.id for error in errors] == expected
    assert all(isinstance(error, Error) and error.hint for error in errors)


@pytest.mark.parametrize("value", [[], [{"hostname": "localhost"}]])
def test_placement_checks_only_apply_to_valid_configuration(settings, value):
    settings.CAST_FEED_PAGINATION = value
    settings.MIDDLEWARE = ["django.middleware.cache.UpdateCacheMiddleware"]
    assert checks.check_feed_pagination_middleware() == []
