import importlib
from pathlib import Path

import pytest
from django.core.files.storage import FileSystemStorage, InMemoryStorage, default_storage, storages
from django.test import override_settings
from django.urls import reverse

from cast.devdata import create_transcript
from cast.models import Transcript
from cast.private_storage import get_private_media_root, get_private_media_storage, get_transcript_storage

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


@override_settings(
    STORAGES={
        **TEST_STORAGES,
        "cast_public_transcripts": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
        "cast_private_media": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    }
)
def test_transcript_storage_uses_configured_alias_before_private_media_alias():
    assert get_transcript_storage() is storages["cast_public_transcripts"]
    assert isinstance(get_transcript_storage(), InMemoryStorage)


@override_settings(
    STORAGES={
        **TEST_STORAGES,
        "cast_private_media": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    }
)
def test_transcript_storage_falls_back_to_configured_private_media_alias():
    assert isinstance(get_transcript_storage(), InMemoryStorage)


@override_settings(STORAGES=TEST_STORAGES)
def test_transcript_storage_falls_back_to_default_storage_when_unconfigured():
    assert get_transcript_storage() is default_storage


def test_public_transcript_artifact_fields_use_transcript_storage_helper():
    for field_name in ("podlove", "vtt", "dote"):
        field = Transcript._meta.get_field(field_name)
        assert field._storage_callable is get_transcript_storage


@pytest.mark.django_db
def test_transcript_artifacts_are_saved_to_default_storage_when_unconfigured(audio):
    transcript = create_transcript(
        audio=audio,
        podlove={"transcripts": [{"text": "hello"}]},
        vtt="WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nhello\n",
        dote={"lines": []},
    )

    media_root = Path(default_storage.location)
    assert transcript.podlove.storage is default_storage
    assert transcript.vtt.storage is default_storage
    assert transcript.dote.storage is default_storage
    assert Path(transcript.podlove.path).is_relative_to(media_root)
    assert Path(transcript.vtt.path).is_relative_to(media_root)
    assert Path(transcript.dote.path).is_relative_to(media_root)
    assert default_storage.exists(transcript.podlove.name)


@pytest.mark.django_db
def test_private_transcript_storage_migration_leaves_default_storage_files_in_place(audio):
    transcript = create_transcript(audio=audio, podlove={"transcripts": [{"text": "hello"}]})
    original_name = transcript.podlove.name
    migration = importlib.import_module("cast.migrations.0077_private_transcript_artifact_storage")

    migration.keep_transcript_artifacts_in_place(None, None)

    assert transcript.podlove.storage is default_storage
    assert default_storage.exists(original_name)


@pytest.mark.django_db
def test_public_transcript_endpoint_reads_transcript_storage_and_sanitizes(client, episode):
    transcript = create_transcript(
        audio=episode.podcast_audio,
        podlove={"transcripts": [{"speaker": "Draft Guest", "voice": "Draft Guest", "text": "hello"}]},
        vtt="WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nhello\n",
        dote={"lines": []},
    )

    response = client.get(reverse("cast:podlove-transcript-json", args=(transcript.pk,)))

    assert response.status_code == 200
    assert response.json()["transcripts"] == [{"text": "hello"}]
    assert transcript.podlove.storage.exists(transcript.podlove.name)
