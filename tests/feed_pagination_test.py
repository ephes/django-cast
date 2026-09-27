"""Configuration, checks and owner resolution for future paged feed endpoints."""

import re
from collections import UserDict
from types import MappingProxyType

import pytest
from django.core.checks import Tags
from django.core.checks.registry import registry
from django.core.exceptions import DisallowedHost, ImproperlyConfigured
from django.db import OperationalError
from django.http import Http404
from wagtail.models import Page, PageViewRestriction, Site

from cast import appsettings
from cast.checks import check_feed_pagination_settings, check_feed_pagination_targets
from cast.feed_pagination import (
    DEFAULT_PAGE_SIZE,
    FeedOwnerError,
    FeedPaginationRecord,
    feed_pagination_records,
    normalize_hostname,
    owner_is_public_live,
    request_host_and_port,
    require_public_live_owner,
    resolve_feed_owner,
    resolve_request_owner,
    validate_feed_pagination,
)
from tests.factories import BlogFactory, HomePageFactory, PodcastFactory, PostFactory
from tests.multisite_helpers import create_site_root


def entry(**overrides):
    return {"hostname": "example.com", "port": 443, "blog_path": "/blog/", **overrides}


def record(**overrides):
    return FeedPaginationRecord(**{"hostname": "localhost", "port": 80, "blog_path": "/news/", **overrides})


def errors_for(value):
    records, errors = validate_feed_pagination(value)
    assert records == ()
    return errors


# Pure configuration parsing — no database access


def test_setting_defaults_to_empty_list(settings):
    if hasattr(settings, "CAST_FEED_PAGINATION"):
        del settings.CAST_FEED_PAGINATION

    assert appsettings.CAST_FEED_PAGINATION == []
    assert feed_pagination_records() == ()
    assert check_feed_pagination_settings() == []


def test_valid_entries_are_normalized():
    value = [
        entry(hostname="Example.COM.", page_size=500),
        entry(hostname="[0:0::1]", port=8000, blog_path="/"),
        entry(port=80, blog_path="/a/b/", page_size=1),
    ]

    records, errors = validate_feed_pagination(value)

    assert errors == []
    assert records == (
        FeedPaginationRecord("example.com", 443, "/blog/", 500),
        FeedPaginationRecord("[::1]", 8000, "/", DEFAULT_PAGE_SIZE),
        FeedPaginationRecord("example.com", 80, "/a/b/", 1),
    )
    assert [r.slug_segment for r in records] == ["blog", None, "b"]


@pytest.mark.parametrize("value", [None, {}, "example.com", entry(), (), (entry(),)])
def test_setting_must_be_a_list(value):
    assert errors_for(value) == ["CAST_FEED_PAGINATION must be a list of dicts"]


@pytest.mark.parametrize(
    "raw",
    [("example.com", 443, "/"), MappingProxyType(entry()), UserDict(entry())],
    ids=["tuple", "proxy", "userdict"],
)
def test_entries_must_be_dicts(raw):
    assert errors_for([raw]) == ["CAST_FEED_PAGINATION[0] must be a dict"]


NON_LIST_OF_DICTS = pytest.mark.parametrize(
    "value, message",
    [
        ((), "CAST_FEED_PAGINATION must be a list of dicts"),
        ((entry(),), "CAST_FEED_PAGINATION must be a list of dicts"),
        ([MappingProxyType(entry())], "CAST_FEED_PAGINATION[0] must be a dict"),
        ([UserDict(entry())], "CAST_FEED_PAGINATION[0] must be a dict"),
    ],
    ids=["empty-tuple", "tuple", "proxy", "userdict"],
)


@NON_LIST_OF_DICTS
def test_records_reject_tuples_and_non_dict_mappings(settings, value, message):
    settings.CAST_FEED_PAGINATION = value

    with pytest.raises(ImproperlyConfigured) as excinfo:
        feed_pagination_records()
    assert str(excinfo.value) == message


@NON_LIST_OF_DICTS
def test_pure_check_rejects_tuples_and_non_dict_mappings(settings, value, message):
    settings.CAST_FEED_PAGINATION = value

    errors = check_feed_pagination_settings()

    assert [(error.id, error.msg) for error in errors] == [("cast.E011", message)]


