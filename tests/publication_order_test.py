"""Equal publication timestamps retain deterministic index and feed membership."""

from datetime import timedelta

import feedparser
import pytest
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone

from cast.models import Audio
from tests.factories import EpisodeFactory, PostFactory


@pytest.fixture(params=["default", "django"])
def repository_mode(request, settings):
    settings.CAST_REPOSITORY = request.param
    cache.clear()
    yield
    cache.clear()


@pytest.mark.django_db
@pytest.mark.parametrize("ordering", ["", "visible_date", "-visible_date"])
def test_equal_date_index_pages(client, blog, settings, repository_mode, ordering):
    settings.POST_LIST_PAGINATION = 3
    now = timezone.now()
    posts = [
        PostFactory(parent=blog, owner=blog.owner, title=f"Post {i}", slug=f"post-{i}", body=[], visible_date=now)
        for i in range(8)
    ]
    expected = sorted((post.pk for post in posts), reverse=True)
    for _ in range(2):
        found = []
        for page in range(1, 4):
            response = client.get(blog.get_url(), {"page": page, "o": ordering})
            assert response.status_code == 200
            found.extend(post.pk for post in response.context["posts"])
        assert found == expected


@pytest.fixture
def publication_episode(podcast):
    # Ordering needs enclosure metadata only, never an audio sample or a probe.
    audio = Audio.objects.create(
        user=podcast.owner,
        title="Synthetic audio",
        m4a="cast_audio/synthetic.m4a",
        duration=timedelta(seconds=1),
        data={"size": {"m4a": 1}},
    )
    return EpisodeFactory(
        owner=podcast.owner,
        parent=podcast,
        title="Synthetic episode",
        slug="synthetic-episode",
        body=[],
        podcast_audio=audio,
    )


@pytest.mark.django_db
@pytest.mark.parametrize("podcast_feed", [False, True])
@pytest.mark.parametrize("format", ["rss", "atom"])
def test_equal_date_feed_order(client, blog, publication_episode, settings, repository_mode, podcast_feed, format):
    episode = publication_episode
    now = timezone.now()
    parent = episode.blog if podcast_feed else blog
    factory = EpisodeFactory if podcast_feed else PostFactory
    extra = {"podcast_audio": episode.podcast_audio} if podcast_feed else {}
    posts = [
        factory(
            parent=parent,
            owner=parent.owner,
            title=f"Entry {i}",
            slug=f"entry-{i}",
            body=[],
            visible_date=now,
            **extra,
        )
        for i in range(5)
    ]
    if podcast_feed:
        episode.visible_date = now
        episode.save(update_fields=["visible_date"])
        posts.append(episode)
        route = "podcast_feed_rss" if format == "rss" else "podcast_feed_atom"
        kwargs = {"slug": parent.slug, "audio_format": "m4a"}
    else:
        settings.CAST_BLOG_FEED_ITEM_LIMIT = 3
        route = "latest_entries_feed" if format == "rss" else "latest_entries_atom_feed"
        kwargs = {"slug": parent.slug}
    expected = [str(post.uuid) for post in sorted(posts, key=lambda post: post.pk, reverse=True)]
    if not podcast_feed:
        expected = expected[:3]
    response = client.get(reverse(f"cast:{route}", kwargs=kwargs))
    assert response.status_code == 200
    assert [entry.id for entry in feedparser.parse(response.content).entries] == expected
