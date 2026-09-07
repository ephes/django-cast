from datetime import datetime, time
from types import SimpleNamespace
from time import mktime
from urllib.parse import urlparse
from xml.etree import ElementTree

import feedparser
import pytest
import pytz
from django.conf import settings as django_settings
from django.contrib.sites import models as sites_models
from django.contrib.sites.models import Site as DjangoSite
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured
from django.http import Http404
from django.urls import resolve, reverse
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
    PSC_NAMESPACE,
    PodcastFeed,
    PodcastIndexElements,
    RssPodcastFeed,
    _episode_season_data,
    _feed_stylesheets,
    _is_itunes_type,
    _is_positive_integer,
    _psc_start,
)
from cast.models import ChapterMark, Contributor, ContributorLink, Episode, EpisodeContributor, Podcast, Season, Post
from cast.models.repository import FeedContext
from tests.factories import BlogFactory, EpisodeFactory


RSS_CHAPTERLESS_ROOT_BASELINE = (
    '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom" '
    'xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd" '
    'xmlns:podcast="https://podcastindex.org/namespace/1.0/">'
)
ATOM_CHAPTERLESS_ROOT_BASELINE = (
    '<feed xml:lang="en-us" xmlns="http://www.w3.org/2005/Atom" '
    'xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd" '
    'xmlns:podcast="https://podcastindex.org/namespace/1.0/">'
)


