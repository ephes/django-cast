from datetime import datetime
from types import SimpleNamespace
from time import mktime
from xml.etree import ElementTree

import feedparser
import pytest
import pytz
from django.http import Http404
from django.urls import reverse
from wagtail.models import PageViewRestriction

import django

from cast import appsettings
from cast.devdata import create_transcript
from cast.feeds import (
    AtomITunesFeedGenerator,
    AtomPodcastFeed,
    ITunesElements,
    LatestEntriesAtomFeed,
    LatestEntriesFeed,
    PodcastFeed,
    PodcastIndexElements,
    RssPodcastFeed,
    _feed_stylesheets,
    _episode_season_data,
    _is_itunes_type,
    _is_positive_integer,
)
from cast.models import Contributor, ContributorLink, Episode, EpisodeContributor, Podcast, Season, Post


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

    @pytest.mark.parametrize("repository", ["default", "django"])
    def test_get_latest_entries_feed_excludes_restricted_posts(
        self, client, post, use_dummy_cache_backend, repository
    ):
        previous_repository = appsettings.CAST_REPOSITORY
        appsettings.CAST_REPOSITORY = repository
        PageViewRestriction.objects.create(page=post, restriction_type=PageViewRestriction.LOGIN)
        feed_url = reverse("cast:latest_entries_feed", kwargs={"slug": post.blog.slug})
        try:
            response = client.get(feed_url)
        finally:
            appsettings.CAST_REPOSITORY = previous_repository

        assert response.status_code == 200
        assert post.title not in response.content.decode("utf-8")

    def test_get_latest_entries_feed_escapes_special_chars_in_title(self, client, post, use_dummy_cache_backend):
        post.title = "A & B < C"
        post.save()
        feed_url = reverse("cast:latest_entries_feed", kwargs={"slug": post.blog.slug})

        response = client.get(feed_url)

        assert response.status_code == 200
        xml_content = response.content.decode("utf-8")
        ElementTree.fromstring(xml_content)
        assert "A &amp; B &lt; C" in xml_content
        assert "A & B < C" not in xml_content

    def test_get_latest_entries_atom_feed(self, client, post, use_dummy_cache_backend):
        feed_url = reverse("cast:latest_entries_atom_feed", kwargs={"slug": post.blog.slug})

        r = client.get(feed_url)
        assert r.status_code == 200

        content = r.content.decode("utf-8")
        assert "xml" in content
        assert post.title in content

    def test_get_latest_entries_atom_feed_from_django_models(
        self, client, post, use_dummy_cache_backend, use_django_repository
    ):
        feed_url = reverse("cast:latest_entries_atom_feed", kwargs={"slug": post.blog.slug})

        r = client.get(feed_url)
        assert r.status_code == 200

        content = r.content.decode("utf-8")
        assert "xml" in content
        assert post.title in content

    def test_latest_entries_rss_feed_item_has_pubdate_and_uuid_guid(self, client, post, use_dummy_cache_backend):
        feed_url = reverse("cast:latest_entries_feed", kwargs={"slug": post.blog.slug})

        response = client.get(feed_url)

        assert response.status_code == 200
        root = ElementTree.fromstring(response.content.decode("utf-8"))
        item = root.find("./channel/item")
        assert item is not None
        assert item.findtext("pubDate") is not None
        guid = item.find("guid")
        assert guid is not None
        assert guid.text == str(post.uuid)
        assert guid.attrib == {"isPermaLink": "false"}

    def test_latest_entries_atom_feed_entry_has_updated_and_uuid_id(self, client, post, use_dummy_cache_backend):
        post.last_published_at = post.visible_date
        post.save(update_fields=["last_published_at"])
        feed_url = reverse("cast:latest_entries_atom_feed", kwargs={"slug": post.blog.slug})

        response = client.get(feed_url)

        assert response.status_code == 200
        root = ElementTree.fromstring(response.content.decode("utf-8"))
        namespace = {"atom": "http://www.w3.org/2005/Atom"}
        entry = root.find("atom:entry", namespace)
        assert entry is not None
        assert entry.findtext("atom:updated", namespaces=namespace) is not None
        assert entry.findtext("atom:id", namespaces=namespace) == str(post.uuid)

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

    @pytest.mark.parametrize("repository", ["default", "django"])
    def test_get_podcast_feed_excludes_restricted_episodes(self, client, episode, use_dummy_cache_backend, repository):
        previous_repository = appsettings.CAST_REPOSITORY
        appsettings.CAST_REPOSITORY = repository
        PageViewRestriction.objects.create(page=episode, restriction_type=PageViewRestriction.LOGIN)
        feed_url = reverse(
            "cast:podcast_feed_rss",
            kwargs={"slug": episode.blog.slug, "audio_format": "m4a"},
        )
        try:
            response = client.get(feed_url)
        finally:
            appsettings.CAST_REPOSITORY = previous_repository

        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert episode.title not in content
        assert episode.podcast_audio.m4a.url not in content

    def test_podcast_feed_rss_uses_subtitle(self, client, episode, use_dummy_cache_backend):
        feed_url = reverse(
            "cast:podcast_feed_rss",
            kwargs={"slug": episode.podcast.slug, "audio_format": "m4a"},
        )

        r = client.get(feed_url)
        assert r.status_code == 200

        content = r.content.decode("utf-8")
        assert f"<itunes:subtitle>{episode.podcast.subtitle}</itunes:subtitle>" in content

    def test_podcast_feed_atom_uses_subtitle(self, client, episode, use_dummy_cache_backend):
        feed_url = reverse(
            "cast:podcast_feed_atom",
            kwargs={"slug": episode.podcast.slug, "audio_format": "m4a"},
        )

        r = client.get(feed_url)
        assert r.status_code == 200

        content = r.content.decode("utf-8")
        assert f"<itunes:subtitle>{episode.podcast.subtitle}</itunes:subtitle>" in content

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

    def test_podcast_feed_from_django_models_includes_transcript(
        self, client, episode, use_dummy_cache_backend, use_django_repository
    ):
        create_transcript(audio=episode.podcast_audio)
        feed_url = reverse(
            "cast:podcast_feed_rss",
            kwargs={"slug": episode.podcast.slug, "audio_format": "m4a"},
        )
        r = client.get(feed_url)
        assert r.status_code == 200
        content = r.content.decode("utf-8")
        assert "podcast:transcript" in content

    def test_podcast_feed_includes_visible_episode_contributors(self, client, episode, image, use_dummy_cache_backend):
        host = Contributor.objects.create(display_name="Episode Host", slug="episode-host", avatar=image)
        host_link = ContributorLink.objects.create(
            contributor=host,
            service=ContributorLink.SERVICE_WEBSITE,
            url="https://example.com/host",
            sort_order=0,
        )
        guest = Contributor.objects.create(display_name="Episode Guest", slug="episode-guest")
        hidden = Contributor.objects.create(display_name="Hidden Guest", slug="hidden-guest", visible=False)
        EpisodeContributor.objects.create(
            episode=episode,
            contributor=host,
            role=EpisodeContributor.ROLE_HOST,
            link=host_link,
            sort_order=0,
        )
        EpisodeContributor.objects.create(
            episode=episode,
            contributor=guest,
            role=EpisodeContributor.ROLE_GUEST,
            sort_order=1,
        )
        EpisodeContributor.objects.create(
            episode=episode,
            contributor=hidden,
            role=EpisodeContributor.ROLE_GUEST,
            sort_order=2,
        )
        feed_url = reverse(
            "cast:podcast_feed_rss",
            kwargs={"slug": episode.podcast.slug, "audio_format": "m4a"},
        )

        response = client.get(feed_url)

        assert response.status_code == 200
        content = response.content.decode("utf-8")
        root = ElementTree.fromstring(content)
        namespace = {"podcast": "https://podcastindex.org/namespace/1.0/"}
        people = root.findall(".//podcast:person", namespace)
        assert [person.text for person in people] == ["Episode Host", "Episode Guest"]
        assert people[0].attrib["role"] == "host"
        assert people[0].attrib["href"] == "https://example.com/host"
        assert people[0].attrib["img"].startswith("http://testserver/media/")
        assert people[1].attrib == {"role": "guest"}
        assert "Hidden Guest" not in content

    def test_podcast_feed_omits_blank_publishing_metadata(self, client, episode, use_dummy_cache_backend):
        feed_url = reverse(
            "cast:podcast_feed_rss",
            kwargs={"slug": episode.podcast.slug, "audio_format": "m4a"},
        )

        response = client.get(feed_url)

        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert "<itunes:type>" not in content
        assert "<itunes:episode>" not in content
        assert "<itunes:season>" not in content
        assert "<itunes:episodeType>" not in content
        assert "<podcast:episode>" not in content
        assert "<podcast:season" not in content

    @pytest.mark.parametrize("itunes_type", ["episodic", "serial"])
    def test_podcast_feed_includes_explicit_channel_type(self, client, episode, use_dummy_cache_backend, itunes_type):
        podcast = episode.podcast
        podcast.itunes_type = itunes_type
        podcast.save(update_fields=["itunes_type"])
        feed_url = reverse(
            "cast:podcast_feed_rss",
            kwargs={"slug": podcast.slug, "audio_format": "m4a"},
        )

        response = client.get(feed_url)

        assert response.status_code == 200
        root = ElementTree.fromstring(response.content.decode("utf-8"))
        namespace = {"itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd"}
        channel = root.find("./channel")
        assert channel is not None
        assert channel.findtext("itunes:type", namespaces=namespace) == itunes_type

    def test_podcast_atom_feed_includes_explicit_channel_type(self, client, episode, use_dummy_cache_backend):
        podcast = episode.podcast
        podcast.itunes_type = Podcast.ItunesType.SERIAL
        podcast.save(update_fields=["itunes_type"])
        feed_url = reverse(
            "cast:podcast_feed_atom",
            kwargs={"slug": podcast.slug, "audio_format": "m4a"},
        )

        response = client.get(feed_url)

        assert response.status_code == 200
        root = ElementTree.fromstring(response.content.decode("utf-8"))
        namespace = {"itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd"}
        assert root.findtext("itunes:type", namespaces=namespace) == Podcast.ItunesType.SERIAL

    def test_podcast_feed_suppresses_invalid_channel_type(self, client, episode, use_dummy_cache_backend):
        podcast = episode.podcast
        type(podcast).objects.filter(pk=podcast.pk).update(itunes_type="chronological")
        feed_url = reverse(
            "cast:podcast_feed_rss",
            kwargs={"slug": podcast.slug, "audio_format": "m4a"},
        )

        response = client.get(feed_url)

        assert response.status_code == 200
        assert "<itunes:type>" not in response.content.decode("utf-8")

    def test_podcast_feed_includes_publishing_metadata(self, client, episode, use_dummy_cache_backend):
        season = Season.objects.create(podcast=episode.podcast, number=2, name="Launch")
        episode.episode_number = 7
        episode.episode_type = Episode.EpisodeType.TRAILER
        episode.season = season
        episode.save(update_fields=["episode_number", "episode_type", "season"])
        feed_url = reverse(
            "cast:podcast_feed_rss",
            kwargs={"slug": episode.podcast.slug, "audio_format": "m4a"},
        )

        response = client.get(feed_url)

        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert content.count("xmlns:podcast=") == 1
        root = ElementTree.fromstring(content)
        namespace = {
            "itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd",
            "podcast": "https://podcastindex.org/namespace/1.0/",
        }
        item = root.find("./channel/item")
        assert item is not None
        assert item.findtext("itunes:episode", namespaces=namespace) == "7"
        assert item.findtext("itunes:season", namespaces=namespace) == "2"
        assert item.findtext("itunes:episodeType", namespaces=namespace) == "trailer"
        assert item.findtext("podcast:episode", namespaces=namespace) == "7"
        podcast_season = item.find("podcast:season", namespace)
        assert podcast_season is not None
        assert podcast_season.text == "2"
        assert podcast_season.attrib == {"name": "Launch"}
        guid = item.find("guid")
        assert guid is not None
        assert guid.text == str(episode.uuid)
        assert guid.attrib == {"isPermaLink": "false"}

    def test_podcast_feed_includes_unnamed_season_without_name_attribute(
        self, client, episode, use_dummy_cache_backend
    ):
        season = Season.objects.create(podcast=episode.podcast, number=1)
        episode.season = season
        episode.save(update_fields=["season"])
        feed_url = reverse(
            "cast:podcast_feed_rss",
            kwargs={"slug": episode.podcast.slug, "audio_format": "m4a"},
        )

        response = client.get(feed_url)

        assert response.status_code == 200
        root = ElementTree.fromstring(response.content.decode("utf-8"))
        namespace = {"podcast": "https://podcastindex.org/namespace/1.0/"}
        podcast_season = root.find("./channel/item/podcast:season", namespace)
        assert podcast_season is not None
        assert podcast_season.text == "1"
        assert podcast_season.attrib == {}

    @pytest.mark.parametrize("episode_type", ["full", "trailer", "bonus"])
    def test_podcast_feed_includes_explicit_episode_type(self, client, episode, use_dummy_cache_backend, episode_type):
        episode.episode_type = episode_type
        episode.save(update_fields=["episode_type"])
        feed_url = reverse(
            "cast:podcast_feed_rss",
            kwargs={"slug": episode.podcast.slug, "audio_format": "m4a"},
        )

        response = client.get(feed_url)

        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert f"<itunes:episodeType>{episode_type}</itunes:episodeType>" in content

    def test_podcast_feed_suppresses_invalid_stored_numbers(self, client, episode, use_dummy_cache_backend):
        season = Season.objects.create(podcast=episode.podcast, number=1, name="Launch")
        episode.season = season
        episode.save(update_fields=["season"])
        Episode.objects.filter(pk=episode.pk).update(episode_number=0, episode_type="preview")
        Season.objects.filter(pk=season.pk).update(number=0)
        feed_url = reverse(
            "cast:podcast_feed_rss",
            kwargs={"slug": episode.podcast.slug, "audio_format": "m4a"},
        )

        response = client.get(feed_url)

        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert "<itunes:episode>" not in content
        assert "<itunes:season>" not in content
        assert "<itunes:episodeType>" not in content
        assert "<podcast:episode>" not in content
        assert "<podcast:season" not in content


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (1, True),
        (0, False),
        (-1, False),
        (True, False),
        ("1", False),
        (None, False),
    ],
)
def test_is_positive_integer(value, expected):
    assert _is_positive_integer(value) is expected


