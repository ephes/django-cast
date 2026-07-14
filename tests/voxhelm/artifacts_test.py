# ruff: noqa: F401,F811,I001
import io
import json
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.error import URLError
from urllib.request import Request

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import RequestFactory
from django.urls import reverse
from wagtail.models import Collection

from cast.devdata import create_transcript
from cast.models import Audio, Contributor, EpisodeContributor, TranscriptGeneration, VoxhelmSettings
from cast.voxhelm_tasks import complete_transcript_generation
from tests.factories import EpisodeFactory
from cast.voxhelm import (
    NoRedirectHandler,
    TranscriptGenerationResult,
    TranscriptSubmission,
    VoxhelmClient,
    VoxhelmError,
    VoxhelmTranscriptService,
    append_diarization_speaker_count_to_task_ref,
    build_audio_task_ref,
    build_failure_message,
    count_episode_diarization_speakers,
    enqueue_audio_transcript_generation,
    ensure_diarized_task_ref,
    get_bool_setting,
    get_float_setting,
    get_setting,
    get_transcript_generation,
    get_transcript_generation_status_context,
    normalize_api_base,
    open_url,
    read_response_bytes,
    require_setting,
    require_artifact_path,
    replace_file,
    resolve_audio_source_url,
    resolve_audio_diarization_enabled,
    resolve_audio_task_ref,
    resolve_diarization_speaker_count,
    strip_diarized_task_ref,
    transcript_complete,
    validate_transcript_artifacts,
)


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False


VALID_PODLOVE_ARTIFACT = b'{"transcripts": [{"text": "done"}]}'
VALID_DOTE_ARTIFACT = (
    b'{"lines": [{"startTime": "00:00:00,000", "endTime": "00:00:00,100", "speakerDesignation": "", "text": "done"}]}'
)
VALID_VTT_ARTIFACT = b"WEBVTT\n\n00:00:00.000 --> 00:00:00.100\ndone\n"


@pytest.mark.django_db
def test_generate_for_audio_updates_existing_transcript(settings, user, m4a_audio):
    settings.MEDIA_URL = "https://media.example.com/"
    audio = Audio(user=user, m4a=m4a_audio, title="episode", collection=Collection.get_first_root_node())
    audio.save(duration=False, cache_file_sizes=False)

    from cast.devdata import create_transcript

    existing = create_transcript(
        audio=audio,
        podlove={"transcripts": [{"text": "old"}]},
        vtt="WEBVTT\n\n00:00:00.000 --> 00:00:00.100\nold\n",
        dote={
            "lines": [
                {
                    "startTime": "00:00:00,000",
                    "endTime": "00:00:00,100",
                    "speakerDesignation": "",
                    "text": "old",
                }
            ]
        },
    )
    old_paths = existing.get_all_paths()

    class StubClient:
        def submit_transcription_job(
            self, *, source_url, task_ref, context, speaker_count=None, diarization_enabled=None
        ):
            assert source_url == audio.m4a.url
            assert task_ref == f"cast-audio-{audio.pk}"
            assert context == {"consumer": "django-cast", "audio_id": audio.pk}
            assert speaker_count is None
            assert diarization_enabled is False
            return {
                "id": "job-2",
                "state": "succeeded",
                "result": {"artifacts": {"podlove": "/podlove", "dote": "/dote", "vtt": "/vtt"}},
            }

        def wait_for_job(self, job_id):
            raise AssertionError(f"wait_for_job should not run for terminal jobs: {job_id}")

        def download_artifact(self, artifact_path):
            if artifact_path == "/podlove":
                return json.dumps(
                    {
                        "version": 1,
                        "transcripts": [
                            {
                                "start": "00:00:02.000",
                                "start_ms": 2000,
                                "end": "00:00:04.000",
                                "end_ms": 4000,
                                "speaker": "",
                                "voice": "",
                                "text": "fresh transcript",
                            }
                        ],
                    }
                ).encode("utf-8")
            if artifact_path == "/dote":
                return json.dumps(
                    {
                        "lines": [
                            {
                                "startTime": "00:00:02,000",
                                "endTime": "00:00:04,000",
                                "speakerDesignation": "",
                                "text": "fresh transcript",
                            }
                        ]
                    }
                ).encode("utf-8")
            if artifact_path == "/vtt":
                return b"WEBVTT\n\n00:00:02.000 --> 00:00:04.000\nfresh transcript\n"
            raise AssertionError(f"unexpected artifact: {artifact_path}")

    result = VoxhelmTranscriptService(client=StubClient()).generate_for_audio(audio)

    existing.refresh_from_db()
    assert result.created is False
    assert existing.get_all_paths() != old_paths
    assert existing.collection_id == audio.collection_id
    assert existing.podlove_data["transcripts"][0]["text"] == "fresh transcript"
    assert existing.dote_data["lines"][0]["text"] == "fresh transcript"
    with existing.vtt.open("r") as handle:
        assert handle.read() == "WEBVTT\n\n00:00:02.000 --> 00:00:04.000\nfresh transcript\n"


