from django.test import override_settings
from django.urls import reverse

from cast import appsettings
from cast.models import Audio
from cast.views.feed import _resolve_feed_detail_template, get_podcast_feed_urls

from .factories import BlogFactory, EpisodeFactory, PodcastFactory, PostFactory
from .multisite_helpers import create_site_root


class TestFeedDetailForBlog:
    def test_feed_detail_returns_200(self, client, blog):
        url = reverse("cast:feed_detail", kwargs={"slug": blog.slug})
        response = client.get(url)
        assert response.status_code == 200

    def test_feed_detail_contains_blog_rss_url(self, client, blog):
        url = reverse("cast:feed_detail", kwargs={"slug": blog.slug})
        response = client.get(url)
        content = response.content.decode()
        rss_url = reverse("cast:latest_entries_feed", kwargs={"slug": blog.slug})
        assert rss_url in content

    def test_feed_detail_contains_blog_atom_url(self, client, blog):
        url = reverse("cast:feed_detail", kwargs={"slug": blog.slug})
        response = client.get(url)
        content = response.content.decode()
        atom_url = reverse("cast:latest_entries_atom_feed", kwargs={"slug": blog.slug})
        assert atom_url in content

    def test_feed_detail_blog_has_no_podcast_content(self, client, blog):
        url = reverse("cast:feed_detail", kwargs={"slug": blog.slug})
        response = client.get(url)
        content = response.content.decode()
        assert "Podcast Feeds" not in content


class TestFeedDetailForPodcast:
    def test_feed_detail_returns_200(self, client, podcast):
        url = reverse("cast:feed_detail", kwargs={"slug": podcast.slug})
        response = client.get(url)
        assert response.status_code == 200

    def test_feed_detail_contains_all_format_feed_urls(self, client, podcast):
        url = reverse("cast:feed_detail", kwargs={"slug": podcast.slug})
        response = client.get(url)
        content = response.content.decode()
        for audio_format in Audio.audio_formats:
            rss_url = reverse("cast:podcast_feed_rss", kwargs={"slug": podcast.slug, "audio_format": audio_format})
            atom_url = reverse("cast:podcast_feed_atom", kwargs={"slug": podcast.slug, "audio_format": audio_format})
            assert rss_url in content
            assert atom_url in content

    def test_feed_detail_with_apple_podcasts(self, client, podcast, monkeypatch):
        apple_url = "https://podcasts.apple.com/podcast/test"
        monkeypatch.setattr(
            appsettings,
            "CAST_FOLLOW_LINKS",
            {"apple_podcasts": apple_url},
        )
        url = reverse("cast:feed_detail", kwargs={"slug": podcast.slug})
        response = client.get(url)
        content = response.content.decode()
        assert apple_url in content

    def test_feed_detail_without_apple_podcasts(self, client, podcast, monkeypatch):
        monkeypatch.setattr(appsettings, "CAST_FOLLOW_LINKS", {})
        url = reverse("cast:feed_detail", kwargs={"slug": podcast.slug})
        response = client.get(url)
        content = response.content.decode()
        assert "Apple Podcasts" not in content

    def test_feed_detail_with_spotify(self, client, podcast, monkeypatch):
        spotify_url = "https://open.spotify.com/show/test"
        monkeypatch.setattr(
            appsettings,
            "CAST_FOLLOW_LINKS",
            {"spotify": spotify_url},
        )
        url = reverse("cast:feed_detail", kwargs={"slug": podcast.slug})
        response = client.get(url)
        content = response.content.decode()
        assert spotify_url in content

    def test_feed_detail_without_spotify(self, client, podcast, monkeypatch):
        monkeypatch.setattr(appsettings, "CAST_FOLLOW_LINKS", {})
        url = reverse("cast:feed_detail", kwargs={"slug": podcast.slug})
        response = client.get(url)
        content = response.content.decode()
        assert "Spotify" not in content

    def test_feed_detail_with_youtube(self, client, podcast, monkeypatch):
        youtube_url = "https://www.youtube.com/@test"
        monkeypatch.setattr(
            appsettings,
            "CAST_FOLLOW_LINKS",
            {"youtube": youtube_url},
        )
        url = reverse("cast:feed_detail", kwargs={"slug": podcast.slug})
        response = client.get(url)
        content = response.content.decode()
        assert youtube_url in content

    def test_feed_detail_without_youtube(self, client, podcast, monkeypatch):
        monkeypatch.setattr(appsettings, "CAST_FOLLOW_LINKS", {})
        url = reverse("cast:feed_detail", kwargs={"slug": podcast.slug})
        response = client.get(url)
        content = response.content.decode()
        assert "YouTube" not in content


class TestFeedDetail404:
    def test_nonexistent_slug_returns_404(self, client, site):
        url = reverse("cast:feed_detail", kwargs={"slug": "nonexistent"})
        response = client.get(url)
        assert response.status_code == 404