def _root_start_tag(content: str, root_name: str) -> str:
    start = content.index(f"<{root_name}")
    end = content.index(">", start) + 1
    return content[start:end]


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

    @pytest.mark.parametrize(
        ("route_name", "is_podcast"),
        [
            ("cast:latest_entries_feed", False),
            ("cast:latest_entries_atom_feed", False),
            ("cast:feed_detail", False),
            ("cast:podcast_feed_rss", True),
            ("cast:podcast_feed_atom", True),
        ],
    )
    @pytest.mark.parametrize(
        "restriction_type",
        [PageViewRestriction.LOGIN, PageViewRestriction.PASSWORD, PageViewRestriction.GROUPS],
    )
    @pytest.mark.parametrize("inherited", [False, True], ids=["direct", "inherited"])
    def test_feed_roots_require_unrestricted_public_page(
        self,
        client,
        blog,
        podcast,
        site,
        use_dummy_cache_backend,
        route_name,
        is_podcast,
        restriction_type,
        inherited,
    ):
        feed_root = podcast if is_podcast else blog
        restricted_page = site.root_page if inherited else feed_root
        PageViewRestriction.objects.create(page=restricted_page, restriction_type=restriction_type)
        kwargs = {"slug": feed_root.slug}
        if "podcast_feed" in route_name:
            kwargs["audio_format"] = "m4a"

        response = client.get(reverse(route_name, kwargs=kwargs))

        assert response.status_code == 404

    @pytest.mark.parametrize(
        ("route_name", "is_podcast"),
        [
            ("cast:latest_entries_feed", False),
            ("cast:latest_entries_atom_feed", False),
            ("cast:podcast_feed_rss", True),
            ("cast:podcast_feed_atom", True),
        ],
    )
    def test_cached_feed_is_hidden_after_root_becomes_restricted(self, client, post, episode, route_name, is_podcast):
        cache.clear()
        try:
            entry = episode if is_podcast else post
            feed_root = entry.blog
            kwargs = {"slug": feed_root.slug}
            if is_podcast:
                kwargs["audio_format"] = "m4a"
            feed_url = reverse(route_name, kwargs=kwargs)
            first_response = client.get(feed_url)
            assert first_response.status_code == 200
            assert entry.title in first_response.content.decode()

            original_title = entry.title
            entry.title = "updated after feed was cached"
            entry.save(update_fields=["title"])
            cached_response = client.get(feed_url)
            assert original_title in cached_response.content.decode()
            assert entry.title not in cached_response.content.decode()

            PageViewRestriction.objects.create(page=feed_root, restriction_type=PageViewRestriction.LOGIN)

            response = client.get(feed_url)

            assert response.status_code == 404
        finally:
            cache.clear()

    @pytest.mark.parametrize("route_name", ["cast:latest_entries_feed", "cast:latest_entries_atom_feed"])
    def test_feed_endpoint_keeps_interleaved_blog_state_separate(
        self, rf, blog, site, user, use_dummy_cache_backend, mocker, route_name
    ):
        other_blog = BlogFactory(owner=user, title="other blog", slug="other-blog", parent=site.root_page)
        first_request = rf.get(reverse(route_name, kwargs={"slug": blog.slug}))
        second_request = rf.get(reverse(route_name, kwargs={"slug": other_blog.slug}))
        view = resolve(first_request.path).func
        original_title = LatestEntriesFeed.title
        second_response = None
        interleaving_started = False

        def interleaved_title(feed):
            nonlocal interleaving_started, second_response
            if not interleaving_started:
                interleaving_started = True
                second_response = view(second_request, slug=other_blog.slug)
            return original_title(feed)

        mocker.patch.object(LatestEntriesFeed, "title", interleaved_title)

        first_response = view(first_request, slug=blog.slug)

        assert blog.title in first_response.content.decode()
        assert other_blog.title not in first_response.content.decode()
        assert second_response is not None
        assert other_blog.title in second_response.content.decode()
        assert blog.title not in second_response.content.decode()

    @pytest.mark.parametrize("route_name", ["cast:podcast_feed_rss", "cast:podcast_feed_atom"])
    def test_podcast_feed_endpoint_keeps_interleaved_audio_format_state_separate(
        self, rf, episode, audio, use_dummy_cache_backend, mocker, route_name
    ):
        audio.mp3.name = audio.m4a.name
        audio.save(update_fields=["mp3"])
        first_request = rf.get(reverse(route_name, kwargs={"slug": episode.blog.slug, "audio_format": "mp3"}))
        second_request = rf.get(reverse(route_name, kwargs={"slug": episode.blog.slug, "audio_format": "m4a"}))
        view = resolve(first_request.path).func
        original_title = PodcastFeed.title
        second_response = None
        interleaving_started = False

        def interleaved_title(feed, blog):
            nonlocal interleaving_started, second_response
            if not interleaving_started:
                interleaving_started = True
                second_response = view(second_request, slug=episode.blog.slug, audio_format="m4a")
            return original_title(feed, blog)

        mocker.patch.object(PodcastFeed, "title", interleaved_title)

        first_response = view(first_request, slug=episode.blog.slug, audio_format="mp3")

        assert "audio/mpeg" in first_response.content.decode()
        assert "audio/mp4" not in first_response.content.decode()
        assert second_response is not None
        assert "audio/mp4" in second_response.content.decode()
        assert "audio/mpeg" not in second_response.content.decode()

    def test_feed_endpoint_discards_state_after_exception(self, rf, blog, site, user, use_dummy_cache_backend, mocker):
        other_blog = BlogFactory(owner=user, title="other blog", slug="other-blog", parent=site.root_page)
        first_request = rf.get(reverse("cast:latest_entries_feed", kwargs={"slug": blog.slug}))
        second_request = rf.get(reverse("cast:latest_entries_feed", kwargs={"slug": other_blog.slug}))
        view = resolve(first_request.path).func
        failing_title = mocker.patch.object(LatestEntriesFeed, "title", side_effect=RuntimeError("render failed"))

        with pytest.raises(RuntimeError, match="render failed"):
            view(first_request, slug=blog.slug)

        mocker.stop(failing_title)
        response = view(second_request, slug=other_blog.slug)

        assert response.status_code == 200
        assert other_blog.title in response.content.decode()
        assert blog.title not in response.content.decode()

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

    @pytest.mark.parametrize(
        ("route_name", "root_path"),
        [
            ("cast:podcast_feed_rss", "./channel/item"),
            ("cast:podcast_feed_atom", "atom:entry"),
        ],
    )
    def test_podcast_feed_emits_podlove_simple_chapters(
        self, client, episode, use_dummy_cache_backend, route_name, root_path
    ):
        ChapterMark.objects.create(audio=episode.podcast_audio, start=time(0, 2, 0, 123456), title="Middle")
        ChapterMark.objects.create(audio=episode.podcast_audio, start=time(0, 1, 0), title="Intro")
        feed_url = reverse(route_name, kwargs={"slug": episode.podcast.slug, "audio_format": "m4a"})

        response = client.get(feed_url)

        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert content.count(f'xmlns:psc="{PSC_NAMESPACE}"') == 1
        root = ElementTree.fromstring(content)
        namespace = {
            "atom": "http://www.w3.org/2005/Atom",
            "podcast": "https://podcastindex.org/namespace/1.0/",
            "psc": PSC_NAMESPACE,
        }
        item = root.find(root_path, namespace)
        assert item is not None
        chapters = item.find("psc:chapters", namespace)
        assert chapters is not None
        assert chapters.attrib == {"version": "1.2"}
        chapter_elements = chapters.findall("psc:chapter", namespace)
        assert [chapter.attrib for chapter in chapter_elements] == [
            {"start": "00:01:00", "title": "Intro"},
            {"start": "00:02:00.123", "title": "Middle"},
        ]
        podcast_chapters = item.find("podcast:chapters", namespace)
        assert podcast_chapters is not None
        assert podcast_chapters.attrib == {
            "url": "http://testserver"
            f"{reverse('cast:chapters-json', kwargs={'pk': episode.podcast_audio.pk})}?episode_id={episode.pk}",
            "type": "application/json+chapters",
        }
        endpoint_url = urlparse(podcast_chapters.attrib["url"])
        endpoint_response = client.get(f"{endpoint_url.path}?{endpoint_url.query}")
        assert endpoint_response.status_code == 200
        assert endpoint_response.json()["chapters"] == [
            {"startTime": 60, "title": "Intro"},
            {"startTime": 120, "title": "Middle"},
        ]

    def test_podcast_feed_declares_podlove_namespace_once_per_chaptered_episode(
        self, client, episode, use_dummy_cache_backend
    ):
        ChapterMark.objects.create(audio=episode.podcast_audio, start=time(0, 1, 0), title="Intro")
        EpisodeFactory(
            owner=episode.owner,
            parent=episode.podcast,
            title="second chaptered episode",
            slug="second-chaptered-episode",
            podcast_audio=episode.podcast_audio,
            body=episode.body,
        )
        feed_url = reverse(
            "cast:podcast_feed_rss",
            kwargs={"slug": episode.podcast.slug, "audio_format": "m4a"},
        )

        response = client.get(feed_url)

        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert content.count(f'xmlns:psc="{PSC_NAMESPACE}"') == 2

    def test_podcast_feed_chaptered_item_element_query_count_is_flat(
        self, rf, episode, django_assert_num_queries, mocker
    ):
        class CapturingHandler:
            def __init__(self):
                self.calls = []

            def startElement(self, name, attrs):
                self.calls.append(("startElement", name, attrs))

            def addQuickElement(self, name, content=None, attrs=None):
                self.calls.append(("addQuickElement", name, content, attrs))

            def endElement(self, name):
                self.calls.append(("endElement", name))

        ChapterMark.objects.create(audio=episode.podcast_audio, start=time(0, 1, 0), title="Intro")
        for index in range(2):
            EpisodeFactory(
                owner=episode.owner,
                parent=episode.podcast,
                title=f"additional chaptered episode {index}",
                slug=f"additional-chaptered-episode-{index}",
                podcast_audio=episode.podcast_audio,
                body=episode.body,
            )
        request = rf.get(episode.podcast.get_url())
        repository = FeedContext.create_from_django_models(
            request=request,
            blog=episode.podcast,
            post_queryset=Episode.objects.live()
            .public()
            .descendant_of(episode.podcast)
            .filter(podcast_audio__isnull=False),
        )
        handler = CapturingHandler()
        generator = PodcastIndexElements()
        generator.request = request
        generator.repository = repository
        mocker.patch("cast.feeds.ITunesElements.add_item_elements")

        with django_assert_num_queries(0):
            for item in repository.post_queryset:
                generator.add_item_elements(handler, {"post": item})

        podcast_chapters_calls = [call for call in handler.calls if call[1] == "podcast:chapters"]
        assert len(podcast_chapters_calls) == 3

    @pytest.mark.parametrize(
        ("route_name", "root_name", "root_baseline"),
        [
            ("cast:podcast_feed_rss", "rss", RSS_CHAPTERLESS_ROOT_BASELINE),
            ("cast:podcast_feed_atom", "feed", ATOM_CHAPTERLESS_ROOT_BASELINE),
        ],
    )
    def test_chapterless_podcast_feed_omits_podlove_namespace_and_keeps_root_stable(
        self, client, episode, use_dummy_cache_backend, route_name, root_name, root_baseline
    ):
        feed_url = reverse(route_name, kwargs={"slug": episode.podcast.slug, "audio_format": "m4a"})

        response = client.get(feed_url)

        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert content.count(f'xmlns:psc="{PSC_NAMESPACE}"') == 0
        assert "psc:" not in content
        assert "podcast:chapters" not in content
        assert _root_start_tag(content, root_name) == root_baseline

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


