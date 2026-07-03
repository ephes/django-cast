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


def test_transcript_service_collection_helpers(mocker):
    get_or_create = mocker.patch("cast.voxhelm.Transcript.objects.get_or_create", return_value=("transcript", True))
    audio = SimpleNamespace(collection_id=None)

    assert VoxhelmTranscriptService._get_or_create_transcript(audio=audio) == (
        "transcript",
        True,
    )
    assert get_or_create.call_args.kwargs == {"audio": audio, "defaults": {}}

    transcript = SimpleNamespace(collection_id=None)
    VoxhelmTranscriptService._update_collection(
        transcript=transcript,
        audio=SimpleNamespace(collection_id=1, collection="root"),
    )
    assert transcript.collection == "root"


@pytest.mark.django_db
def test_enqueue_audio_transcript_generation_creates_local_state(mocker, audio, site):
    submission = TranscriptSubmission(
        job_id="job-queued",
        source_url="https://media.example.com/audio.m4a",
        task_ref=build_audio_task_ref(audio.pk),
        job_payload={"id": "job-queued", "state": "queued"},
    )
    service = mocker.Mock()
    service.submit_for_audio.return_value = submission
    service_cls = mocker.patch("cast.voxhelm.service.VoxhelmTranscriptService", return_value=service)
    enqueue_mock = mocker.Mock(return_value=SimpleNamespace(id="task-123"))
    mocker.patch("cast.voxhelm_tasks.complete_transcript_generation", new=SimpleNamespace(enqueue=enqueue_mock))

    result = enqueue_audio_transcript_generation(audio=audio, request_or_site=site, requested_by=audio.user)

    assert result.enqueued is True
    generation = get_transcript_generation(audio)
    assert generation is not None
    assert generation.status == TranscriptGeneration.Status.QUEUED
    assert generation.task_ref == build_audio_task_ref(audio.pk)
    assert generation.voxhelm_job_id == "job-queued"
    assert generation.task_result_id == "task-123"
    assert generation.source_url == "https://media.example.com/audio.m4a"
    assert generation.site == site
    assert generation.requested_by == audio.user
    service_cls.assert_called_once_with(request_or_site=site)
    service.submit_for_audio.assert_called_once_with(
        audio,
        task_ref=build_audio_task_ref(audio.pk),
        episode=None,
    )
    enqueue_mock.assert_called_once_with(generation.pk)


@pytest.mark.django_db
def test_enqueue_audio_transcript_generation_reuses_active_job(mocker, audio):
    generation = TranscriptGeneration.objects.create(
        audio=audio,
        status=TranscriptGeneration.Status.RUNNING,
        task_ref=build_audio_task_ref(audio.pk),
        voxhelm_job_id="job-running",
        task_result_id="task-1",
        source_url="https://media.example.com/audio.m4a",
    )
    submit = mocker.patch("cast.voxhelm.VoxhelmTranscriptService.submit_for_audio")

    result = enqueue_audio_transcript_generation(audio=audio)

    assert result.enqueued is False
    assert result.generation.pk == generation.pk
    submit.assert_not_called()


@pytest.mark.django_db
def test_enqueue_audio_transcript_generation_reuses_active_job_found_after_initial_lookup(mocker, audio):
    generation = TranscriptGeneration.objects.create(
        audio=audio,
        status=TranscriptGeneration.Status.RUNNING,
        task_ref=build_audio_task_ref(audio.pk),
        voxhelm_job_id="job-running",
        task_result_id="task-1",
        source_url="https://media.example.com/audio.m4a",
    )
    service = mocker.Mock()
    service.client = SimpleNamespace(diarization_enabled=False)
    mocker.patch("cast.voxhelm.service.VoxhelmTranscriptService", return_value=service)
    mocker.patch("cast.voxhelm.service.get_transcript_generation", return_value=None)

    result = enqueue_audio_transcript_generation(audio=audio)

    assert result.enqueued is False
    assert result.generation.pk == generation.pk
    service.submit_for_audio.assert_not_called()


