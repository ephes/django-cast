from datetime import datetime
from time import mktime

import feedparser
import pytest
import pytz
from django.http import Http404
from django.urls import reverse

from cast.feeds import ITunesElements, PodcastFeed
from cast.models import Post


def test_unknown_audio_format():
    pf = PodcastFeed()
    with pytest.raises(Http404):
        pf.set_audio_format("foobar")


class TestFeedCreation:
    pytestmark = pytest.mark.django_db

    def test_add_artwork_true(self, dummy_handler, blog_with_artwork):
        ie = ITunesElements()
        ie.feed = {"title": "foobar", "link": "bar"}
        ie.add_artwork(blog_with_artwork, dummy_handler)
        assert "itunes:image" in dummy_handler.aqe
        assert "image" in dummy_handler.se
        assert "image" in dummy_handler.ee

    def test_add_artwork_false(self, dummy_handler, blog):
        ie = ITunesElements()
        ie.feed = {"title": "foobar", "link": "bar"}
        ie.add_artwork(blog, dummy_handler)
        assert "itunes:image" not in dummy_handler.aqe
        assert "image" not in dummy_handler.se
        assert "image" not in dummy_handler.ee

    def test_itunes_categories(self, dummy_handler, blog_with_itunes_categories):
        blog = blog_with_itunes_categories
        ie = ITunesElements()
        ie.add_itunes_categories(blog, dummy_handler)
        assert dummy_handler.se["itunes:category"]["text"] == "foo"
        assert dummy_handler.aqe["itunes:category"][-1]["text"] == "baz"
        assert "itunes:category" in dummy_handler.ee


@pytest.fixture
def use_dummy_cache_backend(settings):
    settings.CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.dummy.DummyCache",
        }
    }


class TestGeneratedFeeds:
    pytestmark = pytest.mark.django_db

    def test_get_latest_entries_feed(self, client, post, use_dummy_cache_backend):
        feed_url = reverse("cast:latest_entries_feed", kwargs={"slug": post.blog.slug})

        r = client.get(feed_url)
        assert r.status_code == 200

        content = r.content.decode("utf-8")
        assert "xml" in content
        assert post.title in content

    def test_get_podcast_m4a_feed_rss(self, client, podcast_episode, use_dummy_cache_backend):
        feed_url = reverse(
            "cast:podcast_feed_rss",
            kwargs={"slug": podcast_episode.blog.slug, "audio_format": "m4a"},
        )

        r = client.get(feed_url)
        assert r.status_code == 200

        content = r.content.decode("utf-8")
        assert "rss" in content
        assert podcast_episode.title in content

    def test_get_podcast_m4a_feed_atom(self, client, podcast_episode):
        feed_url = reverse(
            "cast:podcast_feed_atom",
            kwargs={"slug": podcast_episode.blog.slug, "audio_format": "m4a"},
        )

        r = client.get(feed_url)
        assert r.status_code == 200

        content = r.content.decode("utf-8")
        assert "feed" in content
        assert podcast_episode.title in content

    def test_podcast_feed_contains_only_podcasts(self, client, post, podcast_episode, use_dummy_cache_backend):
        feed_url = reverse(
            "cast:podcast_feed_rss",
            kwargs={"slug": podcast_episode.blog.slug, "audio_format": "m4a"},
        )
        r = client.get(feed_url)
        assert r.status_code == 200

        d = feedparser.parse(r.content)
        assert len(d.entries) == 1
        assert Post.objects.live().descendant_of(podcast_episode.blog).count() == 2

    def test_podcast_feed_contains_visible_date_as_pubdate(
        self, client, podcast_episode_with_different_visible_date, use_dummy_cache_backend
    ):
        podcast_episode = podcast_episode_with_different_visible_date
        feed_url = reverse(
            "cast:podcast_feed_rss",
            kwargs={"slug": podcast_episode.blog.slug, "audio_format": "m4a"},
        )

        r = client.get(feed_url)
        assert r.status_code == 200

        d = feedparser.parse(r.content)
        date_from_feed = datetime.fromtimestamp(mktime(d.entries[0]["published_parsed"]))
        date_from_feed = pytz.utc.localize(date_from_feed)
        assert date_from_feed == podcast_episode.visible_date

    def test_podcast_feed_contains_detail_information(self, client, podcast_episode):
        feed_url = reverse(
            "cast:podcast_feed_rss",
            kwargs={"slug": podcast_episode.blog.slug, "audio_format": "m4a"},
        )

        r = client.get(feed_url)
        assert r.status_code == 200

        d = feedparser.parse(r.content)
        content = d.entries[0]["content"][0]["value"]
        assert "in_all" in content
        assert "only_in_detail" in content
