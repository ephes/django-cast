from datetime import datetime
from time import mktime

import feedparser
import pytest
import pytz
from django.http import Http404
from django.urls import reverse

from cast import appsettings
from cast.feeds import (
    AtomITunesFeedGenerator,
    ITunesElements,
    LatestEntriesFeed,
    PodcastFeed,
    PodcastIndexElements,
)
from cast.models import Post


def test_unknown_audio_format():
    pf = PodcastFeed()
    with pytest.raises(Http404):
        pf.set_audio_format("foobar")


class TestFeedCreation:
    pytestmark = pytest.mark.django_db

    def test_add_artwork_true(self, dummy_handler, podcast_with_artwork):
        ie = ITunesElements()
        ie.feed = {"title": "foobar", "link": "bar"}
        ie.add_artwork(podcast_with_artwork, dummy_handler)
        assert "itunes:image" in dummy_handler.aqe
        assert "image" in dummy_handler.se
        assert "image" in dummy_handler.ee

    def test_add_artwork_false(self, dummy_handler, podcast):
        ie = ITunesElements()
        ie.feed = {"title": "foobar", "link": "bar"}
        ie.add_artwork(podcast, dummy_handler)
        assert "itunes:image" not in dummy_handler.aqe
        assert "image" not in dummy_handler.se
        assert "image" not in dummy_handler.ee

    def test_itunes_categories(self, dummy_handler, podcast_with_itunes_categories):
        podcast = podcast_with_itunes_categories
        ie = ITunesElements()
        ie.add_itunes_categories(podcast, dummy_handler)
        assert dummy_handler.se["itunes:category"]["text"] == "foo"
        assert dummy_handler.aqe["itunes:category"][-1]["text"] == "baz"
        assert "itunes:category" in dummy_handler.ee


@pytest.fixture()
def use_django_repository():
    previous = appsettings.CAST_REPOSITORY
    appsettings.CAST_REPOSITORY = "django"
    yield appsettings.CAST_REPOSITORY
    appsettings.CAST_REPOSITORY = previous


class TestGeneratedFeeds:
    pytestmark = pytest.mark.django_db

    def test_get_latest_entries_feed(self, client, post, use_dummy_cache_backend):
        feed_url = reverse("cast:latest_entries_feed", kwargs={"slug": post.blog.slug})

        r = client.get(feed_url)
        assert r.status_code == 200

        content = r.content.decode("utf-8")
        assert "xml" in content
        assert post.title in content

    def test_get_latest_entries_feed_from_django_models(
        self, client, post, use_dummy_cache_backend, use_django_repository
    ):
        feed_url = reverse("cast:latest_entries_feed", kwargs={"slug": post.blog.slug})

        r = client.get(feed_url)
        assert r.status_code == 200

        content = r.content.decode("utf-8")
        assert "xml" in content
        assert post.title in content

    def test_get_link_if_no_repository(self, blog):
        feed_view = LatestEntriesFeed()
        feed_view.object = blog
        assert feed_view.link() == f"http://localhost/{blog.slug}/"

    def test_get_podcast_m4a_feed_rss(self, client, episode, use_dummy_cache_backend):
        feed_url = reverse(
            "cast:podcast_feed_rss",
            kwargs={"slug": episode.blog.slug, "audio_format": "m4a"},
        )

        r = client.get(feed_url)
        assert r.status_code == 200

        content = r.content.decode("utf-8")
        assert "rss" in content
        assert episode.title in content

    def test_get_podcast_m4a_feed_atom(self, client, episode):
        feed_url = reverse(
            "cast:podcast_feed_atom",
            kwargs={"slug": episode.blog.slug, "audio_format": "m4a"},
        )

        r = client.get(feed_url)
        assert r.status_code == 200

        content = r.content.decode("utf-8")
        assert "feed" in content
        assert episode.title in content

    def test_podcast_feed_contains_only_podcasts(self, client, post, episode, use_dummy_cache_backend):
        feed_url = reverse(
            "cast:podcast_feed_rss",
            kwargs={"slug": episode.blog.slug, "audio_format": "m4a"},
        )
        r = client.get(feed_url)
        assert r.status_code == 200

        d = feedparser.parse(r.content)
        assert len(d.entries) == 1
        assert Post.objects.live().descendant_of(episode.blog).count() == 1

    def test_podcast_feed_contains_visible_date_as_pubdate(
        self, client, podcast_episode_with_different_visible_date, use_dummy_cache_backend
    ):
        podcast_episode = podcast_episode_with_different_visible_date
        feed_url = reverse(
            "cast:podcast_feed_rss",
            kwargs={"slug": podcast_episode.podcast.slug, "audio_format": "m4a"},
        )

        r = client.get(feed_url)
        assert r.status_code == 200

        d = feedparser.parse(r.content)
        date_from_feed = datetime.fromtimestamp(mktime(d.entries[0]["published_parsed"]))
        date_from_feed = pytz.utc.localize(date_from_feed)
        assert date_from_feed == podcast_episode.visible_date

    def test_podcast_feed_contains_detail_information(self, client, episode):
        feed_url = reverse(
            "cast:podcast_feed_rss",
            kwargs={"slug": episode.podcast.slug, "audio_format": "m4a"},
        )

        r = client.get(feed_url)
        assert r.status_code == 200

        d = feedparser.parse(r.content)
        content = d.entries[0]["content"][0]["value"]
        assert "in_all" in content
        assert "only_in_detail" in content


