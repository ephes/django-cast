"""CAST_BLOG_FEED_ITEM_LIMIT keeps blog feeds short and leaves podcast feeds complete."""

from datetime import timedelta

import feedparser
import pytest
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone

from cast import appsettings
from tests.factories import EpisodeFactory, PostFactory


@pytest.fixture(params=["default", "django"])
def feed_repository(request, monkeypatch):
    monkeypatch.setattr(appsettings, "CAST_REPOSITORY", request.param)
    cache.clear()
    yield request.param
    cache.clear()


def _dated_posts(factory, parent, owner, count, **extra):
    now = timezone.now()
    return [
        factory(
            parent=parent,
            owner=owner,
            title=f"entry {i}",
            slug=f"entry-{i}",
            body=[],
            visible_date=now - timedelta(days=i),
            **extra,
        )
        for i in range(count)
    ]


@pytest.mark.django_db
@pytest.mark.parametrize("route_name", ["latest_entries_feed", "latest_entries_atom_feed"])
def test_blog_feed_keeps_only_newest_posts(client, post, feed_repository, monkeypatch, route_name):
    monkeypatch.setattr(appsettings, "CAST_BLOG_FEED_ITEM_LIMIT", 3)
    posts = [post, *_dated_posts(PostFactory, post.blog, post.owner, 5)]
    newest = sorted(posts, key=lambda item: item.visible_date, reverse=True)[:3]

    response = client.get(reverse(f"cast:{route_name}", kwargs={"slug": post.blog.slug}))

    parsed = feedparser.parse(response.content)
    assert [entry.id for entry in parsed.entries] == [str(item.uuid) for item in newest]


@pytest.mark.django_db
def test_blog_feed_is_complete_without_limit(client, post, feed_repository):
    assert appsettings.CAST_BLOG_FEED_ITEM_LIMIT is None
    _dated_posts(PostFactory, post.blog, post.owner, 5)

    response = client.get(reverse("cast:latest_entries_feed", kwargs={"slug": post.blog.slug}))

    assert len(feedparser.parse(response.content).entries) == 6


@pytest.mark.django_db
@pytest.mark.parametrize("route_name", ["podcast_feed_rss", "podcast_feed_atom"])
def test_podcast_feed_ignores_blog_feed_limit(client, episode, feed_repository, monkeypatch, route_name):
    monkeypatch.setattr(appsettings, "CAST_BLOG_FEED_ITEM_LIMIT", 1)
    _dated_posts(EpisodeFactory, episode.blog, episode.owner, 3, podcast_audio=episode.podcast_audio)

    url = reverse(f"cast:{route_name}", kwargs={"slug": episode.blog.slug, "audio_format": "m4a"})
    response = client.get(url)

    assert len(feedparser.parse(response.content).entries) == 4
