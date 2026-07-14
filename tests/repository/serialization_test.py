# ruff: noqa: F401,F811,I001
"""
This file contains tests for the post data cache. Make sure
all queries happen in one place and there are no additional
queries when rendering posts.
"""

import json
import pickle
from contextvars import Context, copy_context
from copy import deepcopy
from pathlib import Path
from xml.etree import ElementTree

import pytest
import sqlparse
import cast.models.repository as repository_module
from django.contrib.contenttypes.models import ContentType
from django.contrib.sites import models as sites_models
from django.contrib.sites.models import Site as DjangoSite
from django.db import connection, reset_queries
from django.urls import reverse
from django.utils import timezone
from wagtail.images.models import Image, Rendition
from wagtail.models import Site as WagtailSite

from cast.devdata import create_post, create_python_body, create_transcript, generate_blog_with_media
from cast.feeds import LatestEntriesFeed, RssPodcastFeed
from cast.filters import PostFilterset
from cast.models import (
    Audio,
    Blog,
    Contributor,
    ContributorLink,
    Episode,
    EpisodeContributor,
    Podcast,
    Post,
    Season,
    Transcript,
    Video,
)
from cast.models.image_renditions import create_missing_renditions_for_posts
from cast.models.repository.builders import _blog_url_from_referer
from cast.models.repository import (
    BlogIndexContext,
    FeedContext,
    PostDetailContext,
    PostQuerySnapshot,
    add_queryset_data,
    add_site_raw,
    apply_cover_fallback,
    deserialize_audio,
    deserialize_episode,
    deserialize_image,
    deserialize_post,
    deserialize_season,
    deserialize_transcript,
    deserialize_video,
    deserialize_blog,
    deserialize_episode_contributor,
    data_for_blog_cachable,
    get_facet_choices,
    serialize_audio,
    serialize_blog,
    serialize_episode_contributor,
    serialize_episode,
    serialize_image,
    serialize_post,
    serialize_renditions,
    serialize_season,
    serialize_transcript,
    serialize_video,
)
from cast.wagtail_hooks import PageLinkHandlerWithCache
from tests.factories import EpisodeFactory

from tests.repository.helpers import (
    StubFile,
    blocker,
    blog_index_repository,
    feed_repository,
    post_detail_repository,
    queryset_data,
    show_queries,
)


def test_serialize_renditions():
    rendition = Rendition(file="foo.jpg", filter_spec="foobarfilter", width=100, height=200)
    renditions = serialize_renditions({1: [rendition]})
    rendition = Rendition(**renditions[1][0])
    assert rendition.file == "foo.jpg"


def test_serialize_media_helpers():
    audio = Audio(
        id=1,
        collection=None,
        duration=None,
        title="Some audio",
        subtitle="Some subtitle",
        data={},
        m4a=StubFile("audio.m4a"),
        mp3=StubFile("audio.mp3"),
        oga=StubFile("audio.oga"),
        opus=StubFile("audio.opus"),
    )
    video = Video(
        id=1,
        collection=None,
        title="Some video",
        original=StubFile("video.mp4"),
        poster=StubFile("poster.jpg"),
        poster_seconds=1,
    )
    image = Image(id=1, title="Some image", collection=None, file=StubFile("image.jpg"), width=100, height=200)

    class Podlove:
        name = "podlove.json"

    class TranscriptFile:
        name = "transcript.vtt"

    class TranscriptStub:
        pk = 1
        audio_id = 1
        podlove = Podlove()
        vtt = TranscriptFile()
        dote = TranscriptFile()
        collection_id = None

    transcript = TranscriptStub()

    assert serialize_audio(audio)["m4a"] == "audio.m4a"
    assert serialize_video(video)["original"] == "video.mp4"
    assert serialize_image(image)["file"] == "image.jpg"
    assert serialize_transcript(transcript)["podlove"] == "podlove.json"


