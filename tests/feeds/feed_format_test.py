"""Format-specific subscriptions and current enclosure sizes use synthetic media."""

from datetime import timedelta

import feedparser
import pytest
from django.core.files.base import ContentFile
from django.urls import reverse
from wagtail.models import PageViewRestriction

from cast import appsettings
from cast.models import Audio
from cast.models.repository import serialize_audio
from tests.factories import EpisodeFactory


@pytest.mark.django_db
@pytest.mark.parametrize("repository", ["default", "django"])
@pytest.mark.parametrize("route", ["podcast_feed_rss", "podcast_feed_atom"])
@pytest.mark.parametrize("audio_format", ["mp3", "m4a"])
def test_feed_only_lists_requested_format(client, episode, monkeypatch, repository, route, audio_format):
    monkeypatch.setattr(appsettings, "CAST_REPOSITORY", repository)
    expected = set()
    for title, formats, restricted in [
        ("Synthetic MP3", ["mp3"], False),
        ("Synthetic M4A", ["m4a"], False),
        ("Synthetic Both", ["mp3", "m4a"], False),
        ("Synthetic Private", ["mp3", "m4a"], True),
    ]:
        audio = Audio(user=episode.owner, title=title, duration=timedelta(seconds=1))
        for fmt in formats:
            getattr(audio, fmt).save(f"synthetic.{fmt}", ContentFile(b"synthetic media"), save=False)
        audio.save(duration=False, cache_file_sizes=True)
        item = EpisodeFactory(
            owner=episode.owner, parent=episode.podcast, title=title, podcast_audio=audio, body=episode.body
        )
        if restricted:
            PageViewRestriction.objects.create(page=item, restriction_type=PageViewRestriction.LOGIN)
        elif audio_format in formats:
            expected.add(title)
    if getattr(episode.podcast_audio, audio_format):
        expected.add(episode.title)
    response = client.get(
        reverse(f"cast:{route}", kwargs={"slug": episode.podcast.slug, "audio_format": audio_format})
    )
    assert response.status_code == 200
    entries = feedparser.parse(response.content).entries
    assert {entry.title for entry in entries} == expected
    assert all(entry.enclosures[0].type == Audio.mime_lookup[audio_format] for entry in entries)


@pytest.mark.django_db
@pytest.mark.parametrize("change", ["clear", "replace", "missing", "unreadable"])
@pytest.mark.parametrize("repository", ["default", "django"])
@pytest.mark.parametrize("route", ["podcast_feed_rss", "podcast_feed_atom"])
def test_size_derivation_reconciles_current_formats(episode, client, monkeypatch, repository, route, change, mocker):
    monkeypatch.setattr(appsettings, "CAST_REPOSITORY", repository)
    audio = episode.podcast_audio
    audio.mp3.save("synthetic.mp3", ContentFile(b"unchanged"), save=False)
    audio.data = {"custom": {"keep": True}}
    audio.save(duration=False, cache_file_sizes=True)
    previous = audio.data["size"]["m4a"]
    original_size = audio.m4a.storage.size
    storage_size = mocker.spy(audio.m4a.storage, "size")
    if change == "clear":
        audio.m4a = None
    elif change == "replace":
        audio.m4a.save("replacement.m4a", ContentFile(b"new generation"), save=False)
        assert audio.get_file_size("m4a") == len(b"new generation")
    else:
        name = audio.m4a.name

        def size(key):
            if key == name:
                raise FileNotFoundError if change == "missing" else PermissionError
            return original_size(key)

        storage_size.side_effect = size
    audio.save(duration=False, cache_file_sizes=True)
    audio.refresh_from_db()
    expected = len(b"new generation") if change == "replace" else 0
    assert audio.get_file_size("m4a") == expected != previous
    assert audio.data["custom"] == {"keep": True}
    assert audio.data["size"]["mp3"] == len(b"unchanged")
    if change != "replace":
        assert "m4a" not in audio.data["size"]
    assert serialize_audio(audio)["data"]["size"] == audio.data["size"]
    assert next(item for item in audio.audio if item["mimeType"] == Audio.mime_lookup["mp3"])["size"] == str(
        len(b"unchanged")
    )
    if change != "clear":
        assert next(item for item in audio.audio if item["mimeType"] == Audio.mime_lookup["m4a"])["size"] == str(
            expected
        )
    response = client.get(reverse(f"cast:{route}", kwargs={"slug": episode.podcast.slug, "audio_format": "m4a"}))
    assert response.status_code == 200
    entries = feedparser.parse(response.content).entries
    if change == "clear":
        assert entries == []
    else:
        assert entries[0].enclosures[0].length == str(expected)
    storage_size.reset_mock()
    assert audio.get_file_size("mp3") == len(b"unchanged")
    storage_size.assert_not_called()