def test_itunes_elements_add_root_elements_index_error(mocker):
    class MockedHandler:
        def addQuickElement(self, name, content=None, attrs=None):
            if name == "lastBuildDate":
                raise IndexError

        def startElement(self, name, attrs):
            pass

        def endElement(self, name):
            pass

    mocker.patch("cast.feeds.ITunesElements.add_artwork")
    mocker.patch("cast.feeds.rfc2822_date")
    atom_itunes_feed_generator = AtomITunesFeedGenerator("title", "link", "description")
    atom_itunes_feed_generator.feed = mocker.MagicMock()
    handler = MockedHandler()
    add_returned = atom_itunes_feed_generator.add_root_elements(handler)
    assert add_returned is None


def test_itunes_elements_add_item_elements_post_block(rf, mocker):
    mocker.patch("cast.feeds.Atom1Feed.add_item_elements")
    post = mocker.MagicMock()
    post.block = True
    post.podcast_audio.transcript = None  # no transcript
    handler = mocker.MagicMock()
    atom_itunes_feed_generator = AtomITunesFeedGenerator("title", "link", "description")
    request = rf.get("/")
    atom_itunes_feed_generator.request = request
    atom_itunes_feed_generator.add_item_elements(handler, {"post": post})
    handler.addQuickElement.assert_any_call("itunes:block", "yes")


def test_podcast_index_add_item_elements_post_block(rf, mocker):
    request = rf.get("/")
    mocker.patch("cast.feeds.Atom1Feed.add_item_elements")
    post = mocker.MagicMock()
    transcript_pk = 1
    post.podcast_audio.transcript.pk = transcript_pk
    post.podcast_audio.transcript.vtt = "foo"
    handler = mocker.MagicMock()

    vtt_url = reverse("cast:webvtt-transcript", kwargs={"pk": transcript_pk})
    vtt_url = request.build_absolute_uri(vtt_url)
    post.get_vtt_transcript_url.return_value = vtt_url
    json_url = reverse("cast:podcastindex-transcript-json", kwargs={"pk": transcript_pk})
    json_url = request.build_absolute_uri(json_url)
    post.get_podcastindex_transcript_url.return_value = json_url

    atom_itunes_feed_generator = AtomITunesFeedGenerator("title", "link", "description")
    atom_itunes_feed_generator.request = request
    atom_itunes_feed_generator.add_item_elements(handler, {"post": post})
    handler.addQuickElement.assert_any_call("podcast:transcript", attrs={"type": "text/vtt", "url": vtt_url})
    handler.addQuickElement.assert_any_call("podcast:transcript", attrs={"type": "application/json", "url": json_url})


