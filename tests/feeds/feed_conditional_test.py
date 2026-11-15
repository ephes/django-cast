"""Conditional GET (ETag / 304) for the built-in feed routes and the optional itunes:summary."""

import pytest
from django.core.cache import cache
from django.http import HttpResponse, StreamingHttpResponse
from django.urls import reverse
from wagtail.models import PageViewRestriction

from cast import appsettings
from cast.feeds import etag_conditional_feed

FEED_ROUTES = ["latest_entries_feed", "latest_entries_atom_feed", "podcast_feed_rss", "podcast_feed_atom"]


@pytest.fixture
def clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture(params=FEED_ROUTES)
def feed_url(request, post, episode, clear_cache):
    if request.param.startswith("podcast_"):
        return reverse(f"cast:{request.param}", kwargs={"slug": episode.blog.slug, "audio_format": "m4a"})
    return reverse(f"cast:{request.param}", kwargs={"slug": post.blog.slug})


@pytest.mark.django_db
def test_feed_sends_weak_etag_and_answers_matching_if_none_match_with_304(client, feed_url):
    response = client.get(feed_url)
    assert response.status_code == 200
    etag = response["ETag"]
    assert etag.startswith('W/"')

    not_modified = client.get(feed_url, HTTP_IF_NONE_MATCH=etag)
    assert not_modified.status_code == 304
    assert not_modified.content == b""
    assert not_modified["ETag"] == etag
    assert not_modified["Cache-Control"] == response["Cache-Control"]

    # A strong form of the same validator matches too (weak comparison).
    assert client.get(feed_url, HTTP_IF_NONE_MATCH=etag.removeprefix("W/")).status_code == 304
    assert client.get(feed_url, HTTP_IF_NONE_MATCH=f'"other", {etag}').status_code == 304


@pytest.mark.django_db
def test_feed_etag_is_stable_across_cache_hits_and_regeneration(client, feed_url):
    first = client.get(feed_url)
    cached = client.get(feed_url)
    cache.clear()
    regenerated = client.get(feed_url)
    assert first["ETag"] == cached["ETag"] == regenerated["ETag"]
    assert regenerated.content == first.content


@pytest.mark.django_db
def test_changed_feed_content_changes_etag(client, post, episode, clear_cache):
    url = reverse("cast:podcast_feed_rss", kwargs={"slug": episode.blog.slug, "audio_format": "m4a"})
    etag = client.get(url)["ETag"]
    episode.title = "A changed title"
    episode.save_revision().publish()
    cache.clear()
    response = client.get(url, HTTP_IF_NONE_MATCH=etag)
    assert response.status_code == 200
    assert response["ETag"] != etag


@pytest.mark.django_db
def test_mismatched_etag_returns_full_feed(client, feed_url):
    response = client.get(feed_url, HTTP_IF_NONE_MATCH='W/"stale"')
    assert response.status_code == 200
    assert response.content


@pytest.mark.django_db
def test_if_modified_since_alone_never_returns_304(client, feed_url):
    """Last-Modified tracks only the newest entry, so it is not trusted for 304 responses."""
    response = client.get(feed_url)
    last_modified = response.get("Last-Modified", "Fri, 01 Jan 2100 00:00:00 GMT")
    assert client.get(feed_url, HTTP_IF_MODIFIED_SINCE=last_modified).status_code == 200


@pytest.mark.django_db
def test_head_request_revalidates(client, feed_url):
    etag = client.get(feed_url)["ETag"]
    response = client.head(feed_url, HTTP_IF_NONE_MATCH=etag)
    assert response.status_code == 304


@pytest.mark.django_db
def test_if_match_mismatch_returns_412(client, feed_url):
    assert client.get(feed_url, HTTP_IF_MATCH='"nope"').status_code == 412


@pytest.mark.django_db
def test_restricted_feed_root_is_hidden_before_revalidation(client, post, clear_cache):
    url = reverse("cast:latest_entries_feed", kwargs={"slug": post.blog.slug})
    etag = client.get(url)["ETag"]
    PageViewRestriction.objects.create(page=post.blog, restriction_type=PageViewRestriction.LOGIN)
    assert client.get(url, HTTP_IF_NONE_MATCH=etag).status_code == 404


def test_etag_decorator_leaves_other_responses_unchanged(rf):
    responses = {
        "error": HttpResponse(b"missing", status=404),
        "streaming": StreamingHttpResponse(iter([b"chunk"])),
        "post": HttpResponse(b"body"),
    }
    for name, original in responses.items():
        request = rf.post("/feed/") if name == "post" else rf.get("/feed/")
        response = etag_conditional_feed(lambda request, original=original: original)(request)
        assert response is original
        assert not response.has_header("ETag")


def test_etag_decorator_keeps_existing_etag(rf):
    original = HttpResponse(b"body")
    original["ETag"] = '"given"'
    view = etag_conditional_feed(lambda request: original)
    assert view(rf.get("/feed/"))["ETag"] == '"given"'
    assert view(rf.get("/feed/", HTTP_IF_NONE_MATCH='"given"')).status_code == 304


@pytest.mark.django_db
@pytest.mark.parametrize("route_name", ["podcast_feed_rss", "podcast_feed_atom"])
def test_itunes_summary_is_emitted_by_default(client, episode, clear_cache, route_name):
    url = reverse(f"cast:{route_name}", kwargs={"slug": episode.blog.slug, "audio_format": "m4a"})
    assert appsettings.CAST_FEED_ITUNES_SUMMARY is True
    content = client.get(url).content
    assert content.count(b"<itunes:summary") == 2  # channel and the episode


@pytest.mark.django_db
@pytest.mark.parametrize("route_name", ["podcast_feed_rss", "podcast_feed_atom"])
def test_itunes_summary_can_be_disabled(client, episode, clear_cache, settings, route_name):
    settings.CAST_FEED_ITUNES_SUMMARY = False
    url = reverse(f"cast:{route_name}", kwargs={"slug": episode.blog.slug, "audio_format": "m4a"})
    content = client.get(url).content
    assert b"itunes:summary" not in content
    assert b"<itunes:subtitle>" in content
