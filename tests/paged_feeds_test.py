"""Paged feed admission, serializer adapters and uncached route behavior (cache: paged_feed_cache_test)."""

import xml.etree.ElementTree as ET
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone

import pytest
from django.core import signing
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import Http404
from django.urls import reverse, set_script_prefix
from django.utils import timezone as django_timezone, translation
from wagtail.models import PageViewRestriction

from cast import appsettings, paged_feeds
from cast.devdata import create_transcript
from cast.feed_selection import CURSOR_SALT, FeedScope, InvalidFeedCursor, select_feed_page
from cast.feeds import RepositoryMixin
from cast.middleware import MIDDLEWARE_PATH
from cast.models import Audio, ChapterMark, Post
from cast.models.repository import PostQuerySnapshot
from cast.paged_feeds import (
    MAX_QUERY_BYTES,
    PAGED_FEED_CLASSES,
    InvalidPagedFeedQuery,
    PagedFeedNavigation,
    admit_paged_feed_request,
    internal_paged_feed_response,
    parse_paged_feed_query,
    render_paged_feed,
    select_paged_feed,
)
from tests.factories import EpisodeFactory, PostFactory

ATOM = "{http://www.w3.org/2005/Atom}"
DATE = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
PAGE_SIZE = 2
HOST = {"HTTP_HOST": "localhost"}
FEEDS = {
    ("blog", "rss"): ("latest_entries_feed", "paged_entries_feed"),
    ("blog", "atom"): ("latest_entries_atom_feed", "paged_entries_atom_feed"),
    ("podcast", "rss"): ("podcast_feed_rss", "paged_podcast_feed_rss"),
    ("podcast", "atom"): ("podcast_feed_atom", "paged_podcast_feed_atom"),
}


def config(blog_path, **extra):
    return {"hostname": "localhost", "port": 80, "blog_path": blog_path, "page_size": PAGE_SIZE, **extra}


@pytest.fixture()
def paged_config(settings):
    settings.CAST_FEED_PAGINATION = [config("/test_blog/"), config("/test_podcast/")]
    settings.MIDDLEWARE = [MIDDLEWARE_PATH, *settings.MIDDLEWARE]
    cache.clear()
    yield settings
    cache.clear()


@pytest.fixture(params=["default", "django"])
def repository_mode(request, monkeypatch):
    monkeypatch.setattr(appsettings, "CAST_REPOSITORY", request.param)
    return request.param


def make_audio(user, name, formats, repeat=1):
    files = {
        audio_format: SimpleUploadedFile(
            f"{name}.{audio_format}",
            f"{name}-{audio_format}".encode() * repeat * (index + 2),
            content_type=Audio.mime_lookup[audio_format],
        )
        for index, audio_format in enumerate(formats)
    }
    audio = Audio(user=user, title=name, **files)
    audio.save()
    return audio