@pytest.mark.django_db
def test_serialize_episode_contributor_roundtrip(episode, image):
    contributor = Contributor.objects.create(
        display_name="Episode Guest",
        slug="episode-guest",
        avatar=image,
        default_role=EpisodeContributor.ROLE_HOST,
    )
    contributor._avatar_rendition_url = "/media/images/test.fill-80x80.format-webp.webp"
    link = ContributorLink.objects.create(
        contributor=contributor,
        service=ContributorLink.SERVICE_WEBSITE,
        url="https://example.com/guest",
        sort_order=0,
    )
    assignment = EpisodeContributor.objects.create(
        episode=episode,
        contributor=contributor,
        role=EpisodeContributor.ROLE_GUEST,
        link=link,
        sort_order=0,
    )
    # Carry the precomputed rendition URL through serialization, not the live FK instance.
    assignment.contributor = contributor

    data = serialize_episode_contributor(assignment)
    rebuilt = deserialize_episode_contributor(data)
    assert rebuilt.contributor.get_avatar_rendition_url() == "/media/images/test.fill-80x80.format-webp.webp"

    assert rebuilt.display_name == "Episode Guest"
    assert rebuilt.contributor.default_role == EpisodeContributor.ROLE_HOST
    assert rebuilt.href == "https://example.com/guest"
    assert rebuilt.contributor_id == contributor.pk
    assert rebuilt.link.contributor_id == contributor.pk
    assert rebuilt.link.contributor is rebuilt.contributor
    assert rebuilt.link.service == ContributorLink.SERVICE_WEBSITE
    assert rebuilt.sort_order == 0
    rebuilt.clean()


@pytest.mark.django_db
def test_serialize_episode_contributor_without_avatar_rendition(episode):
    contributor = Contributor.objects.create(display_name="Plain Guest", slug="plain-guest")
    assignment = EpisodeContributor.objects.create(
        episode=episode,
        contributor=contributor,
        role=EpisodeContributor.ROLE_GUEST,
        sort_order=0,
    )

    data = serialize_episode_contributor(assignment)
    rebuilt = deserialize_episode_contributor(data)

    assert "avatar_rendition_url" not in data["contributor"]
    assert rebuilt.contributor.get_avatar_rendition_url() == ""
    assert rebuilt.href == ""


@pytest.mark.django_db
def test_serialize_season_roundtrip(episode):
    season = Season.objects.create(podcast=episode.podcast, number=3, name="Named season")

    data = serialize_season(season)
    rebuilt = deserialize_season(data)

    assert "pk" not in data
    assert rebuilt.pk == season.pk
    assert rebuilt.podcast_id == episode.podcast.pk
    assert rebuilt.number == 3
    assert rebuilt.name == "Named season"


@pytest.mark.django_db
def test_serialize_episode_roundtrip_with_publishing_metadata(episode):
    season = Season.objects.create(podcast=episode.podcast, number=1, name="Launch")
    episode.episode_number = 42
    episode.episode_type = Episode.EpisodeType.FULL
    episode.season = season

    data = serialize_episode(episode)
    rebuilt = deserialize_episode(data)

    assert rebuilt.episode_number == 42
    assert rebuilt.episode_type == Episode.EpisodeType.FULL
    assert rebuilt.season is not None
    assert rebuilt.season.number == 1
    assert rebuilt.season.name == "Launch"
    assert serialize_episode(rebuilt) == data


def test_get_facet_choices():
    class Facet:
        choices = [("foo", "Foo"), ("bar", "Bar")]

    # choices are found
    choices = get_facet_choices({"foobar": Facet()}, "foobar")
    assert choices == Facet.choices


@pytest.mark.django_db
def test_deserialize_blog_returns_blog(blog):
    data = serialize_blog(blog)
    assert data["type"] == "blog"
    rebuilt = deserialize_blog(data)
    assert isinstance(rebuilt, Blog)
    assert not isinstance(rebuilt, Podcast)
    assert rebuilt.title == blog.title
    assert rebuilt.subtitle == blog.subtitle


@pytest.mark.django_db
def test_deserialize_legacy_blog_without_type_returns_blog(blog):
    data = serialize_blog(blog)
    data.pop("type")
    rebuilt = deserialize_blog(data)
    assert isinstance(rebuilt, Blog)
    assert not isinstance(rebuilt, Podcast)
    assert rebuilt.title == blog.title


@pytest.mark.django_db
def test_serialize_deserialize_blog_roundtrip_podcast(podcast_with_artwork):
    podcast_with_artwork.itunes_categories = "Technology"
    podcast_with_artwork.keywords = "foo,bar"
    podcast_with_artwork.explicit = 2
    podcast_with_artwork.itunes_type = Podcast.ItunesType.SERIAL
    podcast_with_artwork.subtitle = "Test subtitle"
    podcast_with_artwork.save(update_fields=["itunes_categories", "keywords", "explicit", "itunes_type", "subtitle"])

    data = serialize_blog(podcast_with_artwork)
    assert data["type"] == "podcast"
    rebuilt = deserialize_blog(data)

    assert isinstance(rebuilt, Podcast)
    assert rebuilt.title == podcast_with_artwork.title
    assert rebuilt.subtitle == podcast_with_artwork.subtitle
    assert rebuilt.itunes_categories == podcast_with_artwork.itunes_categories
    assert rebuilt.keywords == podcast_with_artwork.keywords
    assert rebuilt.explicit == podcast_with_artwork.explicit
    assert rebuilt.itunes_type == podcast_with_artwork.itunes_type
    assert rebuilt.itunes_artwork is not None
    assert rebuilt.itunes_artwork.original.name == podcast_with_artwork.itunes_artwork.original.name

    # no choices found
    choices = get_facet_choices({}, "foobar")
    assert choices == []