@NON_LIST_OF_DICTS
def test_target_check_skips_tuples_and_non_dict_mappings(settings, value, message, mocker):
    settings.CAST_FEED_PAGINATION = value
    resolve = mocker.patch("cast.checks.resolve_feed_owner")

    assert check_feed_pagination_targets(databases=["default"]) == []
    resolve.assert_not_called()


@NON_LIST_OF_DICTS
def test_request_resolution_rejects_tuples_and_non_dict_mappings(rf, settings, value, message, mocker):
    settings.CAST_FEED_PAGINATION = value
    host = mocker.patch("cast.feed_pagination.request_host_and_port")

    with pytest.raises(ImproperlyConfigured, match=re.escape(message)):
        resolve_request_owner(local_request(rf), slug="test_blog")
    host.assert_not_called()


def test_unknown_and_missing_fields_are_rejected():
    assert errors_for([{"hostname": "example.com", "path": "/", "cursor": "x"}]) == [
        "CAST_FEED_PAGINATION[0] has unknown fields: 'cursor', 'path'",
        "CAST_FEED_PAGINATION[0] is missing required fields: blog_path, port",
    ]


@pytest.mark.parametrize(
    "hostname",
    [
        None,
        "",
        "https://example.com",
        "example.com:443",
        "example.com:",
        "example.com/blog",
        "user@example.com",
        "-bad.example.com",
        "bad-.example.com",
        "a..example.com",
        ".example.com",
        "exa_mple.com",
        "ex ample.com",
        "bücher.example",
        "[1:::2]",
        "[::1]:443",
        ("a" * 63 + ".") * 4 + "com",
    ],
)
def test_hostname_must_be_bare_host(hostname):
    assert errors_for([entry(hostname=hostname)]) == [
        "CAST_FEED_PAGINATION[0] hostname must be a bare hostname without scheme, port or path"
    ]


def test_normalize_hostname():
    assert normalize_hostname("WWW.Example.com.") == "www.example.com"
    assert normalize_hostname("127.0.0.1") == "127.0.0.1"
    assert normalize_hostname("[::FFFF:1.2.3.4]") == "[::ffff:1.2.3.4]"
    assert normalize_hostname("[2001:DB8:0:0::1]") == "[2001:db8::1]"
    assert normalize_hostname("a" * 63 + ".com") == "a" * 63 + ".com"
    assert normalize_hostname("a" * 64 + ".com") is None


@pytest.mark.parametrize("port", [True, False, 0, 65536, "443", 443.0, None])
def test_port_must_be_exact_integer(port):
    assert errors_for([entry(port=port)]) == ["CAST_FEED_PAGINATION[0] port must be an integer from 1 to 65535"]


@pytest.mark.parametrize("port", [1, 65535])
def test_port_bounds_are_inclusive(port):
    assert validate_feed_pagination([entry(port=port)])[1] == []


@pytest.mark.parametrize(
    ("blog_path", "message"),
    [
        (None, "blog_path must be a string"),
        (b"/blog/", "blog_path must be a string"),
        ("", "blog_path must start and end with '/'"),
        ("blog/", "blog_path must start and end with '/'"),
        ("/blog", "blog_path must start and end with '/'"),
        ("https://example.com/blog/", "blog_path must start and end with '/'"),
        ("/blog/?page=2/", "must not contain a query"),
        ("/blog/#x/", "must not contain a query"),
        ("/bl%6Fg/", "must not contain a query"),
        ("/a\\b/", "must not contain a query"),
        ("/a b/", "must not contain a query"),
        ("/a\tb/", "must not contain a query"),
        ("/a\x00b/", "must not contain a query"),
        ("//", "must not contain empty or dot segments"),
        ("/a//b/", "must not contain empty or dot segments"),
        ("/./", "must not contain empty or dot segments"),
        ("/a/../", "must not contain empty or dot segments"),
        ("/blog/feed/paged/rss.xml", "blog_path must start and end with '/'"),
    ],
)
def test_blog_path_must_be_canonical_page_path(blog_path, message):
    (error,) = errors_for([entry(blog_path=blog_path)])
    assert error.startswith("CAST_FEED_PAGINATION[0] ")
    assert message in error