class TestFeedDetailRoutingNonConflict:
    """Verify feed detail page and XML feed routes don't shadow each other."""

    def test_feed_xml_still_reachable(self, client, blog):
        rss_url = reverse("cast:latest_entries_feed", kwargs={"slug": blog.slug})
        response = client.get(rss_url)
        assert response.status_code == 200
        assert "xml" in response["Content-Type"]

    def test_feed_detail_returns_html(self, client, blog):
        url = reverse("cast:feed_detail", kwargs={"slug": blog.slug})
        response = client.get(url)
        assert response.status_code == 200
        assert "text/html" in response["Content-Type"]

    def test_feed_detail_uses_current_site_for_duplicate_blog_slug(self, client, user):
        site1, site1_root = create_site_root(
            owner=user, hostname="feed-site1.local", slug="feed-site1-root", title="Feed Site 1"
        )
        _site2, site2_root = create_site_root(
            owner=user, hostname="feed-site2.local", slug="feed-site2-root", title="Feed Site 2"
        )
        blog1 = BlogFactory(owner=user, title="Site 1 Blog", slug="shared-feed", parent=site1_root)
        BlogFactory(owner=user, title="Site 2 Blog", slug="shared-feed", parent=site2_root)

        url = reverse("cast:feed_detail", kwargs={"slug": blog1.slug})
        with override_settings(ALLOWED_HOSTS=["testserver", site1.hostname, "feed-site2.local"]):
            response = client.get(url, HTTP_HOST=site1.hostname)

        assert response.status_code == 200
        content = response.content.decode()
        assert "Site 1 Blog" in content
        assert "Site 2 Blog" not in content

    def test_feed_xml_uses_current_site_for_duplicate_blog_slug(self, client, user, body):
        site1, site1_root = create_site_root(
            owner=user, hostname="feed-xml1.local", slug="feed-xml1-root", title="Feed XML 1"
        )
        _site2, site2_root = create_site_root(
            owner=user, hostname="feed-xml2.local", slug="feed-xml2-root", title="Feed XML 2"
        )
        blog1 = BlogFactory(owner=user, title="Site 1 Blog", slug="shared-feed-xml", parent=site1_root)
        blog2 = BlogFactory(owner=user, title="Site 2 Blog", slug="shared-feed-xml", parent=site2_root)
        PostFactory(owner=user, title="Site 1 Post", slug="site-1-post", body=body, parent=blog1)
        PostFactory(owner=user, title="Site 2 Post", slug="site-2-post", body=body, parent=blog2)

        url = reverse("cast:latest_entries_feed", kwargs={"slug": blog1.slug})
        with override_settings(ALLOWED_HOSTS=["testserver", site1.hostname, "feed-xml2.local"]):
            response = client.get(url, HTTP_HOST=site1.hostname)

        assert response.status_code == 200
        content = response.content.decode()
        assert "Site 1 Post" in content
        assert "Site 2 Post" not in content

    def test_podcast_feed_uses_current_site_for_duplicate_podcast_slug(self, client, user, audio, body):
        site1, site1_root = create_site_root(
            owner=user, hostname="podcast-feed1.local", slug="podcast-feed1-root", title="Podcast Feed 1"
        )
        _site2, site2_root = create_site_root(
            owner=user, hostname="podcast-feed2.local", slug="podcast-feed2-root", title="Podcast Feed 2"
        )
        podcast1 = PodcastFactory(owner=user, title="Podcast 1", slug="shared-podcast-feed", parent=site1_root)
        podcast2 = PodcastFactory(owner=user, title="Podcast 2", slug="shared-podcast-feed", parent=site2_root)
        EpisodeFactory(
            owner=user, title="Episode 1", slug="episode-1", body=body, parent=podcast1, podcast_audio=audio
        )
        EpisodeFactory(
            owner=user, title="Episode 2", slug="episode-2", body=body, parent=podcast2, podcast_audio=audio
        )

        url = reverse("cast:podcast_feed_rss", kwargs={"slug": podcast1.slug, "audio_format": "m4a"})
        with override_settings(ALLOWED_HOSTS=["testserver", site1.hostname, "podcast-feed2.local"]):
            response = client.get(url, HTTP_HOST=site1.hostname)

        assert response.status_code == 200
        content = response.content.decode()
        assert "Episode 1" in content
        assert "Episode 2" not in content


class TestFeedDetailTemplateSelection:
    def test_uses_plain_template_via_query_param(self, client, blog):
        url = reverse("cast:feed_detail", kwargs={"slug": blog.slug})
        response = client.get(url, {"template_base_dir": "plain"})
        assert response.status_code == 200
        assert "cast/plain/feed_detail.html" in [t.name for t in response.templates]

    def test_uses_bootstrap4_template_via_query_param(self, client, blog):
        url = reverse("cast:feed_detail", kwargs={"slug": blog.slug})
        response = client.get(url, {"template_base_dir": "bootstrap4"})
        assert response.status_code == 200
        assert "cast/bootstrap4/feed_detail.html" in [t.name for t in response.templates]


class TestFeedDetailTemplateFallback:
    def test_resolve_falls_back_for_missing_theme(self):
        result = _resolve_feed_detail_template("totally_bogus_theme")
        assert "feed_detail.html" in result
        assert "totally_bogus_theme" not in result

    def test_resolve_returns_known_theme_directly(self):
        result = _resolve_feed_detail_template("plain")
        assert result == "cast/plain/feed_detail.html"

    def test_resolve_returns_bootstrap4_directly(self):
        result = _resolve_feed_detail_template("bootstrap4")
        assert result == "cast/bootstrap4/feed_detail.html"


class TestGetPodcastFeedUrls:
    def test_returns_correct_structure(self, podcast):
        feeds = get_podcast_feed_urls(podcast)
        assert len(feeds) == len(Audio.audio_formats)
        for feed in feeds:
            assert "format" in feed
            assert "format_label" in feed
            assert "rss_url" in feed
            assert "atom_url" in feed
            assert feed["format"] in Audio.audio_formats
            assert feed["format_label"] == feed["format"].upper()
            assert "rss.xml" in feed["rss_url"]
            assert "atom.xml" in feed["atom_url"]
