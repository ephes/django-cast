from pathlib import Path

import pytest
from django.core.files.storage import FileSystemStorage, InMemoryStorage, default_storage
from django.test import override_settings
from django.urls import reverse

from cast.devdata import create_transcript
from cast.private_storage import get_private_media_root, get_private_media_storage

TEST_STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


def test_private_media_root_uses_configured_setting(settings, tmp_path):
    settings.CAST_PRIVATE_MEDIA_ROOT = str(tmp_path / "configured-private")

    assert get_private_media_root() == str(tmp_path / "configured-private")


@override_settings(CAST_PRIVATE_MEDIA_ROOT="")
def test_private_media_root_defaults_outside_media_root(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path / "media")

    assert get_private_media_root() == str(tmp_path / "cast-private-media")


@override_settings(
    STORAGES={
        **TEST_STORAGES,
        "cast_private_media": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    }
)
def test_private_media_storage_uses_configured_alias():
    assert isinstance(get_private_media_storage(), InMemoryStorage)


@override_settings(STORAGES=TEST_STORAGES)
def test_private_media_storage_falls_back_to_non_public_filesystem(settings, tmp_path):
    settings.CAST_PRIVATE_MEDIA_ROOT = str(tmp_path / "private")

    storage = get_private_media_storage()

    assert isinstance(storage, FileSystemStorage)
    assert Path(storage.location) == tmp_path / "private"
    with pytest.raises(ValueError, match="not accessible via a URL"):
        storage.url("transcript.json")


@pytest.mark.django_db
def test_transcript_artifacts_are_saved_to_private_storage(audio):
    transcript = create_transcript(
        audio=audio,
        podlove={"transcripts": [{"text": "hello"}]},
        vtt="WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nhello\n",
        dote={"lines": []},
    )

    private_root = Path(transcript.podlove.storage.location)
    assert Path(transcript.podlove.path).is_relative_to(private_root)
    assert Path(transcript.vtt.path).is_relative_to(private_root)
    assert Path(transcript.dote.path).is_relative_to(private_root)
    assert not default_storage.exists(transcript.podlove.name)
    with pytest.raises(ValueError, match="not accessible via a URL"):
        transcript.podlove.url


@pytest.mark.django_db
def test_public_transcript_endpoint_reads_private_storage_and_sanitizes(client, episode):
    transcript = create_transcript(
        audio=episode.podcast_audio,
        podlove={"transcripts": [{"speaker": "Draft Guest", "voice": "Draft Guest", "text": "hello"}]},
        vtt="WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nhello\n",
        dote={"lines": []},
    )

    response = client.get(reverse("cast:podlove-transcript-json", args=(transcript.pk,)))

    assert response.status_code == 200
    assert response.json()["transcripts"] == [{"text": "hello"}]
    with pytest.raises(ValueError, match="not accessible via a URL"):
        transcript.podlove.url