@pytest.mark.parametrize("page_size", [True, False, 0, 501, "100", 100.0, None])
def test_page_size_must_be_exact_integer(page_size):
    assert errors_for([entry(page_size=page_size)]) == [
        "CAST_FEED_PAGINATION[0] page_size must be an integer from 1 to 500"
    ]


def test_all_errors_are_reported_per_entry():
    errors = errors_for([entry(), {"hostname": "x/y", "port": True, "blog_path": "x", "page_size": 0, "z": 1}])

    assert len(errors) == 5
    assert all(error.startswith("CAST_FEED_PAGINATION[1] ") for error in errors)


def test_duplicate_targets_are_rejected_after_normalization():
    assert errors_for([entry(), entry(hostname="EXAMPLE.com.", page_size=5)]) == [
        "CAST_FEED_PAGINATION configures example.com:443/blog/ more than once"
    ]


def test_duplicate_slugs_on_one_host_and_port_are_rejected():
    assert errors_for([entry(blog_path="/a/news/"), entry(blog_path="/b/news/")]) == [
        "CAST_FEED_PAGINATION configures more than one blog with slug 'news' on example.com:443"
    ]


def test_same_slug_on_different_hosts_or_ports_is_allowed():
    value = [entry(blog_path="/news/"), entry(port=80, blog_path="/news/"), entry(hostname="b.example")]

    assert len(validate_feed_pagination(value)[0]) == 3


def test_records_raise_improperly_configured_for_malformed_setting(settings):
    settings.CAST_FEED_PAGINATION = [entry(port=True), "x"]

    with pytest.raises(ImproperlyConfigured, match=r"\[0\] port .*; CAST_FEED_PAGINATION\[1\] must be a dict"):
        feed_pagination_records()


def test_use_tz_is_required_only_when_configured(settings):
    settings.USE_TZ = False
    settings.CAST_FEED_PAGINATION = []
    assert feed_pagination_records() == ()
    assert check_feed_pagination_settings() == []

    settings.CAST_FEED_PAGINATION = [entry()]
    with pytest.raises(ImproperlyConfigured, match="USE_TZ=True"):
        feed_pagination_records()
    assert [error.id for error in check_feed_pagination_settings()] == ["cast.E012"]


def test_records_are_returned_for_valid_setting(settings):
    settings.CAST_FEED_PAGINATION = [entry()]

    assert feed_pagination_records() == (FeedPaginationRecord("example.com", 443, "/blog/"),)


# System checks — no database access unless explicitly requested


def test_pure_check_reports_each_structural_error(settings):
    settings.USE_TZ = False
    settings.CAST_FEED_PAGINATION = [entry(port=0), entry(page_size=True)]

    errors = check_feed_pagination_settings()

    assert [error.id for error in errors] == ["cast.E011", "cast.E011"]
    assert "port must be an integer" in errors[0].msg
    assert "page_size must be an integer" in errors[1].msg


def test_pure_check_accepts_valid_setting(settings):
    settings.CAST_FEED_PAGINATION = [entry()]

    assert check_feed_pagination_settings() == []


def test_setting_is_not_part_of_generic_type_check(settings):
    from cast.checks import check_cast_setting_types

    settings.CAST_FEED_PAGINATION = "not a list"

    assert check_cast_setting_types() == []
    assert [error.id for error in check_feed_pagination_settings()] == ["cast.E011"]


def test_target_check_is_deployment_only_and_database_tagged():
    assert check_feed_pagination_targets in registry.get_checks(include_deployment_checks=True)
    assert check_feed_pagination_targets not in registry.get_checks(include_deployment_checks=False)
    # Only the database tag: ``check --tag cast`` never selects it, even with --deploy.
    assert check_feed_pagination_targets.tags == (Tags.database,)


def test_cast_checks_do_not_resolve_targets_or_touch_the_database(settings, mocker):
    settings.CAST_FEED_PAGINATION = [entry()]
    resolve = mocker.patch("cast.checks.resolve_feed_owner")

    # No django_db mark: any query here fails the test. ``migrate`` passes its
    # alias but never includes deployment checks.
    registry.run_checks(tags=["cast"], databases=["default"])
    registry.run_checks(tags=["cast"], include_deployment_checks=True, databases=["default"])

    resolve.assert_not_called()