def test_episode_season_data():
    assert _episode_season_data(SimpleNamespace(season=None)) == (None, "")
    assert _episode_season_data(SimpleNamespace(season=SimpleNamespace(number=0, name="Invalid"))) == (None, "")
    assert _episode_season_data(SimpleNamespace(season=SimpleNamespace(number=1, name="Launch"))) == (1, "Launch")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("episodic", True),
        ("serial", True),
        ("", False),
        ("chronological", False),
        (None, False),
    ],
)
def test_is_itunes_type(value, expected):
    assert _is_itunes_type(value) is expected


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
        keywords = "foo, bar, baz"
        itunes_categories = "one,two,three"

    podcast_feed = PodcastFeed()

    blog = MockedBlog()
    # test categories -> first keyword, stripped
    categories = podcast_feed.categories(blog)
    assert categories == ("foo",)

    # itunes_categories -> split itunes_categories
    assert podcast_feed.itunes_categories(blog) == blog.itunes_categories.split(",")

    # item_keywords -> item.keywords
    assert podcast_feed.item_keywords(blog) == blog.keywords


def test_podcast_feed_categories_empty_keywords():
    class MockedBlog:
        keywords = ""

    podcast_feed = PodcastFeed()

    assert podcast_feed.categories(MockedBlog()) == ()


