import pytest
import feedparser

from django.urls import reverse
from django.http import Http404

from cast.models import Post
from cast.feeds import ITunesElements, PodcastFeed


class TestFeedCreation:
    @pytest.mark.django_db
    def test_add_artwork_true(self, dummy_handler, blog_with_artwork):
        ie = ITunesElements()
        ie.feed = {"title": "foobar", "link": "bar"}
        ie.add_artwork(blog_with_artwork, dummy_handler)
        assert "itunes:image" in dummy_handler.aqe
        assert "image" in dummy_handler.se
        assert "image" in dummy_handler.ee

    @pytest.mark.django_db
    def test_add_artwork_false(self, dummy_handler, blog):
        ie = ITunesElements()
        ie.feed = {"title": "foobar", "link": "bar"}
        ie.add_artwork(blog, dummy_handler)
        assert "itunes:image" not in dummy_handler.aqe
        assert "image" not in dummy_handler.se
        assert "image" not in dummy_handler.ee

    def test_unknown_audio_format(self):
        pf = PodcastFeed()
        with pytest.raises(Http404):
            pf.set_audio_format("foobar")


class TestGeneratedFeeds:
    @pytest.mark.django_db
    def test_get_latest_entries_feed(self, client, post):
        feed_url = reverse("cast:latest_entries_feed", kwargs={"slug": post.blog.slug})

        r = client.get(feed_url)
        assert r.status_code == 200

        content = r.content.decode("utf-8")
        assert "xml" in content
        assert post.title in content

    @pytest.mark.django_db
    def test_get_podcast_m4a_feed_rss(self, client, podcast_episode):
        feed_url = reverse(
            "cast:podcast_feed_rss",
            kwargs={"slug": podcast_episode.blog.slug, "audio_format": "m4a"},
        )

        r = client.get(feed_url)
        assert r.status_code == 200

        content = r.content.decode("utf-8")
        assert "rss" in content
        assert podcast_episode.title in content

    @pytest.mark.django_db
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

    @pytest.mark.django_db
    def test_podcast_feed_contains_only_podcasts(self, client, post, podcast_episode):
        feed_url = reverse(
            "cast:podcast_feed_rss",
            kwargs={"slug": podcast_episode.blog.slug, "audio_format": "m4a"},
        )

        r = client.get(feed_url)
        assert r.status_code == 200

        d = feedparser.parse(r.content)
        assert len(d.entries) == 1
        assert Post.objects.filter(blog=podcast_episode.blog).count() == 2
