"""Synthetic consent generations for destructive admin regeneration."""

from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.core.files.base import ContentFile
from django.db import transaction
from django.urls import reverse

from cast.devdata import create_transcript
from cast.models import Audio, TranscriptGeneration
from cast.transcripts.regeneration import StaleRegenerationConfirmation
from cast.voxhelm import (
    TranscriptSubmission,
    VoxhelmError,
    enqueue_audio_transcript_generation,
    service as service_module,
)
from cast.voxhelm.service import _consume_consent, _ReviewedAttempt

pytestmark = pytest.mark.django_db


@pytest.fixture
def confirmation(admin_client, episode, mocker):
    audio = episode.podcast_audio
    transcript = create_transcript(audio=audio, podlove={"transcripts": [{"speaker": "Speaker 1"}]})
    submit = mocker.Mock(return_value=TranscriptSubmission("synthetic", "https://media.example/a", "test", {}))
    mocker.patch(
        "cast.voxhelm.service.VoxhelmTranscriptService",
        return_value=SimpleNamespace(client=SimpleNamespace(diarization_enabled=False), submit_for_audio=submit),
    )
    task = mocker.patch("cast.voxhelm.service._resolve_completion_task").return_value
    return audio, transcript, submit, task


@pytest.mark.parametrize("target", ["audio", "episode"])
@pytest.mark.parametrize("change", ["mapping", "corrections", "audio", "duration", "transcript", "deleted", "attempt"])
def test_stale_confirmation_cannot_submit(admin_client, episode, confirmation, target, change):
    audio, transcript, submit, task = confirmation
    url = reverse(f"cast-voxhelm:generate_{target}", args=(audio.pk if target == "audio" else episode.pk,))
    response = admin_client.get(url)
    token = response.context.get("regeneration_token", "")
    if change == "mapping":
        transcript.speaker_mappings.update(display_name="New synthetic name", review_state="approved")
    elif change == "corrections":
        transcript.corrections.save("changed.json", ContentFile(b'{"decisions": [{"decision": "approved"}]}'))
    elif change == "audio":
        Audio.objects.filter(pk=audio.pk).update(m4a="audio/synthetic-new.m4a")
    elif change == "duration":
        Audio.objects.filter(pk=audio.pk).update(duration=timedelta(seconds=99))
    elif change == "transcript":
        transcript.delete()
        create_transcript(audio=audio)
    elif change == "deleted":
        transcript.delete()
    else:
        TranscriptGeneration.objects.create(audio=audio, task_ref="other")
    response = admin_client.post(url, {"confirm_regeneration": "yes", "regeneration_token": token})
    assert response.status_code == 409
    submit.assert_not_called()
    task.enqueue.assert_not_called()


@pytest.mark.parametrize("token", ["", "tampered"])
def test_confirmation_requires_signed_evidence(admin_client, confirmation, token):
    audio, _, submit, _ = confirmation
    url = reverse("cast-voxhelm:generate_audio", args=(audio.pk,))
    assert admin_client.post(url, {"confirm_regeneration": "yes", "regeneration_token": token}).status_code == 409
    submit.assert_not_called()


def test_unchanged_confirmation_queues_once(admin_client, confirmation, django_capture_on_commit_callbacks):
    audio, _, submit, task = confirmation
    url = reverse("cast-voxhelm:generate_audio", args=(audio.pk,))
    response = admin_client.get(url)
    data = {"confirm_regeneration": "yes", "regeneration_token": response.context.get("regeneration_token", "")}
    with django_capture_on_commit_callbacks(execute=True):
        assert admin_client.post(url, data).status_code == 302
    assert submit.call_count == task.enqueue.call_count == 1
    generation = TranscriptGeneration.objects.get(audio=audio)
    generation.mark_succeeded()
    assert admin_client.post(url, data).status_code == 409
    assert submit.call_count == 1


def test_first_generation_needs_no_replacement_consent(admin_client, confirmation, django_capture_on_commit_callbacks):
    audio, transcript, submit, task = confirmation
    transcript.delete()
    url = reverse("cast-voxhelm:generate_audio", args=(audio.pk,))
    with django_capture_on_commit_callbacks(execute=True):
        assert admin_client.post(url).status_code == 302
    assert submit.call_count == task.enqueue.call_count == 1


def test_failed_confirmed_submission_keeps_failed_generation(admin_client, confirmation):
    audio, _, submit, task = confirmation
    submit.side_effect = VoxhelmError("synthetic upstream failure")
    url = reverse("cast-voxhelm:generate_audio", args=(audio.pk,))
    token = admin_client.get(url).context.get("regeneration_token", "")
    assert admin_client.post(url, {"confirm_regeneration": "yes", "regeneration_token": token}).status_code == 302
    generation = TranscriptGeneration.objects.get(audio=audio)
    assert generation.status == TranscriptGeneration.Status.FAILED
    assert generation.error_message == "synthetic upstream failure"
    task.enqueue.assert_not_called()


@pytest.mark.django_db(transaction=True)
def test_admin_submission_runs_outside_consent_locks_and_reports_enqueue_failure(episode, confirmation):
    audio, transcript, submit, task = confirmation
    transcript.delete()
    in_atomic = []
    submit.side_effect = lambda *args, **kwargs: (
        in_atomic.append(transaction.get_connection().in_atomic_block)
        or TranscriptSubmission("synthetic", "https://media.example/a", "test", {})
    )
    task.enqueue.side_effect = RuntimeError("synthetic task backend failure")
    with pytest.raises(RuntimeError, match="synthetic task backend failure"):
        enqueue_audio_transcript_generation(audio=audio, regeneration_token="")
    assert in_atomic == [False]
    generation = TranscriptGeneration.objects.get(audio=audio)
    assert generation.status == TranscriptGeneration.Status.FAILED
    assert generation.error_message == "synthetic task backend failure"