@pytest.mark.django_db
def test_podcast_feed_rss_renders_first_keyword_as_category(client, episode, use_dummy_cache_backend):
    podcast = episode.podcast
    podcast.keywords = "python,django"
    podcast.save(update_fields=["keywords"])
    feed_url = reverse(
        "cast:podcast_feed_rss",
        kwargs={"slug": podcast.slug, "audio_format": "m4a"},
    )

    response = client.get(feed_url)

    assert response.status_code == 200
    root = ElementTree.fromstring(response.content.decode("utf-8"))
    channel = root.find("./channel")
    assert channel is not None
    assert channel.findtext("category") == "python"


@pytest.mark.django_db
def test_podcast_feed_rss_omits_category_when_keywords_blank(client, episode, use_dummy_cache_backend):
    podcast = episode.podcast
    podcast.keywords = ""
    podcast.save(update_fields=["keywords"])
    feed_url = reverse(
        "cast:podcast_feed_rss",
        kwargs={"slug": podcast.slug, "audio_format": "m4a"},
    )

    response = client.get(feed_url)

    assert response.status_code == 200
    root = ElementTree.fromstring(response.content.decode("utf-8"))
    channel = root.find("./channel")
    assert channel is not None
    assert channel.find("category") is None


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


def test_latest_entries_feed_item_link_repository_is_none(mocker):
    item = mocker.MagicMock()
    item.get_full_url.return_value = "http://testserver/post/"
    feed = LatestEntriesFeed(repository=None)

    assert feed.item_link(item) == "http://testserver/post/"
    item.get_full_url.assert_called_once()