@pytest.mark.django_db
def test_enqueue_audio_transcript_generation_uses_diarized_task_ref_from_site_settings(mocker, audio, site, settings):
    settings.CAST_VOXHELM_API_BASE = "https://settings.example"
    settings.CAST_VOXHELM_API_KEY = "settings-secret"
    VoxhelmSettings.objects.update_or_create(
        site=site,
        defaults={
            "api_base": "https://site.example",
            "api_token": "site-secret",
            "diarization_enabled": True,
        },
    )
    task_ref = build_audio_task_ref(audio.pk, diarization_enabled=True)
    submission = TranscriptSubmission(
        job_id="job-diarized",
        source_url="https://media.example.com/audio.m4a",
        task_ref=task_ref,
        job_payload={"id": "job-diarized", "state": "queued"},
    )
    submit = mocker.patch("cast.voxhelm.VoxhelmTranscriptService.submit_for_audio", return_value=submission)
    enqueue_mock = mocker.Mock(return_value=SimpleNamespace(id="task-123"))
    mocker.patch("cast.voxhelm_tasks.complete_transcript_generation", new=SimpleNamespace(enqueue=enqueue_mock))

    result = enqueue_audio_transcript_generation(audio=audio, request_or_site=site, requested_by=audio.user)

    assert result.enqueued is True
    generation = get_transcript_generation(audio)
    assert generation is not None
    assert generation.task_ref == task_ref
    assert generation.voxhelm_job_id == "job-diarized"
    submit.assert_called_once_with(audio, task_ref=task_ref, episode=None)


@pytest.mark.django_db
def test_enqueue_audio_transcript_generation_uses_episode_speaker_count(mocker, episode):
    audio = episode.podcast_audio
    assert audio is not None
    for index in range(4):
        contributor = Contributor.objects.create(display_name=f"Speaker {index}", slug=f"enqueue-speaker-{index}")
        EpisodeContributor.objects.create(
            episode=episode,
            contributor=contributor,
            role=EpisodeContributor.ROLE_GUEST,
        )
    task_ref = build_audio_task_ref(audio.pk, diarization_enabled=True, diarization_speaker_count=4)
    submission = TranscriptSubmission(
        job_id="job-diarized",
        source_url="https://media.example.com/audio.m4a",
        task_ref=task_ref,
        job_payload={"id": "job-diarized", "state": "queued"},
    )
    service = mocker.Mock()
    service.client = SimpleNamespace(diarization_enabled=True)
    service.submit_for_audio.return_value = submission
    mocker.patch("cast.voxhelm.service.VoxhelmTranscriptService", return_value=service)
    enqueue_mock = mocker.Mock(return_value=SimpleNamespace(id="task-123"))
    mocker.patch("cast.voxhelm_tasks.complete_transcript_generation", new=SimpleNamespace(enqueue=enqueue_mock))

    result = enqueue_audio_transcript_generation(audio=audio, episode=episode)

    generation = get_transcript_generation(audio)
    assert result.enqueued is True
    assert generation is not None
    assert generation.task_ref == task_ref
    service.submit_for_audio.assert_called_once_with(audio, task_ref=task_ref, episode=episode)


@pytest.mark.django_db
def test_enqueue_audio_transcript_generation_enabled_mode_overrides_client_disabled(mocker, episode):
    audio = episode.podcast_audio
    assert audio is not None
    audio.transcript_diarization_mode = Audio.TranscriptDiarizationMode.ENABLED
    audio.save(update_fields=["transcript_diarization_mode"], duration=False, cache_file_sizes=False)
    first = Contributor.objects.create(display_name="Enabled First", slug="enqueue-enabled-first")
    second = Contributor.objects.create(display_name="Enabled Second", slug="enqueue-enabled-second")
    EpisodeContributor.objects.create(episode=episode, contributor=first, role=EpisodeContributor.ROLE_HOST)
    EpisodeContributor.objects.create(episode=episode, contributor=second, role=EpisodeContributor.ROLE_GUEST)
    task_ref = build_audio_task_ref(audio.pk, diarization_enabled=True, diarization_speaker_count=2)
    submission = TranscriptSubmission(
        job_id="job-enabled",
        source_url="https://media.example.com/audio.m4a",
        task_ref=task_ref,
        job_payload={"id": "job-enabled", "state": "queued"},
    )
    service = mocker.Mock()
    service.client = SimpleNamespace(diarization_enabled=False)
    service.submit_for_audio.return_value = submission
    mocker.patch("cast.voxhelm.service.VoxhelmTranscriptService", return_value=service)
    enqueue_mock = mocker.Mock(return_value=SimpleNamespace(id="task-123"))
    mocker.patch("cast.voxhelm_tasks.complete_transcript_generation", new=SimpleNamespace(enqueue=enqueue_mock))

    result = enqueue_audio_transcript_generation(audio=audio, episode=episode)

    generation = get_transcript_generation(audio)
    assert result.enqueued is True
    assert generation is not None
    assert generation.task_ref == task_ref
    service.submit_for_audio.assert_called_once_with(audio, task_ref=task_ref, episode=episode)