@pytest.mark.parametrize(
    ("iso", "expected"),
    [
        ("01:02:03", "01:02:03"),
        ("01:02:03.987654", "01:02:03.987"),
    ],
)
def test_psc_start_formats_iso_time_for_podlove_simple_chapters(iso, expected):
    assert _psc_start(iso) == expected


@pytest.mark.django_db
def test_episode_get_chapters_url_uses_feed_repository(rf, episode):
    request = rf.get("/")
    repository = SimpleNamespace(
        chapters=[{"start": "00:01:00", "title": "Intro"}],
        podcast_audio=episode.podcast_audio,
    )

    assert episode.get_chapters_url(request, repository) == (
        "http://testserver"
        f"{reverse('cast:chapters-json', kwargs={'pk': episode.podcast_audio.pk})}?episode_id={episode.pk}"
    )


@pytest.mark.django_db
def test_episode_get_chapters_url_returns_none_for_chapterless_repository(rf, episode):
    request = rf.get("/")
    repository = SimpleNamespace(chapters=[], podcast_audio=episode.podcast_audio)

    assert episode.get_chapters_url(request, repository) is None


@pytest.mark.django_db
def test_episode_get_chapters_url_falls_back_to_podcast_audio(rf, episode):
    ChapterMark.objects.create(audio=episode.podcast_audio, start=time(0, 1, 0), title="Intro")
    request = rf.get("/")

    assert episode.get_chapters_url(request) == (
        "http://testserver"
        f"{reverse('cast:chapters-json', kwargs={'pk': episode.podcast_audio.pk})}?episode_id={episode.pk}"
    )