def test_podcast_feed_categories_and_keywords():
    class MockedBlog:
        categories = True
        keywords = "foo, bar, baz"
        itunes_categories = "one,two,three"

    podcast_feed = PodcastFeed()

    blog = MockedBlog()
    # test categories -> first category
    categories = podcast_feed.categories(blog)
    assert categories == ("foo",)

    # itunes_categories -> split itunes_categories
    assert podcast_feed.itunes_categories(blog) == blog.itunes_categories.split(",")

    # item_keywords -> item.keywords
    assert podcast_feed.item_keywords(blog) == blog.keywords


def test_podcast_feed_item_description_repository_none(mocker):
    # given a podcast feed with repository None
    item = mocker.MagicMock()
    feed = PodcastFeed()
    feed.repository = None
    feed.request = mocker.MagicMock()
    # when calling item_description
    feed.item_description(item)
    # then item.get_description should be called, but not self.repository.get_post_detail_repository
    item.get_description.assert_called_once()


def test_podcsat_feed_link_repository_is_none(mocker):
    feed = PodcastFeed()
    feed.repository = None
    feed.object = mocker.MagicMock()
    feed.link()
    # make sure feed.object.get_full_url is called
    feed.object.get_full_url.assert_called_once()


def test_get_repository_uses_predefined_repository(mocker):
    repository = mocker.MagicMock()
    repository.used = False
    feed = LatestEntriesFeed(repository=repository)

    returned = feed.get_repository(mocker.MagicMock(), mocker.MagicMock())

    assert returned is repository


def test_cache_site_for_feed_without_site_id(settings, rf):
    settings.SITE_ID = None

    LatestEntriesFeed._cache_site_for_feed(rf.get("/"))


def test_cache_site_for_feed_uses_existing_cache(settings, rf):
    from django.contrib.sites import models as sites_models
    from django.contrib.sites.models import Site as DjangoSite

    site_id = 998
    settings.SITE_ID = site_id
    cache_backup = sites_models.SITE_CACHE.copy()
    sites_models.SITE_CACHE[site_id] = DjangoSite(id=site_id, domain="example.com", name="example.com")
    try:
        LatestEntriesFeed._cache_site_for_feed(rf.get("/"))
        assert sites_models.SITE_CACHE[site_id].domain == "example.com"
    finally:
        sites_models.SITE_CACHE.clear()
        sites_models.SITE_CACHE.update(cache_backup)


def test_cache_site_for_feed_without_get_host(settings):
    from django.contrib.sites import models as sites_models

    class DummyRequest:
        pass

    site_id = 999
    settings.SITE_ID = site_id
    cache_backup = sites_models.SITE_CACHE.copy()
    try:
        sites_models.SITE_CACHE.pop(site_id, None)
        LatestEntriesFeed._cache_site_for_feed(DummyRequest())
        assert sites_models.SITE_CACHE[site_id].domain == "localhost"
    finally:
        sites_models.SITE_CACHE.clear()
        sites_models.SITE_CACHE.update(cache_backup)


@pytest.mark.django_db
def test_latest_entries_feed_get_object_uses_repository_blog(rf, blog, mocker):
    repository = mocker.MagicMock()
    repository.used = False
    repository.blog = blog
    feed = LatestEntriesFeed(repository=repository)

    returned = feed.get_object(rf.get("/"), slug=blog.slug)

    assert returned is blog


@pytest.mark.django_db
def test_podcast_feed_get_object_uses_repository_blog(rf, podcast, mocker):
    repository = mocker.MagicMock()
    repository.used = False
    repository.blog = podcast
    feed = PodcastFeed(repository=repository)

    returned = feed.get_object(rf.get("/"), slug=podcast.slug, audio_format="m4a")

    assert returned is podcast


def test_podcast_index_elements_catch_no_super_add_item_elements(mocker):
    elements = PodcastIndexElements()
    elements.request = mocker.MagicMock()
    handler = mocker.MagicMock()
    result = elements.add_item_elements(handler, {"post": mocker.MagicMock()})
    assert result is None
