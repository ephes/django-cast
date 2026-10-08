from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone

from cast.models import TranscriptGeneration
from cast.models.transcript_generation import get_transcript_generation_stale_after
from cast.voxhelm import (
    TranscriptSubmission,
    VoxhelmError,
    build_audio_task_ref,
    enqueue_audio_transcript_generation,
    get_transcript_generation_status_context,
)
from cast.voxhelm_tasks import complete_transcript_generation

STALE_AGE = timedelta(seconds=900 + 15 * 60 + 60)
FRESH_AGE = timedelta(minutes=5)


def make_generation(audio, *, status, age, started=True):
    generation = TranscriptGeneration.objects.create(
        audio=audio,
        status=status,
        task_ref=build_audio_task_ref(audio.pk),
        voxhelm_job_id="job-old",
        task_result_id="task-old",
        source_url="https://media.example.com/audio.m4a",
    )
    then = timezone.now() - age
    TranscriptGeneration.objects.filter(pk=generation.pk).update(
        updated_at=then,
        started_at=then if started else None,
    )
    generation.refresh_from_db()
    return generation


def make_generation_aged(generation, age):
    TranscriptGeneration.objects.filter(pk=generation.pk).update(updated_at=timezone.now() - age)
    generation.refresh_from_db()
    return generation


def mock_resubmission(mocker, audio, *, job_id="job-old"):
    submission = TranscriptSubmission(
        job_id=job_id,
        source_url="https://media.example.com/audio.m4a",
        task_ref=build_audio_task_ref(audio.pk),
        job_payload={"id": job_id, "state": "running"},
    )
    service = mocker.Mock()
    service.client = SimpleNamespace(diarization_enabled=False)
    service.submit_for_audio.return_value = submission
    mocker.patch("cast.voxhelm.service.VoxhelmTranscriptService", return_value=service)
    enqueue_mock = mocker.Mock(return_value=SimpleNamespace(id="task-new"))
    mocker.patch("cast.voxhelm_tasks.complete_transcript_generation", new=SimpleNamespace(enqueue=enqueue_mock))
    return service, enqueue_mock


@pytest.fixture(autouse=True)
def default_timeouts(settings, monkeypatch):
    settings.CAST_VOXHELM_POLL_TIMEOUT = None
    settings.CAST_VOXHELM_STALE_AFTER = None
    monkeypatch.delenv("CAST_VOXHELM_POLL_TIMEOUT", raising=False)
    monkeypatch.delenv("CAST_VOXHELM_STALE_AFTER", raising=False)


def test_stale_after_defaults_to_poll_timeout_plus_margin():
    assert get_transcript_generation_stale_after() == timedelta(seconds=900 + 15 * 60)


def test_stale_after_follows_poll_timeout_setting(settings):
    settings.CAST_VOXHELM_POLL_TIMEOUT = 6 * 3600
    assert get_transcript_generation_stale_after() == timedelta(seconds=6 * 3600 + 15 * 60)


def test_stale_after_explicit_setting_and_environment(settings, monkeypatch):
    monkeypatch.setenv("CAST_VOXHELM_STALE_AFTER", "120")
    assert get_transcript_generation_stale_after() == timedelta(seconds=120)
    monkeypatch.setenv("CAST_VOXHELM_STALE_AFTER", "")
    monkeypatch.setenv("CAST_VOXHELM_POLL_TIMEOUT", "60")
    assert get_transcript_generation_stale_after() == timedelta(seconds=60 + 15 * 60)
    settings.CAST_VOXHELM_STALE_AFTER = "30"
    assert get_transcript_generation_stale_after() == timedelta(seconds=30)


def test_stale_after_rejects_non_numeric_value(settings):
    settings.CAST_VOXHELM_STALE_AFTER = "soon"
    with pytest.raises(ImproperlyConfigured, match="CAST_VOXHELM_STALE_AFTER"):
        get_transcript_generation_stale_after()


@pytest.mark.django_db
@pytest.mark.parametrize("status", [TranscriptGeneration.Status.QUEUED, TranscriptGeneration.Status.RUNNING])
def test_fresh_active_generation_still_blocks(mocker, audio, status):
    generation = make_generation(audio, status=status, age=FRESH_AGE)
    service_cls = mocker.patch("cast.voxhelm.service.VoxhelmTranscriptService")

    assert generation.is_stale is False
    assert generation.is_active is True
    result = enqueue_audio_transcript_generation(audio=audio)

    assert result.enqueued is False
    service_cls.assert_not_called()
    assert get_transcript_generation_status_context(audio=audio)["transcript_generation_active"] is True