@pytest.mark.django_db
def test_enqueue_audio_transcript_generation_disabled_mode_overrides_client_enabled(mocker, episode):
    audio = episode.podcast_audio
    assert audio is not None
    audio.transcript_diarization_mode = Audio.TranscriptDiarizationMode.DISABLED
    audio.save(update_fields=["transcript_diarization_mode"], duration=False, cache_file_sizes=False)
    first = Contributor.objects.create(display_name="Disabled First", slug="enqueue-disabled-first")
    second = Contributor.objects.create(display_name="Disabled Second", slug="enqueue-disabled-second")
    EpisodeContributor.objects.create(episode=episode, contributor=first, role=EpisodeContributor.ROLE_HOST)
    EpisodeContributor.objects.create(episode=episode, contributor=second, role=EpisodeContributor.ROLE_GUEST)
    task_ref = build_audio_task_ref(audio.pk)
    submission = TranscriptSubmission(
        job_id="job-disabled",
        source_url="https://media.example.com/audio.m4a",
        task_ref=task_ref,
        job_payload={"id": "job-disabled", "state": "queued"},
    )
    service = mocker.Mock()
    service.client = SimpleNamespace(diarization_enabled=True)
    service.submit_for_audio.return_value = submission
    mocker.patch("cast.voxhelm.service.VoxhelmTranscriptService", return_value=service)
    enqueue_mock = mocker.Mock(return_value=SimpleNamespace(id="task-123"))
    mocker.patch("cast.voxhelm_tasks.complete_transcript_generation", new=SimpleNamespace(enqueue=enqueue_mock))

    result = enqueue_audio_transcript_generation(audio=audio, episode=episode)

    generation = get_transcript_generation(audio)
    assert result.enqueued is True
    assert generation is not None
    assert generation.task_ref == task_ref
    service.submit_for_audio.assert_called_once_with(audio, task_ref=task_ref, episode=episode)


@pytest.mark.django_db
def test_enqueue_audio_transcript_generation_requeues_inactive_generation_with_diarized_task_ref(mocker, audio):
    generation = TranscriptGeneration.objects.create(
        audio=audio,
        status=TranscriptGeneration.Status.SUCCEEDED,
        task_ref=build_audio_task_ref(audio.pk),
        voxhelm_job_id="job-old",
        task_result_id="task-old",
        source_url="https://media.example.com/audio.m4a",
    )
    task_ref = build_audio_task_ref(audio.pk, diarization_enabled=True)
    submission = TranscriptSubmission(
        job_id="job-diarized",
        source_url="https://media.example.com/audio.m4a",
        task_ref=task_ref,
        job_payload={"id": "job-diarized", "state": "queued"},
    )
    service = mocker.Mock()
    service.client = SimpleNamespace(diarization_enabled=True)
    service.submit_for_audio.return_value = submission
    mocker.patch("cast.voxhelm.service.VoxhelmTranscriptService", return_value=service)
    enqueue_mock = mocker.Mock(return_value=SimpleNamespace(id="task-123"))
    mocker.patch("cast.voxhelm_tasks.complete_transcript_generation", new=SimpleNamespace(enqueue=enqueue_mock))

    result = enqueue_audio_transcript_generation(audio=audio)

    generation.refresh_from_db()
    assert result.enqueued is True
    assert result.generation.pk == generation.pk
    assert generation.task_ref == task_ref
    assert generation.voxhelm_job_id == "job-diarized"
    service.submit_for_audio.assert_called_once_with(audio, task_ref=task_ref, episode=None)


@pytest.mark.django_db
def test_enqueue_audio_transcript_generation_requires_saved_audio():
    unsaved_audio = SimpleNamespace(pk=None)

    with pytest.raises(VoxhelmError, match="must be saved"):
        enqueue_audio_transcript_generation(audio=unsaved_audio)  # type: ignore[arg-type]


@pytest.mark.django_db
def test_enqueue_audio_transcript_generation_marks_failed_when_enqueue_fails(mocker, audio, site):
    submission = TranscriptSubmission(
        job_id="job-queued",
        source_url="https://media.example.com/audio.m4a",
        task_ref=build_audio_task_ref(audio.pk),
        job_payload={"id": "job-queued", "state": "queued"},
    )
    service = mocker.Mock()
    service.submit_for_audio.return_value = submission
    mocker.patch("cast.voxhelm.service.VoxhelmTranscriptService", return_value=service)
    enqueue_mock = mocker.Mock(side_effect=RuntimeError("queue broke"))
    mocker.patch("cast.voxhelm_tasks.complete_transcript_generation", new=SimpleNamespace(enqueue=enqueue_mock))

    with pytest.raises(RuntimeError, match="queue broke"):
        enqueue_audio_transcript_generation(audio=audio, request_or_site=site, requested_by=audio.user)

    generation = get_transcript_generation(audio)
    assert generation is not None
    assert generation.status == TranscriptGeneration.Status.FAILED
    assert generation.error_message == "queue broke"


