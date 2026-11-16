"""Synthetic consent generations for destructive admin regeneration."""

from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.core.files.base import ContentFile
from django.urls import reverse

from cast.devdata import create_transcript
from cast.models import Audio, TranscriptGeneration
from cast.voxhelm import TranscriptSubmission

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