@pytest.mark.django_db
def test_deploy_check_without_database_option_skips_target_resolution(settings, mocker):
    settings.CAST_FEED_PAGINATION = [entry()]
    resolve = mocker.patch("cast.checks.resolve_feed_owner")

    # Equivalent to ``check --deploy`` without ``--database``.
    registry.run_checks(include_deployment_checks=True, databases=None)

    resolve.assert_not_called()


@pytest.mark.parametrize("databases", [None, [], ["other"]])
def test_target_check_requires_the_page_database_alias(settings, databases, mocker):
    settings.CAST_FEED_PAGINATION = [entry()]
    resolve = mocker.patch("cast.checks.resolve_feed_owner")

    assert check_feed_pagination_targets(databases=databases) == []
    resolve.assert_not_called()


@pytest.mark.parametrize("value", [[], [entry(port=0)]])
def test_target_check_skips_empty_or_malformed_setting(settings, value, mocker):
    settings.CAST_FEED_PAGINATION = value
    resolve = mocker.patch("cast.checks.resolve_feed_owner")

    assert check_feed_pagination_targets(databases=["default"]) == []
    resolve.assert_not_called()


def test_target_check_reports_missing_tables(settings, mocker):
    settings.CAST_FEED_PAGINATION = [entry()]
    mocker.patch("cast.checks.resolve_feed_owner", side_effect=OperationalError("no such table"))

    (error,) = check_feed_pagination_targets(databases=["default"])

    assert error.id == "cast.E014"
    assert "migrate" in error.hint


@pytest.mark.django_db
def test_target_check_reports_unresolvable_entries(settings, blog):
    settings.CAST_FEED_PAGINATION = [
        entry(hostname="localhost", port=80, blog_path=f"/{blog.slug}/"),
        entry(hostname="localhost", port=80, blog_path="/missing/"),
        entry(hostname="unknown.example", port=80, blog_path="/"),
    ]

    errors = check_feed_pagination_targets(databases=["default"])

    assert [error.id for error in errors] == ["cast.E013", "cast.E013"]
    assert "localhost:80/missing/: no unique page" in errors[0].msg
    assert "unknown.example:80/: no unique Wagtail Site" in errors[1].msg


@pytest.mark.django_db
def test_target_check_accepts_resolvable_entries(settings, blog, podcast):
    settings.CAST_FEED_PAGINATION = [
        entry(hostname="localhost", port=80, blog_path=f"/{blog.slug}/"),
        entry(hostname="localhost", port=80, blog_path=f"/{podcast.slug}/"),
    ]

    assert check_feed_pagination_targets(databases=["default"]) == []


@pytest.mark.django_db
def test_check_command_runs_target_check_only_with_deploy_and_database(settings, blog):
    from django.core.management import call_command
    from django.core.management.base import SystemCheckError

    settings.CAST_FEED_PAGINATION = [entry(hostname="localhost", port=80, blog_path="/missing/")]
    settings.MIDDLEWARE = ["cast.middleware.PagedFeedCacheMiddleware", *settings.MIDDLEWARE]

    call_command("check", "--database", "default")
    call_command("check", "--deploy", "--tag", "cast")
    with pytest.raises(SystemCheckError, match="cast.E013"):
        call_command("check", "--deploy", "--database", "default")


# Exact owner resolution


@pytest.fixture()
def news_site(user, site):
    other_site, home = create_site_root(owner=user, hostname="news.example", slug="news-home", title="News")
    return other_site, home


@pytest.mark.django_db
def test_resolves_nested_blog_and_podcast(blog, podcast):
    blog_owner = resolve_feed_owner(record(blog_path=f"/{blog.slug}/"))
    podcast_owner = resolve_feed_owner(record(blog_path=f"/{podcast.slug}/"))

    assert blog_owner.site.hostname == "localhost"
    assert blog_owner.blog == blog and not blog_owner.is_podcast
    assert podcast_owner.blog.specific_class.__name__ == "Podcast" and podcast_owner.is_podcast
    assert type(podcast_owner.blog).__name__ == "Podcast"


@pytest.mark.django_db
def test_resolves_blog_that_is_the_site_root(user, site):
    root = Page.get_first_root_node()
    root_blog = BlogFactory(owner=user, title="Root blog", slug="root-blog", parent=root)
    root_site = Site.objects.create(hostname="root.example", port=443, root_page=root_blog)

    owner = resolve_feed_owner(record(hostname="root.example", port=443, blog_path="/"))

    assert owner.site == root_site and owner.blog == root_blog
    assert owner.record.slug_segment is None