@pytest.mark.django_db
def test_deserialize_legacy_podcast_without_type_returns_podcast(podcast_with_artwork):
    podcast_with_artwork.itunes_categories = "Technology"
    podcast_with_artwork.keywords = "foo,bar"
    podcast_with_artwork.explicit = 2
    podcast_with_artwork.save(update_fields=["itunes_categories", "keywords", "explicit"])

    data = serialize_blog(podcast_with_artwork)
    data.pop("type")
    rebuilt = deserialize_blog(data)

    assert isinstance(rebuilt, Podcast)
    assert rebuilt.keywords == podcast_with_artwork.keywords


@pytest.mark.django_db
def test_deserialize_blog_roundtrip(blog):
    data = serialize_blog(blog)
    rebuilt = deserialize_blog(data)
    assert isinstance(rebuilt, Blog)
    assert rebuilt.title == blog.title
    assert rebuilt.slug == blog.slug


def test_deserialize_canonical_media_types():
    audio = deserialize_audio(
        {
            "id": 1,
            "duration": None,
            "title": "Some audio",
            "subtitle": "Some subtitle",
            "data": {},
            "m4a": "audio.m4a",
            "mp3": "audio.mp3",
            "oga": "audio.oga",
            "opus": "audio.opus",
            "collection": None,
        }
    )
    transcript = deserialize_transcript(
        {
            "id": 1,
            "audio_id": 1,
            "podlove": "podlove.json",
            "vtt": "transcript.vtt",
            "dote": "transcript.dote",
            "collection": None,
        }
    )
    video = deserialize_video(
        {
            "id": 1,
            "title": "Some video",
            "original": "video.mp4",
            "poster": "poster.jpg",
            "poster_seconds": 1,
            "collection": None,
        }
    )
    image = deserialize_image(
        {
            "pk": 1,
            "title": "Some image",
            "file": "image.jpg",
            "width": 100,
            "height": 200,
            "collection": None,
        }
    )
    post = deserialize_post(
        {
            "id": 1,
            "pk": 1,
            "uuid": "d9f1825b-6f86-4d24-8455-7c3eef4da36f",
            "slug": "post-slug",
            "title": "Post title",
            "visible_date": None,
            "comments_enabled": True,
            "body": "[]",
        }
    )
    episode = deserialize_episode(
        {
            "id": 2,
            "pk": 2,
            "uuid": "b9a1947f-2581-4f8d-b2be-26247ea2f30f",
            "slug": "episode-slug",
            "title": "Episode title",
            "visible_date": None,
            "comments_enabled": True,
            "body": "[]",
            "podcast_audio": {
                "id": 1,
                "duration": None,
                "title": "Some audio",
                "subtitle": "Some subtitle",
                "data": {},
                "m4a": "audio.m4a",
                "mp3": "audio.mp3",
                "oga": "audio.oga",
                "opus": "audio.opus",
                "collection": None,
            },
            "keywords": "",
            "explicit": 0,
            "block": False,
        }
    )
    episode_without_podcast_audio = deserialize_episode(
        {
            "id": 3,
            "pk": 3,
            "uuid": "f05b2e72-9330-472e-9930-84475e912aaf",
            "slug": "episode-without-audio-slug",
            "title": "Episode without audio",
            "visible_date": None,
            "comments_enabled": True,
            "body": "[]",
            "keywords": "",
            "explicit": 0,
            "block": False,
        }
    )

    assert isinstance(audio, Audio)
    assert isinstance(transcript, Transcript)
    assert isinstance(video, Video)
    assert isinstance(image, Image)
    assert isinstance(post, Post)
    assert isinstance(episode, Episode)
    assert isinstance(episode_without_podcast_audio, Episode)