def test_podcast_feed_item_link_repository_is_none(mocker):
    item = mocker.MagicMock()
    item.get_full_url.return_value = "http://testserver/episode/"
    feed = PodcastFeed(repository=None)

    assert feed.item_link(item) == "http://testserver/episode/"
    item.get_full_url.assert_called_once()


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


class TestFeedStylesheets:
    def test_feed_stylesheets_set_on_django_52_plus(self):
        if django.VERSION >= (5, 2):
            assert _feed_stylesheets is not None
            assert len(_feed_stylesheets) == 1
            assert _feed_stylesheets[0].url == "/static/cast/feed-style.xsl"
        else:
            assert _feed_stylesheets is None

    def test_latest_entries_feed_has_stylesheets(self):
        assert LatestEntriesFeed.stylesheets is _feed_stylesheets

    def test_latest_entries_atom_feed_has_stylesheets(self):
        assert LatestEntriesAtomFeed.stylesheets is _feed_stylesheets

    def test_atom_podcast_feed_has_stylesheets(self):
        assert AtomPodcastFeed.stylesheets is _feed_stylesheets

    def test_rss_podcast_feed_has_stylesheets(self):
        assert RssPodcastFeed.stylesheets is _feed_stylesheets

    @pytest.mark.django_db
    def test_rss_feed_contains_xsl_processing_instruction(self, client, post, use_dummy_cache_backend):
        if django.VERSION < (5, 2):
            pytest.skip("Stylesheet support requires Django 5.2+")
        feed_url = reverse("cast:latest_entries_feed", kwargs={"slug": post.blog.slug})
        r = client.get(feed_url)
        assert r.status_code == 200
        content = r.content.decode("utf-8")
        assert 'href="/static/cast/feed-style.xsl"' in content

    @pytest.mark.django_db
    def test_atom_blog_feed_contains_xsl_processing_instruction(self, client, post, use_dummy_cache_backend):
        if django.VERSION < (5, 2):
            pytest.skip("Stylesheet support requires Django 5.2+")
        feed_url = reverse("cast:latest_entries_atom_feed", kwargs={"slug": post.blog.slug})
        r = client.get(feed_url)
        assert r.status_code == 200
        content = r.content.decode("utf-8")
        assert 'href="/static/cast/feed-style.xsl"' in content

    @pytest.mark.django_db
    def test_podcast_rss_feed_contains_xsl_processing_instruction(self, client, episode, use_dummy_cache_backend):
        if django.VERSION < (5, 2):
            pytest.skip("Stylesheet support requires Django 5.2+")
        feed_url = reverse(
            "cast:podcast_feed_rss",
            kwargs={"slug": episode.blog.slug, "audio_format": "m4a"},
        )
        r = client.get(feed_url)
        assert r.status_code == 200
        content = r.content.decode("utf-8")
        assert 'href="/static/cast/feed-style.xsl"' in content

    @pytest.mark.django_db
    def test_podcast_atom_feed_contains_xsl_processing_instruction(self, client, episode):
        if django.VERSION < (5, 2):
            pytest.skip("Stylesheet support requires Django 5.2+")
        feed_url = reverse(
            "cast:podcast_feed_atom",
            kwargs={"slug": episode.blog.slug, "audio_format": "m4a"},
        )
        r = client.get(feed_url)
        assert r.status_code == 200
        content = r.content.decode("utf-8")
        assert 'href="/static/cast/feed-style.xsl"' in content


def test_podcast_index_elements_catch_no_super_add_item_elements(mocker):
    elements = PodcastIndexElements()
    elements.request = mocker.MagicMock()
    handler = mocker.MagicMock()
    result = elements.add_item_elements(handler, {"post": mocker.MagicMock()})
    assert result is None


def test_podcast_index_person_attributes_omit_unknown_role(rf):
    assignment = SimpleNamespace(role="producer", href="", get_avatar_rendition_url=lambda _request: "")

    assert PodcastIndexElements.get_person_attributes(assignment, rf.get("/")) == {}
