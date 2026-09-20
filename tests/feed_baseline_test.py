"""Pre-pagination contracts, including accepted five-minute child-cache staleness."""

import feedparser
import pytest
from django.core.cache import cache
from django.urls import reverse
from wagtail.models import PageViewRestriction

from cast import appsettings
from tests.factories import EpisodeFactory, PostFactory


@pytest.fixture(params=["default", "django"])
def feed_repository(request, monkeypatch):
    monkeypatch.setattr(appsettings, "CAST_REPOSITORY", request.param)
    cache.clear()
    yield request.param
    cache.clear()


@pytest.fixture(params=["latest_entries_feed", "latest_entries_atom_feed", "podcast_feed_rss", "podcast_feed_atom"])
def feed_case(request, post, episode):
    podcast = request.param.startswith("podcast_")
    entry = episode if podcast else post
    assert post.blog.pk != episode.blog.pk
    kwargs = {"slug": entry.blog.slug}
    if podcast:
        kwargs["audio_format"] = "m4a"
    return reverse(f"cast:{request.param}", kwargs=kwargs), entry, podcast


@pytest.mark.django_db
def test_full_feed_membership_and_identity(client, feed_repository, feed_case):
    url, entry, podcast = feed_case
    factory = EpisodeFactory if podcast else PostFactory
    extra = {"podcast_audio": entry.podcast_audio} if podcast else {}
    # Cross the nonexistent 50-item limit previously advertised by the docs.
    entries = [entry] + [
        factory(parent=entry.blog, owner=entry.owner, title=f"baseline {i}", slug=f"baseline-{i}", body=[], **extra)
        for i in range(50)
    ]
    response = client.get(url)
    assert response.status_code == 200
    parsed = feedparser.parse(response.content)
    assert len(parsed.entries) == 51
    assert {item.id for item in parsed.entries} == {str(item.uuid) for item in entries}
    dates_by_id = {str(item.uuid): item.visible_date for item in entries}
    returned_dates = [dates_by_id[item.id] for item in parsed.entries]
    assert returned_dates == sorted(returned_dates, reverse=True)
    self_links = [link.href for link in parsed.feed.links if link.rel == "self"]
    assert self_links == [f"http://testserver{url}"]
    if "atom" in url:
        expected_id = entry.blog.get_full_url() if podcast else f"http://testserver{entry.blog.url}"
        assert parsed.feed.id == expected_id
    if podcast:
        for item in parsed.entries:
            assert item.enclosures[0].href == entry.get_enclosure_url("m4a")
    assert client.get(url).content == response.content


@pytest.mark.django_db
@pytest.mark.parametrize("change", ["restrict", "unpublish", "delete"])
def test_accepted_cached_child_visibility(client, feed_repository, feed_case, change):
    """Child changes become visible after cache expiry/invalidation, by accepted policy."""
    url, entry, _ = feed_case
    identity = str(entry.uuid)
    first = client.get(url)
    assert first.status_code == 200
    assert identity in {item.id for item in feedparser.parse(first.content).entries}
    if change == "restrict":
        PageViewRestriction.objects.create(page=entry, restriction_type=PageViewRestriction.LOGIN)
    elif change == "unpublish":
        entry.unpublish()
    else:
        entry.delete()
    warm = client.get(url)
    assert warm.content == first.content
    cache.clear()
    cold = client.get(url)
    assert cold.status_code == 200
    assert identity not in {item.id for item in feedparser.parse(cold.content).entries}