@pytest.mark.django_db
def test_resolves_deeply_nested_blog(user, news_site):
    news, home = news_site
    section = HomePageFactory(owner=user, title="Section", slug="section", parent=home)
    nested = BlogFactory(owner=user, title="Deep", slug="deep", parent=section)

    owner = resolve_feed_owner(record(hostname="news.example", blog_path="/section/deep/"))

    assert owner.site == news and owner.blog == nested


@pytest.mark.django_db
def test_requires_exact_site_without_default_fallback(blog):
    # Wagtail would route unknown hosts and ports to the default site; resolution must not.
    with pytest.raises(FeedOwnerError, match="no unique Wagtail Site"):
        resolve_feed_owner(record(hostname="alias.example", blog_path=f"/{blog.slug}/"))
    with pytest.raises(FeedOwnerError, match="no unique Wagtail Site"):
        resolve_feed_owner(record(port=8080, blog_path=f"/{blog.slug}/"))


@pytest.mark.django_db
@pytest.mark.parametrize("path", ["/missing/", "/test_blog/missing/"])
def test_requires_page_at_exact_path(blog, path):
    with pytest.raises(FeedOwnerError, match="no unique page"):
        resolve_feed_owner(record(blog_path=path))


@pytest.mark.django_db
def test_requires_page_under_the_configured_site_root(user, news_site):
    _, home = news_site
    BlogFactory(owner=user, title="News", slug="news", parent=home)
    create_site_root(owner=user, hostname="other.example", slug="other-home", title="Other")

    with pytest.raises(FeedOwnerError, match="no unique page"):
        resolve_feed_owner(record(hostname="other.example", blog_path="/news/"))


@pytest.mark.django_db
def test_requires_blog_or_podcast_page(user, blog):
    PostFactory(owner=user, parent=blog, title="Post", slug="a-post", body=[])
    HomePageFactory(owner=user, title="Home", slug="plain-home", parent=Page.get_first_root_node())

    for path in ("/test_blog/a-post/", "/plain-home/"):
        with pytest.raises(FeedOwnerError, match="not a Blog or Podcast"):
            resolve_feed_owner(record(blog_path=path))


@pytest.mark.django_db
def test_rejects_same_site_duplicate_slugs_including_drafts(user, news_site):
    _, home = news_site
    BlogFactory(owner=user, title="News", slug="news", parent=home)
    section = HomePageFactory(owner=user, title="Section", slug="section", parent=home)
    PodcastFactory(owner=user, title="News pod", slug="news", parent=section, live=False)

    for path in ("/news/", "/section/news/"):
        with pytest.raises(FeedOwnerError, match="another Blog on this Site uses slug 'news'"):
            resolve_feed_owner(record(hostname="news.example", blog_path=path))


@pytest.mark.django_db
def test_same_slug_on_two_sites_resolves_independently(user, news_site):
    news, news_home = news_site
    other, other_home = create_site_root(owner=user, hostname="other.example", slug="other-home", title="Other")
    news_blog = BlogFactory(owner=user, title="News", slug="shared", parent=news_home)
    other_blog = PodcastFactory(owner=user, title="Other", slug="shared-pod", parent=other_home)
    other_blog.slug = "shared"
    other_blog.save()

    assert resolve_feed_owner(record(hostname="news.example", blog_path="/shared/")).blog == news_blog
    assert resolve_feed_owner(record(hostname="other.example", blog_path="/shared/")).blog.pk == other_blog.pk


# Fresh public/live access


@pytest.mark.django_db
def test_owner_access_is_checked_freshly(blog):
    owner = resolve_feed_owner(record(blog_path=f"/{blog.slug}/"))
    assert owner_is_public_live(owner)
    assert require_public_live_owner(owner) is owner

    blog.unpublish()

    assert not owner_is_public_live(owner)
    with pytest.raises(Http404):
        require_public_live_owner(owner)