@pytest.mark.django_db
def test_episode_get_chapters_url_fallback_returns_none_without_chapters_or_audio(rf, episode):
    request = rf.get("/")
    assert episode.get_chapters_url(request) is None

    episode.podcast_audio = None
    assert episode.get_chapters_url(request) is None


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
    post.get_chapters_url.return_value = None

    atom_itunes_feed_generator = AtomITunesFeedGenerator("title", "link", "description")
    atom_itunes_feed_generator.request = request
    atom_itunes_feed_generator.add_item_elements(handler, {"post": post})
    handler.addQuickElement.assert_any_call("podcast:transcript", attrs={"type": "text/vtt", "url": vtt_url})
    handler.addQuickElement.assert_any_call("podcast:transcript", attrs={"type": "application/json", "url": json_url})


def test_podcast_index_add_item_elements_emits_podlove_simple_chapters_sequence(rf, mocker):
    class CapturingHandler:
        def __init__(self):
            self.calls = []

        def startElement(self, name, attrs):
            self.calls.append(("startElement", name, attrs))

        def addQuickElement(self, name, content=None, attrs=None):
            self.calls.append(("addQuickElement", name, content, attrs))

        def endElement(self, name):
            self.calls.append(("endElement", name))

    request = rf.get("/")
    mocker.patch("cast.feeds.ITunesElements.add_item_elements")
    episode_repository = SimpleNamespace(
        chapters=[
            {"start": "00:01:02", "title": "Intro"},
            {"start": "00:03:04.567890", "title": "Middle"},
        ]
    )
    repository = SimpleNamespace(get_episode_feed_detail_repository=lambda _episode: episode_repository)
    episode = SimpleNamespace(
        get_vtt_transcript_url=lambda _request, _repository: None,
        get_podcastindex_transcript_url=lambda _request, _repository: None,
        get_chapters_url=lambda _request, _repository: None,
        visible_contributor_assignments=[],
    )
    handler = CapturingHandler()

    atom_itunes_feed_generator = AtomITunesFeedGenerator("title", "link", "description")
    atom_itunes_feed_generator.request = request
    atom_itunes_feed_generator.repository = repository
    atom_itunes_feed_generator.add_item_elements(handler, {"post": episode})

    assert handler.calls == [
        ("startElement", "psc:chapters", {"xmlns:psc": PSC_NAMESPACE, "version": "1.2"}),
        ("addQuickElement", "psc:chapter", None, {"start": "00:01:02", "title": "Intro"}),
        ("addQuickElement", "psc:chapter", None, {"start": "00:03:04.567", "title": "Middle"}),
        ("endElement", "psc:chapters"),
    ]


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
    render = mocker.patch("cast.feeds.render_post_description", return_value="<p>description</p>")
    feed = PodcastFeed()
    feed.repository = None
    feed.request = mocker.MagicMock()
    # when calling item_description
    description = feed.item_description(item)
    # then the presenter should be called without resolving a detail repository from the feed
    assert description == "<p>description</p>"
    render.assert_called_once_with(
        item,
        request=feed.request,
        render_detail=True,
        escape_html=False,
        repository=None,
    )


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