@pytest.mark.django_db
def test_generate_for_audio_saves_optional_speakers_artifact(settings, user, m4a_audio):
    settings.MEDIA_URL = "https://media.example.com/"
    audio = Audio(user=user, m4a=m4a_audio, title="episode")
    audio.save(duration=False, cache_file_sizes=False)

    class StubClient:
        def submit_transcription_job(
            self, *, source_url, task_ref, context, speaker_count=None, diarization_enabled=None
        ):
            del source_url, task_ref, context, speaker_count, diarization_enabled
            return {
                "id": "job-speakers",
                "state": "succeeded",
                "result": {
                    "artifacts": {
                        "podlove": "/podlove",
                        "dote": "/dote",
                        "vtt": "/vtt",
                        "speakers": "/speakers",
                    }
                },
            }

        def wait_for_job(self, job_id):
            raise AssertionError(f"wait_for_job should not run for terminal jobs: {job_id}")

        def download_artifact(self, artifact_path):
            if artifact_path == "/podlove":
                return VALID_PODLOVE_ARTIFACT
            if artifact_path == "/dote":
                return VALID_DOTE_ARTIFACT
            if artifact_path == "/vtt":
                return VALID_VTT_ARTIFACT
            if artifact_path == "/speakers":
                return b'{"segments": []}'
            raise AssertionError(f"unexpected artifact: {artifact_path}")

    result = VoxhelmTranscriptService(client=StubClient()).generate_for_audio(audio)

    result.transcript.refresh_from_db()
    assert result.transcript.speakers_data == {"segments": []}


@pytest.mark.django_db
def test_save_artifacts_keeps_existing_files_when_later_artifact_write_fails(settings, user, m4a_audio, mocker):
    settings.MEDIA_URL = "https://media.example.com/"
    audio = Audio(user=user, m4a=m4a_audio, title="episode")
    audio.save(duration=False, cache_file_sizes=False)
    existing = create_transcript(
        audio=audio,
        podlove={"transcripts": [{"text": "old podlove"}]},
        vtt="WEBVTT\n\n00:00:00.000 --> 00:00:00.100\nold vtt\n",
        dote={"lines": [{"text": "old dote"}]},
    )
    old_podlove_name = existing.podlove.name
    old_dote_name = existing.dote.name
    old_vtt_name = existing.vtt.name
    storage = existing.podlove.storage
    original_save = storage.save
    saved_names = []

    def fail_dote_save(name, content, *args, **kwargs):
        saved_names.append(name)
        if "dote" in name:
            raise OSError("dote write failed")
        return original_save(name, content, *args, **kwargs)

    mocker.patch.object(storage, "save", side_effect=fail_dote_save)

    with pytest.raises(OSError, match="dote write failed"):
        VoxhelmTranscriptService._save_artifacts(
            transcript=existing,
            audio=audio,
            podlove=b'{"transcripts": [{"text": "new podlove"}]}',
            dote=VALID_DOTE_ARTIFACT,
            vtt=b"WEBVTT\n\nnew vtt\n",
        )

    persisted = type(existing).objects.get(pk=existing.pk)
    assert existing.podlove.name == old_podlove_name
    assert existing.dote.name == old_dote_name
    assert existing.vtt.name == old_vtt_name
    assert persisted.podlove.name == old_podlove_name
    assert persisted.dote.name == old_dote_name
    assert persisted.vtt.name == old_vtt_name
    assert storage.exists(old_podlove_name)
    assert storage.exists(old_dote_name)
    assert storage.exists(old_vtt_name)
    assert not storage.exists(saved_names[0])
    assert persisted.podlove_data["transcripts"][0]["text"] == "old podlove"
    assert persisted.dote_data["lines"][0]["text"] == "old dote"
    with persisted.vtt.open("r") as handle:
        assert "old vtt" in handle.read()