@pytest.mark.django_db
@pytest.mark.parametrize("restrict_parent", [False, True])
def test_owner_access_rejects_direct_and_inherited_restrictions(user, news_site, restrict_parent):
    _, home = news_site
    news = BlogFactory(owner=user, title="News", slug="news", parent=home)
    owner = resolve_feed_owner(record(hostname="news.example", blog_path="/news/"))

    PageViewRestriction.objects.create(
        page=home if restrict_parent else news, restriction_type=PageViewRestriction.PASSWORD, password="x"
    )

    assert not owner_is_public_live(owner)


# Request validation


@pytest.mark.parametrize(
    ("host", "secure", "expected"),
    [
        ("Example.COM.", False, ("example.com", 80)),
        ("example.com", True, ("example.com", 443)),
        ("example.com:8443", False, ("example.com", 8443)),
        ("[0:0::1]:8000", False, ("[::1]", 8000)),
    ],
)
def test_request_host_and_port(rf, settings, host, secure, expected):
    settings.ALLOWED_HOSTS = ["example.com", "[::1]", "[0:0::1]"]

    assert request_host_and_port(rf.get("/", HTTP_HOST=host, secure=secure)) == expected


def test_request_host_must_pass_allowed_hosts(rf):
    with pytest.raises(DisallowedHost):
        request_host_and_port(rf.get("/", HTTP_HOST="evil.example"))


@pytest.mark.parametrize("host", ["a..example.com", "-bad.example.com", "example.com:0", "example.com:65536"])
def test_request_host_must_be_supported(rf, settings, host):
    settings.ALLOWED_HOSTS = ["*"]

    with pytest.raises(Http404):
        request_host_and_port(rf.get("/", HTTP_HOST=host))


def test_request_ignores_untrusted_forwarding_headers(rf):
    request = rf.get(
        "/",
        HTTP_HOST="example.com",
        HTTP_X_FORWARDED_HOST="localhost",
        HTTP_X_FORWARDED_PROTO="https",
        HTTP_X_FORWARDED_PORT="8443",
        SERVER_PORT="8000",
    )

    assert request_host_and_port(request) == ("example.com", 80)


def test_request_uses_only_explicitly_trusted_proxy_headers(rf, settings):
    settings.USE_X_FORWARDED_HOST = True
    settings.USE_X_FORWARDED_PORT = True
    settings.SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    request = rf.get(
        "/",
        HTTP_HOST="internal",
        HTTP_X_FORWARDED_HOST="Example.com",
        HTTP_X_FORWARDED_PROTO="https",
        HTTP_X_FORWARDED_PORT="8443",
        SERVER_PORT="8000",
    )

    # An omitted port follows the trusted scheme, not SERVER_PORT or X-Forwarded-Port.
    assert request_host_and_port(request) == ("example.com", 443)


@pytest.fixture()
def paged(settings):
    def configure(*entries):
        settings.CAST_FEED_PAGINATION = [entry(hostname="localhost", port=80, **item) for item in entries]

    return configure


def local_request(rf, **extra):
    return rf.get("/", HTTP_HOST="localhost", **extra)


def test_request_resolution_is_disabled_by_default(rf, settings, mocker):
    settings.CAST_FEED_PAGINATION = []
    host = mocker.patch("cast.feed_pagination.request_host_and_port")

    with pytest.raises(Http404):
        resolve_request_owner(local_request(rf), slug="test_blog")
    host.assert_not_called()


def test_request_resolution_raises_for_malformed_configuration(rf, settings):
    settings.CAST_FEED_PAGINATION = [entry(port="80")]

    with pytest.raises(ImproperlyConfigured):
        resolve_request_owner(local_request(rf), slug="test_blog")


def test_request_resolution_rejects_unknown_kind(rf):
    with pytest.raises(ValueError):
        resolve_request_owner(local_request(rf), slug="test_blog", kind="video")


@pytest.mark.parametrize(("kind", "audio_format"), [("blog", "mp3"), ("podcast", None), ("podcast", "wav")])
def test_request_resolution_validates_route_format(rf, paged, kind, audio_format):
    paged({"blog_path": "/test_blog/"})

    with pytest.raises(Http404):
        resolve_request_owner(local_request(rf), slug="test_blog", kind=kind, audio_format=audio_format)


@pytest.mark.django_db
def test_request_resolves_blog_feed_owner(rf, paged, blog):
    paged({"blog_path": "/test_blog/", "page_size": 7})

    owner = resolve_request_owner(local_request(rf), slug="test_blog")

    assert owner.blog == blog
    assert owner.record.page_size == 7