def test_get_repository_replaces_used_predefined_repository(mocker):
    repository = mocker.MagicMock(used=True)
    replacement = mocker.MagicMock()
    cachable_data = mocker.patch.object(FeedContext, "data_for_feed_cachable", return_value={})
    create_repository = mocker.patch.object(FeedContext, "create_from_cachable_data", return_value=replacement)
    feed = LatestEntriesFeed(repository=repository)
    request = mocker.MagicMock()
    blog = mocker.MagicMock()

    returned = feed.get_repository(request, blog)

    assert returned is replacement
    cachable_data.assert_called_once_with(request=request, blog=blog, is_podcast=False)
    create_repository.assert_called_once_with(data={})


@pytest.mark.django_db
def test_feed_uses_request_host_without_replacing_configured_site(client, post, use_dummy_cache_backend):
    configured_site, _created = DjangoSite.objects.update_or_create(
        pk=django_settings.SITE_ID,
        defaults={"domain": "canonical.example", "name": "Canonical"},
    )
    site_cache_backup = sites_models.SITE_CACHE.copy()
    try:
        DjangoSite.objects.clear_cache()
        feed_url = reverse("cast:latest_entries_feed", kwargs={"slug": post.blog.slug})

        response = client.get(feed_url, HTTP_HOST="example.com")

        assert response.status_code == 200
        content = response.content.decode()
        assert f"http://example.com{feed_url}" in content
        assert "canonical.example" not in content
        assert DjangoSite.objects.get_current().pk == configured_site.pk
        assert DjangoSite.objects.get_current().domain == "canonical.example"
        assert DjangoSite.objects.get(pk=configured_site.pk).domain == "canonical.example"
    finally:
        sites_models.SITE_CACHE.clear()
        sites_models.SITE_CACHE.update(site_cache_backup)


@pytest.mark.django_db
def test_cached_feed_response_is_scoped_to_request_host(client, post, settings, mocker):
    settings.ALLOWED_HOSTS = [*settings.ALLOWED_HOSTS, "alternate.example"]
    DjangoSite.objects.update_or_create(
        pk=django_settings.SITE_ID,
        defaults={"domain": "canonical.example", "name": "Canonical"},
    )
    feed_url = reverse("cast:latest_entries_feed", kwargs={"slug": post.blog.slug})
    render_feed = mocker.spy(LatestEntriesFeed, "get_feed")
    site_cache_backup = sites_models.SITE_CACHE.copy()
    cache.clear()
    try:
        first = client.get(feed_url, HTTP_HOST="example.com")
        first_cached = client.get(feed_url, HTTP_HOST="example.com")
        second = client.get(feed_url, HTTP_HOST="alternate.example")

        assert first.status_code == 200
        assert first_cached.content == first.content
        assert second.status_code == 200
        assert render_feed.call_count == 2
        assert f"http://example.com{feed_url}" in first.content.decode()
        second_content = second.content.decode()
        assert f"http://alternate.example{feed_url}" in second_content
        assert f"http://example.com{feed_url}" not in second_content
    finally:
        cache.clear()
        sites_models.SITE_CACHE.clear()
        sites_models.SITE_CACHE.update(site_cache_backup)


@pytest.mark.django_db
def test_feed_missing_django_site_row_raises_configuration_error(client, post, use_dummy_cache_backend):
    DjangoSite.objects.filter(pk=django_settings.SITE_ID).delete()
    site_cache_backup = sites_models.SITE_CACHE.copy()
    try:
        DjangoSite.objects.clear_cache()
        feed_url = reverse("cast:latest_entries_feed", kwargs={"slug": post.blog.slug})

        with pytest.raises(ImproperlyConfigured, match="requires a django.contrib.sites Site"):
            client.get(feed_url)
    finally:
        sites_models.SITE_CACHE.clear()
        sites_models.SITE_CACHE.update(site_cache_backup)


@pytest.mark.django_db
def test_feed_without_site_id_uses_matching_django_site(client, post, settings, use_dummy_cache_backend):
    settings.SITE_ID = None
    matching_site, _created = DjangoSite.objects.get_or_create(domain="example.com", defaults={"name": "Request Host"})
    site_cache_backup = sites_models.SITE_CACHE.copy()
    try:
        DjangoSite.objects.clear_cache()
        feed_url = reverse("cast:latest_entries_feed", kwargs={"slug": post.blog.slug})

        response = client.get(feed_url, HTTP_HOST="example.com")

        assert response.status_code == 200
        assert f"http://example.com{feed_url}" in response.content.decode()
        assert DjangoSite.objects.get_current(response.wsgi_request) == matching_site
    finally:
        sites_models.SITE_CACHE.clear()
        sites_models.SITE_CACHE.update(site_cache_backup)