@pytest.mark.django_db
def test_generate_for_audio_waits_for_queued_job(settings, user, m4a_audio):
    settings.MEDIA_URL = "https://media.example.com/"
    audio = Audio(user=user, m4a=m4a_audio, title="episode")
    audio.save(duration=False, cache_file_sizes=False)

    class StubClient:
        def submit_transcription_job(
            self, *, source_url, task_ref, context, speaker_count=None, diarization_enabled=None
        ):
            del source_url, task_ref, context, speaker_count, diarization_enabled
            return {"id": "job-3", "state": "queued"}

        def wait_for_job(self, job_id):
            assert job_id == "job-3"
            return {"id": "job-3", "state": "failed", "error": {"message": "transcription failed"}}

        def download_artifact(self, artifact_path):
            raise AssertionError(f"unexpected artifact: {artifact_path}")

    with pytest.raises(VoxhelmError, match="transcription failed"):
        VoxhelmTranscriptService(client=StubClient()).generate_for_audio(audio)


@pytest.mark.django_db
def test_complete_audio_job_ignores_mismatched_initial_payload(settings, user, m4a_audio):
    settings.MEDIA_URL = "https://media.example.com/"
    audio = Audio(user=user, m4a=m4a_audio, title="episode")
    audio.save(duration=False, cache_file_sizes=False)

    class StubClient:
        def wait_for_job(self, job_id):
            assert job_id == "job-5"
            return {
                "id": "job-5",
                "state": "succeeded",
                "result": {"artifacts": {"podlove": "/podlove", "dote": "/dote", "vtt": "/vtt"}},
            }

        def download_artifact(self, artifact_path):
            if artifact_path == "/podlove":
                return b'{"version": 1, "transcripts": [{"text": "done"}]}'
            if artifact_path == "/dote":
                return VALID_DOTE_ARTIFACT
            if artifact_path == "/vtt":
                return b"WEBVTT\n"
            raise AssertionError(f"unexpected artifact: {artifact_path}")

    result = VoxhelmTranscriptService(client=StubClient()).complete_audio_job(
        audio,
        job_id="job-5",
        source_url=audio.m4a.url,
        initial_job_payload={"id": "job-other", "state": "succeeded"},
    )

    assert result.job_id == "job-5"


@pytest.mark.django_db
@pytest.mark.parametrize("missing_format", ["podlove", "dote", "vtt"])
def test_generate_for_audio_requires_required_artifacts(settings, user, m4a_audio, missing_format):
    settings.MEDIA_URL = "https://media.example.com/"
    audio = Audio(user=user, m4a=m4a_audio, title="episode")
    audio.save(duration=False, cache_file_sizes=False)

    class StubClient:
        def submit_transcription_job(
            self, *, source_url, task_ref, context, speaker_count=None, diarization_enabled=None
        ):
            del source_url, task_ref, context, speaker_count, diarization_enabled
            artifacts = {"podlove": "/podlove", "dote": "/dote", "vtt": "/vtt"}
            artifacts.pop(missing_format)
            return {"id": "job-4", "state": "succeeded", "result": {"artifacts": artifacts}}

        def wait_for_job(self, job_id):
            raise AssertionError(f"wait_for_job should not run for terminal jobs: {job_id}")

        def download_artifact(self, artifact_path):
            if artifact_path == "/podlove":
                return b'{"version": 1, "transcripts": []}'
            if artifact_path == "/dote":
                return b'{"lines": []}'
            if artifact_path == "/vtt":
                return b"WEBVTT\n"
            raise AssertionError(f"unexpected artifact: {artifact_path}")

    with pytest.raises(VoxhelmError, match=rf"'{missing_format}' artifact"):
        VoxhelmTranscriptService(client=StubClient()).generate_for_audio(audio)