@pytest.mark.django_db
def test_enqueue_audio_transcript_generation_marks_failed_when_initial_submit_fails(mocker, audio, site):
    service = mocker.Mock()
    service.submit_for_audio.side_effect = VoxhelmError("voxhelm offline")
    mocker.patch("cast.voxhelm.service.VoxhelmTranscriptService", return_value=service)

    with pytest.raises(VoxhelmError, match="voxhelm offline"):
        enqueue_audio_transcript_generation(audio=audio, request_or_site=site, requested_by=audio.user)

    generation = get_transcript_generation(audio)
    assert generation is not None
    assert generation.status == TranscriptGeneration.Status.FAILED
    assert generation.error_message == "voxhelm offline"
    assert generation.voxhelm_job_id == ""


@pytest.mark.django_db
def test_enqueue_audio_transcript_generation_preserves_existing_failed_row_when_retry_submit_fails(
    mocker, audio, site
):
    generation = TranscriptGeneration.objects.create(
        audio=audio,
        status=TranscriptGeneration.Status.FAILED,
        task_ref=build_audio_task_ref(audio.pk),
        error_message="older failure",
    )
    service = mocker.Mock()
    service.submit_for_audio.side_effect = VoxhelmError("voxhelm still offline")
    mocker.patch("cast.voxhelm.service.VoxhelmTranscriptService", return_value=service)

    with pytest.raises(VoxhelmError, match="voxhelm still offline"):
        enqueue_audio_transcript_generation(audio=audio, request_or_site=site, requested_by=audio.user)

    generation.refresh_from_db()
    assert generation.status == TranscriptGeneration.Status.FAILED
    assert generation.error_message == "older failure"


@pytest.mark.django_db
def test_complete_transcript_generation_marks_success_and_calls_service(mocker, audio):
    generation = TranscriptGeneration.objects.create(
        audio=audio,
        status=TranscriptGeneration.Status.QUEUED,
        task_ref=build_audio_task_ref(audio.pk),
        voxhelm_job_id="job-42",
        task_result_id="task-42",
        source_url="https://media.example.com/audio.m4a",
    )
    service = mocker.Mock()
    mocker.patch("cast.voxhelm_tasks.VoxhelmTranscriptService", return_value=service)

    complete_transcript_generation.call(generation.pk)

    generation.refresh_from_db()
    assert generation.status == TranscriptGeneration.Status.SUCCEEDED
    service.complete_audio_job.assert_called_once_with(
        audio,
        job_id="job-42",
        source_url="https://media.example.com/audio.m4a",
    )


@pytest.mark.django_db
def test_complete_transcript_generation_returns_when_already_succeeded(mocker, audio):
    generation = TranscriptGeneration.objects.create(
        audio=audio,
        status=TranscriptGeneration.Status.SUCCEEDED,
        task_ref=build_audio_task_ref(audio.pk),
    )
    service_cls = mocker.patch("cast.voxhelm_tasks.VoxhelmTranscriptService")

    complete_transcript_generation.call(generation.pk)

    service_cls.assert_not_called()


@pytest.mark.django_db
def test_complete_transcript_generation_marks_failure_on_exception(mocker, audio):
    generation = TranscriptGeneration.objects.create(
        audio=audio,
        status=TranscriptGeneration.Status.QUEUED,
        task_ref=build_audio_task_ref(audio.pk),
        voxhelm_job_id="job-43",
        source_url="https://media.example.com/audio.m4a",
    )
    service = mocker.Mock()
    service.complete_audio_job.side_effect = VoxhelmError("worker broke")
    mocker.patch("cast.voxhelm_tasks.VoxhelmTranscriptService", return_value=service)

    with pytest.raises(VoxhelmError, match="worker broke"):
        complete_transcript_generation.call(generation.pk)

    generation.refresh_from_db()
    assert generation.status == TranscriptGeneration.Status.FAILED
    assert generation.error_message == "worker broke"


@pytest.mark.django_db
def test_get_transcript_generation_status_context_exposes_failed_state(audio):
    TranscriptGeneration.objects.create(
        audio=audio,
        status=TranscriptGeneration.Status.FAILED,
        task_ref=build_audio_task_ref(audio.pk),
        error_message="upstream broke",
    )

    context = get_transcript_generation_status_context(audio=audio)

    assert context["transcript_generation_active"] is False
    assert context["transcript_generation_status"] == "Failed"
    assert context["transcript_generation_error"] == "upstream broke"


@pytest.mark.django_db
def test_get_transcript_generation_status_context_links_succeeded_transcript(audio):
    transcript = create_transcript(audio=audio)
    TranscriptGeneration.objects.create(
        audio=audio,
        status=TranscriptGeneration.Status.SUCCEEDED,
        task_ref=build_audio_task_ref(audio.pk),
    )

    context = get_transcript_generation_status_context(audio=audio)

    assert context["transcript_generation_status"] == "Succeeded"
    assert context["transcript_generation_transcript_url"] == reverse("cast-transcript:edit", args=(transcript.pk,))