@pytest.mark.django_db
def test_podcast_record_enables_blog_and_podcast_routes(rf, paged, podcast):
    paged({"blog_path": "/test_podcast/"})

    assert resolve_request_owner(local_request(rf), slug="test_podcast").is_podcast
    owner = resolve_request_owner(local_request(rf), slug="test_podcast", kind="podcast", audio_format="m4a")
    assert owner.blog.pk == podcast.pk


@pytest.mark.django_db
def test_podcast_route_requires_podcast(rf, paged, blog):
    paged({"blog_path": "/test_blog/"})

    with pytest.raises(Http404):
        resolve_request_owner(local_request(rf), slug="test_blog", kind="podcast", audio_format="mp3")


@pytest.mark.django_db
def test_request_requires_configured_slug(rf, paged, blog, podcast):
    paged({"blog_path": "/test_blog/"})

    with pytest.raises(Http404):
        resolve_request_owner(local_request(rf), slug="test_podcast")


@pytest.mark.django_db
def test_request_rejects_unconfigured_alias_host_and_port(rf, paged, settings, blog):
    paged({"blog_path": "/test_blog/"})
    settings.ALLOWED_HOSTS = ["localhost", "alias.example"]

    # Wagtail's default-site fallback would serve these, but paged feeds are exact.
    for request in (
        rf.get("/", HTTP_HOST="alias.example"),
        rf.get("/", HTTP_HOST="localhost", secure=True),
        rf.get("/", HTTP_HOST="localhost:8000"),
    ):
        with pytest.raises(Http404):
            resolve_request_owner(request, slug="test_blog")


@pytest.mark.django_db
def test_request_resolves_root_blog_by_its_slug(rf, settings, user, site):
    root_blog = BlogFactory(owner=user, title="Root blog", slug="root-blog", parent=Page.get_first_root_node())
    Site.objects.create(hostname="root.example", port=443, root_page=root_blog)
    settings.ALLOWED_HOSTS = ["root.example"]
    settings.CAST_FEED_PAGINATION = [entry(hostname="root.example", port=443, blog_path="/")]
    request = rf.get("/", HTTP_HOST="root.example", secure=True)

    assert resolve_request_owner(request, slug="root-blog").blog == root_blog
    with pytest.raises(Http404):
        resolve_request_owner(request, slug="other")


@pytest.mark.django_db
def test_request_skips_unresolvable_records(rf, paged, blog):
    # The Site root is not a Blog, so that candidate cannot claim the slug.
    paged({"blog_path": "/missing/"}, {"blog_path": "/"}, {"blog_path": "/test_blog/"})

    assert resolve_request_owner(local_request(rf), slug="test_blog").blog == blog


@pytest.mark.django_db
def test_request_rejects_ambiguous_slug(rf, paged, user, blog):
    section = HomePageFactory(owner=user, title="Section", slug="section", parent=Page.get_first_root_node())
    BlogFactory(owner=user, title="Other", slug="test_blog", parent=section)
    paged({"blog_path": "/test_blog/"})

    with pytest.raises(Http404):
        resolve_request_owner(local_request(rf), slug="test_blog")


@pytest.mark.django_db
@pytest.mark.parametrize("found", ["none", "other"])
def test_request_requires_wagtail_site_agreement(rf, paged, blog, news_site, mocker, found):
    paged({"blog_path": "/test_blog/"})
    mocker.patch("cast.feed_pagination.Site.find_for_request", return_value=None if found == "none" else news_site[0])

    with pytest.raises(Http404):
        resolve_request_owner(local_request(rf), slug="test_blog")


@pytest.mark.django_db
def test_request_rechecks_public_live_owner(rf, paged, blog):
    paged({"blog_path": "/test_blog/"})
    PageViewRestriction.objects.create(page=blog, restriction_type=PageViewRestriction.PASSWORD, password="x")

    with pytest.raises(Http404):
        resolve_request_owner(local_request(rf), slug="test_blog")

    PageViewRestriction.objects.all().delete()
    blog.unpublish()
    with pytest.raises(Http404):
        resolve_request_owner(local_request(rf), slug="test_blog")