def test_replayed_confirmation_during_submission_cannot_submit_again(admin_client, confirmation):
    audio, _, submit, task = confirmation
    url = reverse("cast-voxhelm:generate_audio", args=(audio.pk,))
    TranscriptGeneration.objects.create(audio=audio, task_ref="old", status=TranscriptGeneration.Status.SUCCEEDED)
    token = admin_client.get(url).context.get("regeneration_token", "")
    replays = []

    def submit_and_replay(*args, **kwargs):
        if not replays:
            # A double-click arrives after the first request released its locks.
            with pytest.raises(StaleRegenerationConfirmation):
                replays.append(enqueue_audio_transcript_generation(audio=audio, regeneration_token=token))
            replays.append("refused")
        return TranscriptSubmission("synthetic", "https://media.example/a", "test", {})

    submit.side_effect = submit_and_replay
    assert admin_client.post(url, {"confirm_regeneration": "yes", "regeneration_token": token}).status_code == 302
    assert replays == ["refused"]
    assert submit.call_count == 1
    assert TranscriptGeneration.objects.get(audio=audio).status == TranscriptGeneration.Status.QUEUED


def test_concurrent_checked_replay_loses_the_consent_claim(admin_client, confirmation, mocker):
    audio, _, submit, task = confirmation
    url = reverse("cast-voxhelm:generate_audio", args=(audio.pk,))
    TranscriptGeneration.objects.create(audio=audio, task_ref="old", status=TranscriptGeneration.Status.SUCCEEDED)
    token = admin_client.get(url).context.get("regeneration_token", "")
    original_task_ref = service_module.resolve_audio_task_ref
    replays = []

    def task_ref_and_replay(*args, **kwargs):
        if not replays:
            # Both requests passed the locked check and the active-row check.
            # The replay claims first; its failed submission leaves the row inactive.
            replays.append(None)
            submit.side_effect = VoxhelmError("synthetic replay failure")
            with pytest.raises(VoxhelmError):
                enqueue_audio_transcript_generation(audio=audio, regeneration_token=token)
            submit.side_effect = None
        return original_task_ref(*args, **kwargs)

    mocker.patch("cast.voxhelm.service.resolve_audio_task_ref", side_effect=task_ref_and_replay)
    with pytest.raises(StaleRegenerationConfirmation):
        enqueue_audio_transcript_generation(audio=audio, regeneration_token=token)
    assert submit.call_count == 1
    assert TranscriptGeneration.objects.get(audio=audio).status == TranscriptGeneration.Status.FAILED
    task.enqueue.assert_not_called()


def test_consent_claim_is_a_single_compare_and_swap(audio):
    generation = TranscriptGeneration.objects.create(
        audio=audio, task_ref="old", status=TranscriptGeneration.Status.SUCCEEDED
    )
    reviewed = _ReviewedAttempt(str(generation.attempt_id))
    _consume_consent(generation, created=False, consent=reviewed)
    claimed = generation.attempt_id
    assert str(claimed) != reviewed.attempt_id
    assert TranscriptGeneration.objects.get(pk=generation.pk).attempt_id == claimed
    for consent in (reviewed, _ReviewedAttempt(None)):
        with pytest.raises(StaleRegenerationConfirmation):
            _consume_consent(generation, created=False, consent=consent)
    assert TranscriptGeneration.objects.get(pk=generation.pk).attempt_id == claimed
    _consume_consent(generation, created=True, consent=reviewed)
    _consume_consent(generation, created=False, consent=None)
    assert TranscriptGeneration.objects.get(pk=generation.pk).attempt_id == claimed


def test_configuration_error_leaves_confirmation_unused(admin_client, confirmation, mocker):
    audio, _, submit, task = confirmation
    url = reverse("cast-voxhelm:generate_audio", args=(audio.pk,))
    generation = TranscriptGeneration.objects.create(
        audio=audio, task_ref="old", status=TranscriptGeneration.Status.SUCCEEDED
    )
    token = admin_client.get(url).context.get("regeneration_token", "")
    data = {"confirm_regeneration": "yes", "regeneration_token": token}
    resolve = mocker.patch(
        "cast.voxhelm.service._resolve_completion_task", side_effect=ImproperlyConfigured("synthetic missing backend")
    )
    assert admin_client.post(url, data).status_code == 302
    generation.refresh_from_db()
    assert submit.call_count == 0
    attempt = generation.attempt_id
    resolve.side_effect = None
    resolve.return_value = task
    assert admin_client.post(url, data).status_code == 302
    generation.refresh_from_db()
    assert submit.call_count == 1
    assert generation.attempt_id != attempt
    assert generation.status == TranscriptGeneration.Status.QUEUED


def test_oversized_transcript_can_still_be_replaced(admin_client, confirmation, mocker):
    audio, _, submit, _ = confirmation
    mocker.patch("cast.transcripts.parsing.MAX_TRANSCRIPT_FINGERPRINT_ARTIFACT_BYTES", 1)
    mocker.patch("cast.transcripts.parsing.MAX_TRANSCRIPT_FINGERPRINT_TOTAL_BYTES", 1)
    url = reverse("cast-voxhelm:generate_audio", args=(audio.pk,))
    response = admin_client.get(url)
    assert response.status_code == 200
    data = {"confirm_regeneration": "yes", "regeneration_token": response.context.get("regeneration_token", "")}
    assert admin_client.post(url, data).status_code == 302
    assert submit.call_count == 1