@pytest.mark.django_db
def test_feed_without_site_id_and_matching_site_raises_configuration_error(
    client, post, settings, use_dummy_cache_backend
):
    settings.SITE_ID = None
    settings.ALLOWED_HOSTS = [*settings.ALLOWED_HOSTS, "missing.example"]
    DjangoSite.objects.filter(domain="missing.example").delete()
    site_cache_backup = sites_models.SITE_CACHE.copy()
    try:
        DjangoSite.objects.clear_cache()
        feed_url = reverse("cast:latest_entries_feed", kwargs={"slug": post.blog.slug})

        with pytest.raises(ImproperlyConfigured, match="requires a django.contrib.sites Site"):
            client.get(feed_url, HTTP_HOST="missing.example")
    finally:
        sites_models.SITE_CACHE.clear()
        sites_models.SITE_CACHE.update(site_cache_backup)


@pytest.mark.django_db
def test_feed_without_django_sites_app_uses_request_site(client, post, use_dummy_cache_backend, mocker):
    mocker.patch("django.contrib.sites.shortcuts.apps.is_installed", return_value=False)
    get_current = mocker.patch.object(
        DjangoSite.objects,
        "get_current",
        side_effect=AssertionError("Django Site manager must not be used"),
    )
    feed_url = reverse("cast:latest_entries_feed", kwargs={"slug": post.blog.slug})

    response = client.get(feed_url, HTTP_HOST="example.com")

    assert response.status_code == 200
    assert f"http://example.com{feed_url}" in response.content.decode()
    get_current.assert_not_called()


def test_feed_preserves_absolute_repository_blog_url(rf, mocker):
    repository = mocker.MagicMock(blog_url="https://canonical.example/blog/")
    feed = LatestEntriesFeed(repository=repository)
    feed.request = rf.get("/blog/feed/rss.xml", HTTP_HOST="alternate.example")

    assert feed.link() == "https://canonical.example/blog/"


def test_atom_podcast_feed_uses_request_host_for_relative_blog_url(rf, mocker):
    repository = mocker.MagicMock(blog_url="/podcast/")
    feed = AtomPodcastFeed(repository=repository)
    feed.request = rf.get("/podcast/feed/podcast/mp3/atom.xml", HTTP_HOST="example.com")

    assert feed.link() == "http://example.com/podcast/"


def test_atom_podcast_feed_keeps_canonical_feed_identity(mocker):
    feed = AtomPodcastFeed()
    feed.object = mocker.MagicMock()
    feed.object.get_full_url.return_value = "https://canonical.example/podcast/"

    assert feed.feed_guid(feed.object) == "https://canonical.example/podcast/"


@pytest.mark.django_db
def test_latest_entries_feed_get_object_uses_repository_blog(rf, blog, mocker):
    repository = mocker.MagicMock()
    repository.used = False
    repository.blog = blog
    feed = LatestEntriesFeed(repository=repository)

    returned = feed.get_object(rf.get("/"), slug=blog.slug)

    assert returned is blog


@pytest.mark.django_db
def test_latest_entries_feed_get_object_ignores_used_repository(rf, blog, mocker):
    repository = mocker.MagicMock(used=True)
    repository.blog = mocker.MagicMock()
    feed = LatestEntriesFeed(repository=repository)

    returned = feed.get_object(rf.get("/"), slug=blog.slug)

    assert returned == blog


@pytest.mark.django_db
def test_podcast_feed_get_object_uses_repository_blog(rf, podcast, mocker):
    repository = mocker.MagicMock()
    repository.used = False
    repository.blog = podcast
    feed = PodcastFeed(repository=repository)

    returned = feed.get_object(rf.get("/"), slug=podcast.slug, audio_format="m4a")

    assert returned is podcast


@pytest.mark.django_db
def test_podcast_feed_get_object_ignores_used_repository(rf, podcast, mocker):
    repository = mocker.MagicMock(used=True)
    repository.blog = mocker.MagicMock()
    feed = PodcastFeed(repository=repository)

    returned = feed.get_object(rf.get("/"), slug=podcast.slug, audio_format="m4a")

    assert returned == podcast


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