def test_serialize_deserialize_roundtrip_for_media_types():
    audio = Audio(
        id=1,
        collection=None,
        duration=None,
        title="Some audio",
        subtitle="Some subtitle",
        data={},
        m4a=StubFile("audio.m4a"),
        mp3=StubFile("audio.mp3"),
        oga=StubFile("audio.oga"),
        opus=StubFile("audio.opus"),
    )
    audio_data = serialize_audio(audio)
    assert serialize_audio(deserialize_audio(audio_data)) == audio_data

    class Podlove:
        name = "podlove.json"

    class TranscriptFile:
        name = "transcript.vtt"

    class TranscriptStub:
        pk = 1
        audio_id = 1
        podlove = Podlove()
        vtt = TranscriptFile()
        dote = TranscriptFile()
        collection_id = None

    transcript_data = serialize_transcript(TranscriptStub())
    assert serialize_transcript(deserialize_transcript(transcript_data)) == transcript_data

    video = Video(
        id=1,
        collection=None,
        title="Some video",
        original=StubFile("video.mp4"),
        poster=StubFile("poster.jpg"),
        poster_seconds=1,
    )
    video_data = serialize_video(video)
    assert serialize_video(deserialize_video(video_data)) == video_data

    image = Image(id=1, title="Some image", collection=None, file=StubFile("image.jpg"), width=100, height=200)
    image_data = serialize_image(image)
    assert serialize_image(deserialize_image(image_data)) == image_data


@pytest.mark.django_db
def test_serialize_deserialize_roundtrip_for_post_types(post, episode):
    post_data = serialize_post(post)
    assert post_data["type"] == "post"
    assert serialize_post(deserialize_post(post_data)) == post_data

    episode_data = serialize_episode(episode)
    assert episode_data["type"] == "episode"
    assert serialize_episode(deserialize_episode(episode_data)) == episode_data


def test_feed_context_deserializes_post_discriminator(blog_data):
    data = deepcopy(blog_data)
    data.update(
        {
            "site": {"id": 1},
            "blog_url": "/some-blog/",
        }
    )

    repository = FeedContext.create_from_cachable_data(data=data)

    assert isinstance(repository.post_by_id[1], Post)
    assert not isinstance(repository.post_by_id[1], Episode)


def test_feed_context_deserializes_episode_discriminator(blog_data):
    data = deepcopy(blog_data)
    data.update(
        {
            "site": {"id": 1},
            "blog_url": "/some-blog/",
        }
    )
    data["post_by_id"][1]["type"] = "episode"
    data["post_by_id"][1]["podcast_audio"] = data["audios"][1]

    repository = FeedContext.create_from_cachable_data(data=data)

    assert isinstance(repository.post_by_id[1], Episode)


def test_feed_context_deserializes_legacy_post_without_type(blog_data):
    data = deepcopy(blog_data)
    data.update(
        {
            "site": {"id": 1},
            "blog_url": "/some-blog/",
        }
    )
    data["post_by_id"][1].pop("type")

    repository = FeedContext.create_from_cachable_data(data=data)

    assert isinstance(repository.post_by_id[1], Post)
    assert not isinstance(repository.post_by_id[1], Episode)


def test_feed_context_deserializes_legacy_episode_without_type(blog_data):
    data = deepcopy(blog_data)
    data.update(
        {
            "site": {"id": 1},
            "blog_url": "/some-blog/",
        }
    )
    data["post_by_id"][1].pop("type")
    data["post_by_id"][1]["podcast_audio"] = data["audios"][1]

    repository = FeedContext.create_from_cachable_data(data=data)

    assert isinstance(repository.post_by_id[1], Episode)


def test_blog_index_context_deserializes_legacy_episode_without_type(blog_data):
    data = deepcopy(blog_data)
    data["post_by_id"][1].pop("type")
    data["post_by_id"][1]["podcast_audio"] = data["audios"][1]

    repository = BlogIndexContext.create_from_cachable_data(data=data)

    assert isinstance(repository.post_by_id[1], Episode)


@pytest.mark.django_db
def test_create_from_cachable_data_use_audio_player_false():
    data = {
        "template_base_dir": "bootstrap4",
        "blog": {"id": 1, "title": "Some blog", "slug": "some-blog"},
        "post_by_id": {1: {"pk": 1}},
        "posts": [1],
        "page_url_by_id": {1: "/foo-bar-baz/"},
        "absolute_page_url_by_id": {1: "http://testserver/foo-bar-baz/"},
        "pagination_context": {},
        "audios": {},
        "images": {},
        "videos": {},
        "renditions_for_posts": {},
        "audios_by_post_id": {},
        "videos_by_post_id": {},
        "images_by_post_id": {},
        "cover_by_post_id": {},
        "cover_alt_by_post_id": {},
        "owner_username_by_id": {1: "owner"},
        "has_audio_by_id": {1: False},
        "root_nav_links": [],
        "filterset": {
            "get_params": {},
            "date_facets_choices": [],
            "category_facets_choices": [],
            "tag_facets_choices": [],
        },
    }
    repository = BlogIndexContext.create_from_cachable_data(data=data)
    assert repository.use_audio_player is False