@pytest.mark.django_db
@pytest.mark.parametrize("status", [TranscriptGeneration.Status.QUEUED, TranscriptGeneration.Status.RUNNING])
def test_stale_generation_resumes_its_existing_voxhelm_job(mocker, audio, site, status):
    generation = make_generation(audio, status=status, age=STALE_AGE)
    stored_ref = f"{build_audio_task_ref(audio.pk)}-diarized-4-speakers"
    TranscriptGeneration.objects.filter(pk=generation.pk).update(task_ref=stored_ref, site=site)
    generation.refresh_from_db()
    assert generation.is_stale is True
    assert generation.is_active is False
    service, enqueue_mock = mock_resubmission(mocker, audio, job_id="job-new")

    # Recovery requested without a site keeps the site whose Voxhelm endpoint owns the job.
    result = enqueue_audio_transcript_generation(audio=audio, request_or_site=None)

    assert result.enqueued is True
    # Diarization is now disabled, but the interrupted job is resumed, not resubmitted.
    service.submit_for_audio.assert_not_called()
    enqueue_mock.assert_called_once_with(generation.pk)
    generation.refresh_from_db()
    assert generation.status == TranscriptGeneration.Status.QUEUED
    assert generation.task_ref == stored_ref
    assert generation.voxhelm_job_id == "job-old"
    assert generation.source_url == "https://media.example.com/audio.m4a"
    assert generation.task_result_id == "task-new"
    assert generation.site == site
    assert generation.is_active is True


@pytest.mark.django_db
def test_stale_generation_without_job_id_is_resubmitted(mocker, audio, site):
    generation = make_generation(audio, status=TranscriptGeneration.Status.QUEUED, age=STALE_AGE)
    TranscriptGeneration.objects.filter(pk=generation.pk).update(voxhelm_job_id="")
    service, enqueue_mock = mock_resubmission(mocker, audio, job_id="job-new")

    result = enqueue_audio_transcript_generation(audio=audio, request_or_site=site)

    assert result.enqueued is True
    service.submit_for_audio.assert_called_once_with(audio, task_ref=build_audio_task_ref(audio.pk), episode=None)
    enqueue_mock.assert_called_once_with(generation.pk)
    generation.refresh_from_db()
    assert generation.voxhelm_job_id == "job-new"
    assert generation.status == TranscriptGeneration.Status.QUEUED


@pytest.mark.django_db
def test_running_generation_staleness_is_measured_from_started_at(audio):
    generation = make_generation(audio, status=TranscriptGeneration.Status.RUNNING, age=STALE_AGE)
    # A save touches updated_at, but the task started long ago.
    TranscriptGeneration.objects.filter(pk=generation.pk).update(updated_at=timezone.now())
    generation.refresh_from_db()

    assert generation.is_stale is True


@pytest.mark.django_db
def test_running_generation_without_started_at_uses_updated_at(audio):
    generation = make_generation(audio, status=TranscriptGeneration.Status.RUNNING, age=FRESH_AGE, started=False)
    assert generation.is_stale is False
    generation = make_generation_aged(generation, STALE_AGE)
    assert generation.is_stale is True


@pytest.mark.django_db
@pytest.mark.parametrize("status", [TranscriptGeneration.Status.SUCCEEDED, TranscriptGeneration.Status.FAILED])
def test_terminal_generation_is_never_stale(audio, status):
    generation = make_generation(audio, status=status, age=STALE_AGE)
    assert generation.is_stale is False


@pytest.mark.django_db
def test_custom_stale_after_setting_is_respected(audio, settings):
    settings.CAST_VOXHELM_STALE_AFTER = 60
    generation = make_generation(audio, status=TranscriptGeneration.Status.RUNNING, age=timedelta(minutes=2))
    assert generation.is_stale is True


@pytest.mark.django_db
def test_stale_resubmission_failure_marks_generation_failed(mocker, audio, site):
    generation = make_generation(audio, status=TranscriptGeneration.Status.QUEUED, age=STALE_AGE)
    TranscriptGeneration.objects.filter(pk=generation.pk).update(voxhelm_job_id="")
    service, _ = mock_resubmission(mocker, audio)
    service.submit_for_audio.side_effect = VoxhelmError("voxhelm offline")

    with pytest.raises(VoxhelmError, match="voxhelm offline"):
        enqueue_audio_transcript_generation(audio=audio, request_or_site=site)

    generation.refresh_from_db()
    assert generation.status == TranscriptGeneration.Status.FAILED
    assert generation.error_message == "voxhelm offline"


@pytest.mark.django_db
def test_status_context_reports_interrupted_generation(audio):
    make_generation(audio, status=TranscriptGeneration.Status.RUNNING, age=STALE_AGE)

    context = get_transcript_generation_status_context(audio=audio)

    assert context["transcript_generation_active"] is False
    assert context["transcript_generation_status"] == "Interrupted"
    assert "interrupted" in context["transcript_generation_message"]
    assert context["transcript_generation_transcript_url"] == ""


@pytest.mark.django_db
def test_task_marks_failed_when_service_construction_fails(mocker, audio):
    generation = make_generation(audio, status=TranscriptGeneration.Status.QUEUED, age=FRESH_AGE)
    mocker.patch(
        "cast.voxhelm_tasks.VoxhelmTranscriptService",
        side_effect=ImproperlyConfigured("CAST_VOXHELM_API_KEY must be configured"),
    )

    with pytest.raises(ImproperlyConfigured):
        complete_transcript_generation.call(generation.pk)

    generation.refresh_from_db()
    assert generation.status == TranscriptGeneration.Status.FAILED
    assert "CAST_VOXHELM_API_KEY" in generation.error_message