def make_entries(root, kind, count):
    """Entries with tied and distinct dates; podcast entries have distinct media per episode."""
    entries = []
    for index in range(count):
        date = DATE - timedelta(hours=index // 2)
        common = {"parent": root, "owner": root.owner, "title": f"entry {index}", "slug": f"entry-{index}"}
        if kind == "blog":
            entries.append(PostFactory(body=[], visible_date=date, **common))
            continue
        audio = make_audio(root.owner, f"episode-{index}", ["m4a", "mp3"], repeat=index + 1)
        if index == 0:
            ChapterMark.objects.create(audio=audio, start="00:00:01.500", title="intro")
            create_transcript(audio=audio, vtt="WEBVTT\n\n00:00.000 --> 00:01.000\nhello\n")
        entries.append(EpisodeFactory(body=[], visible_date=date, podcast_audio=audio, **common))
    return entries


def root_for(kind, blog, podcast):
    return podcast if kind == "podcast" else blog


def url_kwargs(kind, root, audio_format="mp3"):
    kwargs = {"slug": root.slug}
    if kind == "podcast":
        kwargs["audio_format"] = audio_format
    return kwargs


def paged_url(kind, representation, root, audio_format="mp3"):
    name = FEEDS[(kind, representation)][1]
    return reverse(f"cast:{name}", kwargs=url_kwargs(kind, root, audio_format))


def legacy_url(kind, representation, root, audio_format="mp3"):
    name = FEEDS[(kind, representation)][0]
    return reverse(f"cast:{name}", kwargs=url_kwargs(kind, root, audio_format))


def feed_root(content):
    root = ET.fromstring(content)
    return root.find("channel") if root.tag == "rss" else root


def items(content):
    channel = feed_root(content)
    return channel.findall("item") + channel.findall(f"{ATOM}entry")


def item_id(item):
    """The UUID identity: RSS guid, the podcast Atom guid extension, or the blog Atom id."""
    return item.findtext("guid") or item.findtext(f"{ATOM}guid") or item.findtext(f"{ATOM}id")


def links(content):
    """Atom namespace links by rel, excluding Atom's rel=alternate."""
    found = {}
    for link in feed_root(content).findall(f"{ATOM}link"):
        if link.get("rel") != "alternate":
            found.setdefault(link.get("rel"), []).append((link.get("href"), link.get("type")))
    return found


def walk(client, url):
    pages = []
    while url is not None:
        response = client.get(url, **HOST)
        assert response.status_code == 200
        pages.append(response)
        next_links = links(response.content).get("next")
        url = next_links[0][0] if next_links else None
    return pages


# Strict query admission — pure


@pytest.mark.parametrize(
    "query,expected",
    [
        ("", None),
        ("cursor=abc", "abc"),
        ("cursor=a%3Ab", "a:b"),
        ("cursor=a:b", "a:b"),
        ("%63ursor=abc", "abc"),
        ("cursor=a+b", "a b"),
        ("cursor=" + "x" * (MAX_QUERY_BYTES - 7), "x" * (MAX_QUERY_BYTES - 7)),
    ],
)
def test_query_accepts_head_or_one_cursor(query, expected):
    assert parse_paged_feed_query(query) == expected


@pytest.mark.parametrize(
    "query",
    [
        "cursor=" + "x" * (MAX_QUERY_BYTES - 6),
        "cursor=é",
        "cursor=%",
        "cursor=%4",
        "cursor=%zz",
        "cursor=%ff",
        "cursor=a&cursor=b",
        "cursor=a&page=2",
        "cursor=a&",
        "&cursor=a",
        "&",
        "cursor",
        "cursor=",
        "=abc",
        "Cursor=abc",
        "page=2",
        "size=500",
    ],
)
def test_query_rejects_everything_else(query):
    with pytest.raises(InvalidPagedFeedQuery) as excinfo:
        parse_paged_feed_query(query)
    assert isinstance(excinfo.value, InvalidFeedCursor)
    assert "abc" not in str(excinfo.value)


def test_navigation_links_and_classes_are_request_local():
    head = PagedFeedNavigation("https://h/f", "https://h/f", None, "application/rss+xml")
    assert head.links() == [("first", "https://h/f")]
    page = replace(head, self_url="https://h/f?cursor=a", next_url="https://h/f?cursor=b")
    assert page.links() == [("first", "https://h/f"), ("next", "https://h/f?cursor=b")]
    for feed_class in PAGED_FEED_CLASSES.values():
        first, second = feed_class(repository=None, navigation=head), feed_class(repository=None, navigation=page)
        assert (first.navigation, second.navigation) == (head, page)
        assert "navigation" not in vars(feed_class)


# Traversal, navigation and parity with the legacy full feed


@pytest.mark.urls("tests.paged_feed_urls")
@pytest.mark.parametrize("kind,representation", list(FEEDS))
def test_traversal_matches_legacy_full_feed(
    client, paged_config, repository_mode, blog, podcast, kind, representation
):
    root = root_for(kind, blog, podcast)
    entries = make_entries(root, kind, 5)
    legacy = client.get(legacy_url(kind, representation, root), **HOST)
    assert legacy.status_code == 200
    head = paged_url(kind, representation, root)

    pages = walk(client, f"http://localhost{head}")

    assert [len(items(page.content)) for page in pages] == [2, 2, 1]
    # Exact per-GUID item bytes; legacy leaves tied dates unordered, pages break ties by descending pk.
    legacy_items = {item_id(item): ET.tostring(item) for item in items(legacy.content)}
    paged_items = [(item_id(item), ET.tostring(item)) for page in pages for item in items(page.content)]
    assert dict(paged_items) == legacy_items and len(paged_items) == len(legacy_items) == 5
    expected_order = sorted(entries, key=lambda entry: (entry.visible_date, entry.pk), reverse=True)
    assert [guid for guid, _ in paged_items] == [str(entry.uuid) for entry in expected_order]
    mime = "application/rss+xml" if representation == "rss" else "application/atom+xml"
    for index, page in enumerate(pages):
        assert page["Content-Type"] == f"{mime}; charset=utf-8"
        assert page["Cache-Control"] == "public, max-age=300"
        assert page["ETag"].startswith('W/"')
        assert not page.has_header("Last-Modified")
        assert page.content.startswith(b'<?xml version="1.0" encoding="utf-8"?>\n<?xml-stylesheet')
        page_links = links(page.content)
        assert page_links["first"] == [(f"http://localhost{head}", mime)]
        assert len(page_links["self"]) == 1
        if index == 0:
            assert page_links["self"][0][0] == f"http://localhost{head}"
        else:
            assert page_links["self"][0][0] == links(pages[index - 1].content)["next"][0][0]
        if index < len(pages) - 1:
            (next_href, next_type), *rest = page_links["next"]
            assert not rest and next_type == mime
            assert next_href.startswith(f"http://localhost{head}?cursor=") and "%3A" in next_href
        else:
            assert "next" not in page_links
        assert set(page_links) <= {"self", "first", "next"}
    legacy_channel = feed_root(legacy.content)
    head_channel = feed_root(pages[0].content)
    if representation == "rss":
        assert ET.fromstring(pages[0].content).attrib == ET.fromstring(legacy.content).attrib
    else:
        assert head_channel.findtext(f"{ATOM}id") == legacy_channel.findtext(f"{ATOM}id")
        assert {page_id for page in pages for page_id in [feed_root(page.content).findtext(f"{ATOM}id")]} == {
            legacy_channel.findtext(f"{ATOM}id")
        }

    def metadata(channel):
        return [
            ET.tostring(element) for element in channel if element.tag not in ("item", f"{ATOM}entry", f"{ATOM}link")
        ]

    assert metadata(head_channel) == metadata(legacy_channel)
    if kind == "podcast":
        content = b"".join(page.content for page in pages)
        assert content.count(b"psc:chapter ") == 1 and b"podcast:transcript" in content
        enclosures = [
            (link.get("href") or link.get("url"), link.get("length"))
            for page in pages
            for item in items(page.content)
            for link in item.findall("enclosure") + item.findall(f"{ATOM}link[@rel='enclosure']")
        ]
        assert len(set(enclosures)) == 5 and all(url.endswith(".mp3") for url, _ in enclosures)
        assert len({length for _, length in enclosures}) == 5


@pytest.mark.urls("tests.paged_feed_urls")
@pytest.mark.parametrize("representation", ["rss", "atom"])
def test_missing_format_keeps_legacy_eligibility(client, paged_config, repository_mode, podcast, representation):
    """Membership is not redefined: an episode lacking a format fails both serializers alike."""
    make_entries(podcast, "podcast", 2)
    audio = make_audio(podcast.owner, "m4a-only", ["m4a"])
    EpisodeFactory(
        parent=podcast, owner=podcast.owner, title="m4a only", slug="m4a-only", body=[], podcast_audio=audio
    )
    for url in [legacy_url("podcast", representation, podcast), paged_url("podcast", representation, podcast)]:
        with pytest.raises(ValueError, match="'mp3' attribute has no file"):
            client.get(url, **HOST)
    legacy = client.get(legacy_url("podcast", representation, podcast, "m4a"), **HOST)
    pages = walk(client, paged_url("podcast", representation, podcast, "m4a"))
    legacy_items = {item_id(item): ET.tostring(item) for item in items(legacy.content)}
    paged_items = {item_id(item): ET.tostring(item) for page in pages for item in items(page.content)}
    assert paged_items == legacy_items and len(paged_items) == 3
    assert all(b".m4a" in item and b".mp3" not in item for item in paged_items.values())


@pytest.mark.urls("tests.paged_feed_urls")
@pytest.mark.parametrize("kind,representation", list(FEEDS))
def test_empty_head_and_exhausted_continuation(
    client, paged_config, repository_mode, blog, podcast, kind, representation
):
    root = root_for(kind, blog, podcast)
    head = f"http://localhost{paged_url(kind, representation, root)}"
    empty = client.get(head, **HOST)
    assert empty.status_code == 200 and items(empty.content) == []
    assert {rel: [href for href, _ in hrefs] for rel, hrefs in links(empty.content).items()} == {
        "self": [head],
        "first": [head],
    }
    entries = make_entries(root, kind, 3)
    # The empty head stays cached for up to 300 seconds; expire it to observe new entries.
    cache.clear()
    first = client.get(head, **HOST)
    ((next_url, _),) = links(first.content)["next"]
    min(entries, key=lambda entry: (entry.visible_date, entry.pk)).delete()
    tail = client.get(next_url, **HOST)
    assert tail.status_code == 200 and items(tail.content) == []
    assert links(tail.content)["self"][0][0] == next_url
    assert links(tail.content)["first"][0][0] == head
    assert "next" not in links(tail.content)


@pytest.mark.urls("tests.paged_feed_urls")
def test_page_size_changes_keep_cursors_valid(client, paged_config, blog):
    make_entries(blog, "blog", 5)
    head = client.get(paged_url("blog", "rss", blog), **HOST)
    ((next_url, _),) = links(head.content)["next"]
    paged_config.CAST_FEED_PAGINATION = [config("/test_blog/", page_size=3)]
    rest = client.get(next_url, **HOST)
    assert rest.status_code == 200 and len(items(rest.content)) == 3
    assert "next" not in links(rest.content)


@pytest.mark.urls("tests.paged_feed_urls")
@pytest.mark.parametrize(
    "change",
    ["unconfigured", "restricted", "inherited", "unpublished", "host", "blog-as-podcast", "format", "slug"],
)
def test_unavailable_targets_are_404_before_cursor_handling(client, paged_config, blog, podcast, site, change):
    url = paged_url("blog", "rss", blog)
    extra = dict(HOST)
    if change == "unconfigured":
        paged_config.CAST_FEED_PAGINATION = [config("/test_podcast/")]
    elif change == "restricted":
        PageViewRestriction.objects.create(page=blog, restriction_type=PageViewRestriction.LOGIN)
    elif change == "inherited":
        PageViewRestriction.objects.create(page=site.root_page, restriction_type=PageViewRestriction.PASSWORD)
    elif change == "unpublished":
        blog.unpublish()
    elif change == "host":
        extra["HTTP_HOST"] = "example.com"
    elif change == "blog-as-podcast":
        url = reverse("cast:paged_podcast_feed_rss", kwargs={"slug": blog.slug, "audio_format": "mp3"})
    elif change == "format":
        url = paged_url("podcast", "rss", podcast, "flac")
    else:
        url = url.replace(blog.slug, "unknown-blog")
    response = client.get(f"{url}?cursor=malformed", **extra)
    assert response.status_code == 404


def signed_cursor(scope, **changes):
    data = {"v": 1, "order": 1, "scope": asdict(scope), "date": DATE.isoformat(timespec="microseconds"), "pk": 1}
    return signing.Signer(salt=CURSOR_SALT).sign_object(data | changes)


@pytest.mark.urls("tests.paged_feed_urls")
def test_malformed_and_wrong_scope_queries_are_generic_400(client, paged_config, blog, podcast, site):
    url = paged_url("blog", "rss", blog)
    scope = FeedScope(site.pk, blog.pk)
    podcast_scope = FeedScope(site.pk, podcast.pk, kind="podcast", audio_format="m4a")
    bad_queries = [
        "cursor=not-a-cursor",
        "cursor=a&cursor=b",
        "page=2",
        "cursor=%zz",
        "cursor=" + "x" * MAX_QUERY_BYTES,
        "cursor=" + signed_cursor(replace(scope, representation="atom")),
        "cursor=" + signed_cursor(replace(scope, blog_id=podcast.pk)),
        "cursor=" + signed_cursor(replace(scope, family="legacy")),
    ]
    for query in bad_queries:
        response = client.get(f"{url}?{query}", **HOST)
        assert response.status_code == 400
        assert response.content == b"Invalid feed request"
        assert response["Cache-Control"] == "no-store"
    mp3_url = paged_url("podcast", "rss", podcast, "mp3")
    assert client.get(f"{mp3_url}?cursor={signed_cursor(podcast_scope)}", **HOST).status_code == 400


@pytest.mark.urls("tests.paged_feed_urls")
def test_unverifiable_or_unsupported_cursors_restart_at_validated_head(client, paged_config, blog, site, settings):
    make_entries(blog, "blog", 3)
    url = paged_url("blog", "atom", blog)
    scope = FeedScope(site.pk, blog.pk, representation="atom")
    valid = signed_cursor(scope)
    tampered = valid[:-1] + ("A" if valid[-1] != "A" else "B")
    for cursor in [tampered, signed_cursor(scope, v=2), signed_cursor(scope, order=2)]:
        response = client.get(f"{url}?cursor={cursor}", **HOST)
        assert response.status_code == 302
        assert response["Location"] == f"http://localhost{url}"
        assert response["Cache-Control"] == "no-store"
    settings.SECRET_KEY_FALLBACKS = [settings.SECRET_KEY]
    settings.SECRET_KEY = "rotated-paged-feed-test-key"
    assert client.get(f"{url}?cursor={valid}", **HOST).status_code == 200
    settings.SECRET_KEY_FALLBACKS = []
    assert client.get(f"{url}?cursor={valid}", **HOST).status_code == 302


@pytest.mark.urls("tests.paged_feed_urls")
def test_methods_and_head(client, paged_config, blog):
    make_entries(blog, "blog", 1)
    url = paged_url("blog", "rss", blog)
    rejected = client.post(url, **HOST)
    assert rejected.status_code == 405
    assert rejected["Allow"] == "GET, HEAD"
    assert rejected["Cache-Control"] == "no-store"
    head = client.head(url, **HOST)
    get = client.get(url, **HOST)
    assert head.status_code == get.status_code == 200
    assert head.content == b"" and get.content
    assert head["Content-Type"] == get["Content-Type"]


# URL mounts, prefixes and origins


def test_public_paged_routes_are_additive(blog):
    assert reverse("cast:paged_entries_feed", kwargs={"slug": blog.slug}) == "/cast/test_blog/feed/paged/rss.xml"
    assert reverse("cast:latest_entries_feed", kwargs={"slug": blog.slug}) == "/cast/test_blog/feed/rss.xml"
    kwargs = {"slug": "p", "audio_format": "mp3"}
    assert reverse("cast:paged_podcast_feed_atom", kwargs=kwargs) == "/cast/p/feed/podcast/mp3/paged/atom.xml"
    assert reverse("cast:podcast_feed_atom", kwargs=kwargs) == "/cast/p/feed/podcast/mp3/atom.xml"


@pytest.fixture()
def locale_middleware(settings):
    """Enable LocaleMiddleware and restore the thread language it activates and never deactivates."""
    session = settings.MIDDLEWARE.index("django.contrib.sessions.middleware.SessionMiddleware")
    settings.MIDDLEWARE = [
        *settings.MIDDLEWARE[: session + 1],
        "django.middleware.locale.LocaleMiddleware",
        *settings.MIDDLEWARE[session + 1 :],
    ]
    with translation.override(translation.get_language()):
        yield


@pytest.mark.parametrize(
    "urlconf,expected_path",
    [
        ("tests.paged_feed_urls", "/blogs/test_blog/feed/paged/rss.xml"),
        ("tests.paged_feed_root_urls", "/test_blog/feed/paged/rss.xml"),
        ("tests.paged_feed_i18n_urls", "/de/blogs/test_blog/feed/paged/rss.xml"),
    ],
)
def test_links_follow_mount_and_language_prefix(
    client, paged_config, blog, settings, locale_middleware, urlconf, expected_path
):
    settings.ROOT_URLCONF = urlconf
    client.cookies["django_language"] = "fr"
    extra = {**HOST, "HTTP_ACCEPT_LANGUAGE": "fr"}
    make_entries(blog, "blog", 3)
    with translation.override("de"):
        assert paged_url("blog", "rss", blog) == expected_path
    response = client.get(expected_path, **extra)
    assert response.status_code == 200
    page_links = links(response.content)
    assert page_links["self"][0][0] == page_links["first"][0][0] == f"http://localhost{expected_path}"
    assert page_links["next"][0][0].startswith(f"http://localhost{expected_path}?cursor=")
    # A URL language prefix is part of the document URL, not the rendering language.
    assert f"<language>{settings.LANGUAGE_CODE}</language>".encode() in response.content
    assert client.get(page_links["next"][0][0], **extra).status_code == 200


@pytest.mark.urls("tests.paged_feed_urls")
def test_script_prefix_and_unexpected_alias(rf, paged_config, blog):
    make_entries(blog, "blog", 1)
    path = paged_url("blog", "rss", blog)
    set_script_prefix("/app/")
    try:
        request = rf.get(path, SCRIPT_NAME="/app", **HOST)
        response = internal_paged_feed_response(request, slug=blog.slug, kind="blog", representation="rss")
    finally:
        set_script_prefix("/")
    assert response.status_code == 200
    assert links(response.content)["self"][0][0] == f"http://localhost/app{path}"
    alias = rf.get("/elsewhere/rss.xml", **HOST)
    with pytest.raises(Http404, match="canonical"):
        internal_paged_feed_response(alias, slug=blog.slug, kind="blog", representation="rss")


@pytest.mark.urls("tests.paged_feed_urls")
@pytest.mark.parametrize(
    "port,secure,host,origin",
    [
        (443, True, "localhost", "https://localhost"),
        (8000, False, "LOCALHOST:8000", "http://localhost:8000"),
    ],
)
def test_origin_is_the_validated_normalized_request_origin(
    client, paged_config, blog, site, port, secure, host, origin
):
    site.port = port
    site.save()
    paged_config.CAST_FEED_PAGINATION = [config("/test_blog/", port=port)]
    make_entries(blog, "blog", 3)
    path = paged_url("blog", "atom", blog)
    response = client.get(path, secure=secure, HTTP_HOST=host)
    assert response.status_code == 200
    page_links = links(response.content)
    assert page_links["self"][0][0] == f"{origin}{path}"
    assert page_links["next"][0][0].startswith(f"{origin}{path}?cursor=")
    assert client.get(page_links["next"][0][0], secure=secure, HTTP_HOST=host).status_code == 200


@pytest.mark.urls("tests.paged_feed_urls")
def test_cursor_query_is_rebuilt_canonically(client, paged_config, blog):
    make_entries(blog, "blog", 3)
    url = paged_url("blog", "rss", blog)
    ((next_url, _),) = links(client.get(url, **HOST).content)["next"]
    encoded = next_url.split("?cursor=", 1)[1]
    raw_colon = client.get(f"{url}?cursor={encoded.replace('%3A', ':')}", **HOST)
    lowercase_escape = client.get(f"{url}?%63ursor={encoded.replace('%3A', '%3a')}", **HOST)
    for response in [raw_colon, lowercase_escape]:
        assert response.status_code == 200
        assert links(response.content)["self"][0][0] == next_url


# Isolated anonymous rendering with fixed language and timezone


@pytest.fixture()
def rendering_spy(monkeypatch):
    captured = []
    original = RepositoryMixin.item_description

    def item_description(feed, item):
        captured.append((feed.request, translation.get_language(), django_timezone.get_current_timezone_name()))
        return original(feed, item)

    monkeypatch.setattr(RepositoryMixin, "item_description", item_description)
    return captured


@pytest.mark.urls("tests.paged_feed_urls")
@pytest.mark.parametrize("fixed", [("en-us", "America/Chicago"), ("de", "Europe/Berlin")])
def test_rendering_ignores_caller_state_and_restores_locale(rf, paged_config, podcast, user, rendering_spy, fixed):
    paged_config.LANGUAGE_CODE, paged_config.TIME_ZONE = fixed
    make_entries(podcast, "podcast", 3)
    url = paged_url("podcast", "rss", podcast)
    kwargs = {"slug": podcast.slug, "kind": "podcast", "representation": "rss", "audio_format": "mp3"}
    baseline = internal_paged_feed_response(rf.get(url, **HOST), **kwargs).content
    rendering_spy.clear()

    request = rf.get(
        url, HTTP_ACCEPT_LANGUAGE="fr", HTTP_HX_REQUEST="true", HTTP_COOKIE="django_language=fr; sessionid=x", **HOST
    )
    request.user = user
    request.session = {"template_base_dir": "plain"}
    request.LANGUAGE_CODE = "fr"
    before = dict(vars(request))
    translation.activate("fr")
    django_timezone.activate("Asia/Tokyo")
    try:
        response = internal_paged_feed_response(request, **kwargs)
        assert translation.get_language() == "fr"
        assert django_timezone.get_current_timezone_name() == "Asia/Tokyo"
    finally:
        translation.deactivate()
        django_timezone.deactivate()

    assert response.content == baseline
    assert f"<language>{fixed[0]}</language>".encode() in response.content
    assert len(rendering_spy) == PAGE_SIZE
    for isolated, language, timezone_name in rendering_spy:
        assert isolated is not request
        assert (language, timezone_name, isolated.LANGUAGE_CODE) == (fixed[0], fixed[1], fixed[0])
        assert isolated.user.is_anonymous and not hasattr(isolated, "session")
        assert isolated.COOKIES == {} and not isolated.htmx
        assert isolated.get_full_path() == url and isolated.build_absolute_uri() == f"http://localhost{url}"
    # Owner resolution may cache the resolved Site; nothing else on the caller changes.
    after = dict(vars(request))
    assert set(after) - set(before) <= {"_wagtail_site"}
    assert {key: after[key] for key in before} == before
    assert request.session == {"template_base_dir": "plain"} and request.LANGUAGE_CODE == "fr"


@pytest.mark.urls("tests.paged_feed_urls")
def test_rendering_is_independent_of_logged_in_client(client, paged_config, blog, user):
    make_entries(blog, "blog", 3)
    url = paged_url("blog", "atom", blog)
    anonymous = client.get(url, **HOST).content
    client.force_login(user)
    session = client.session
    session["template_base_dir"] = "plain"
    session.save()
    logged_in = client.get(url, HTTP_HX_REQUEST="true", **HOST)
    assert logged_in.content == anonymous


@pytest.mark.urls("tests.paged_feed_urls")
@pytest.mark.parametrize("kind", ["blog", "podcast"])
def test_selection_and_hydration_are_bounded(
    rf, paged_config, repository_mode, blog, podcast, mocker, kind, rendering_spy
):
    root = root_for(kind, blog, podcast)
    make_entries(root, kind, 5)
    path = paged_url(kind, "rss", root)
    target = admit_paged_feed_request(
        rf.get(path, **HOST),
        slug=root.slug,
        kind=kind,
        representation="rss",
        audio_format="mp3" if kind == "podcast" else None,
    )
    select = mocker.spy(paged_feeds, "select_feed_page")
    hydrate = mocker.spy(PostQuerySnapshot, "create_from_post_queryset")
    selection = select_paged_feed(target)
    select.assert_called_once_with(target.scope, page_size=PAGE_SIZE, cursor=None)
    rendered = render_paged_feed(target, selection)
    assert len(selection.ids) == PAGE_SIZE and selection.next_cursor is not None
    assert tuple(hydrate.call_args.kwargs["queryset"].values_list("pk", flat=True)) == selection.ids
    assert len(rendering_spy) == PAGE_SIZE
    uuids = dict(Post.objects.filter(pk__in=selection.ids).values_list("pk", "uuid"))
    assert [item_id(item) for item in items(rendered.content)] == [str(uuids[pk]) for pk in selection.ids]
    assert rendered.next_url == target.page_url(selection.next_cursor)
    assert rendered.document_url == target.head_url


@pytest.mark.urls("tests.paged_feed_urls")
def test_adapters_never_fall_back_and_validate_scope(rf, paged_config, repository_mode, blog, podcast, site):
    make_entries(blog, "blog", 3)
    request = rf.get(paged_url("blog", "rss", blog), **HOST)
    target = admit_paged_feed_request(request, slug=blog.slug, kind="blog", representation="rss")
    selection = select_paged_feed(target)
    navigation = PagedFeedNavigation(target.document_url, target.head_url, None, "application/rss+xml")
    context = paged_feeds.build_feed_page_context(paged_feeds.IsolatedFeedRequest(target), selection)

    feed = paged_feeds.PagedEntriesFeed(repository=context, navigation=navigation)
    assert feed.get_repository(request, blog) is context
    context.used = True
    with pytest.raises(RuntimeError, match="exactly once"):
        feed.get_repository(request, blog)
    with pytest.raises(RuntimeError, match="exactly once"):
        paged_feeds.PagedEntriesAtomFeed(repository=None, navigation=navigation).get_object(request)
    context.used = False
    podcast_feed = paged_feeds.PagedRssPodcastFeed(repository=context, navigation=navigation)
    with pytest.raises(Http404, match="require a Podcast"):
        podcast_feed.get_object(request, audio_format="mp3")

    other_scope = replace(selection, scope=replace(selection.scope, representation="atom"))
    with pytest.raises(ValueError, match="admitted target"):
        render_paged_feed(target, other_scope)
    empty = select_feed_page(FeedScope(site.pk, podcast.pk, kind="podcast", audio_format="mp3"))
    with pytest.raises(ValueError, match="admitted target"):
        render_paged_feed(target, empty)
