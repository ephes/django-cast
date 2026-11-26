"""Podcast feed renders must not ask the media storage for every enclosure size."""

from datetime import timedelta

import feedparser
import pytest
from django.core.cache import cache
from django.core.files.storage import FileSystemStorage
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from cast.models import Audio
from tests.factories import EpisodeFactory


@pytest.fixture(params=["default", "django"])
def feed_repository(request, settings):
    settings.CAST_REPOSITORY = request.param
    cache.clear()
    yield request.param
    cache.clear()


def _legacy_sized_episodes(podcast, audio, count):
    """Episodes whose audio size was cached before sizes were bound to file names."""
    now = timezone.now()
    episodes = []
    for i in range(count):
        legacy = Audio.objects.create(user=audio.user, title=f"legacy {i}", m4a=audio.m4a.name, duration=None)
        Audio.objects.filter(pk=legacy.pk).update(data={"size": {"m4a": 1}})
        episodes.append(
            EpisodeFactory(
                owner=podcast.owner,
                parent=podcast,
                title=f"episode {i}",
                slug=f"episode-{i}",
                podcast_audio=legacy,
                body=[],
                visible_date=now - timedelta(days=i),
            )
        )
    return episodes


def _render_feed(client, podcast, capture_on_commit):
    cache.clear()  # a feed cache miss, as after the five-minute feed cache expires
    url = reverse("cast:podcast_feed_rss", kwargs={"slug": podcast.slug, "audio_format": "m4a"})
    # Run the size cache writes the request schedules for after its commit.
    with capture_on_commit(execute=True), CaptureQueriesContext(connection) as queries:
        response = client.get(url)
    assert response.status_code == 200
    return response, len(queries)


@pytest.mark.django_db
def test_feed_reads_each_legacy_size_from_storage_only_once(
    client, podcast, audio, feed_repository, mocker, django_capture_on_commit_callbacks
):
    _legacy_sized_episodes(podcast, audio, 3)
    storage_size = mocker.spy(FileSystemStorage, "size")

    first, _ = _render_feed(client, podcast, django_capture_on_commit_callbacks)
    assert storage_size.call_count == 3

    second, _ = _render_feed(client, podcast, django_capture_on_commit_callbacks)
    assert storage_size.call_count == 3  # the healed sizes need no storage request
    lengths = [entry.enclosures[0].length for entry in feedparser.parse(second.content).entries]
    assert lengths == [str(audio.m4a.size)] * 3
    assert first.content == second.content


@pytest.mark.django_db
def test_healed_feed_query_count_does_not_grow_with_episodes(
    client, podcast, audio, feed_repository, django_capture_on_commit_callbacks
):
    _legacy_sized_episodes(podcast, audio, 2)
    _render_feed(client, podcast, django_capture_on_commit_callbacks)  # heals the legacy sizes
    _, two_episodes = _render_feed(client, podcast, django_capture_on_commit_callbacks)

    third = Audio.objects.create(user=audio.user, title="third", m4a=audio.m4a.name, duration=None)
    EpisodeFactory(
        owner=podcast.owner, parent=podcast, title="episode 2", slug="episode-2", podcast_audio=third, body=[]
    )
    _render_feed(client, podcast, django_capture_on_commit_callbacks)
    _, three_episodes = _render_feed(client, podcast, django_capture_on_commit_callbacks)

    assert two_episodes > 0
    assert three_episodes == two_episodes
