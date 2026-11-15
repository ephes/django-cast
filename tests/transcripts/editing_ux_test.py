"""Regressions for the Wagtail transcript editing journey."""

from types import SimpleNamespace

import pytest
from django.urls import reverse

from cast.devdata import create_transcript
from cast.forms import SpeakerContributorMappingForm
from cast.models import TranscriptGeneration, TranscriptSpeakerMapping
from cast.transcripts.editing import get_speaker_mapping_context

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("target", ["episode", "audio"])
def test_regeneration_requires_confirmation(admin_client, episode, mocker, target):
    transcript = create_transcript(audio=episode.podcast_audio, podlove={"transcripts": [{"speaker": "Speaker 1"}]})
    mapping = transcript.speaker_mappings.get()
    mapping.display_name = "Former name"
    mapping.review_state = TranscriptSpeakerMapping.ReviewState.APPROVED
    mapping.save()
    target_id = episode.pk if target == "episode" else episode.podcast_audio_id
    url = reverse(f"cast-voxhelm:generate_{target}", args=(target_id,))
    generation = TranscriptGeneration.objects.create(audio=episode.podcast_audio, task_ref="test")
    enqueue = mocker.patch(
        "cast.views.voxhelm.enqueue_audio_transcript_generation",
        return_value=SimpleNamespace(generation=generation, enqueued=True),
    )
    response = admin_client.get(url)
    assert response.status_code == 200
    assert "Former name" in response.content.decode()
    assert "confirm_regeneration" in response.content.decode()
    enqueue.assert_not_called()
    assert admin_client.post(url).status_code == 400
    enqueue.assert_not_called()
    assert admin_client.post(url, {"confirm_regeneration": "yes"}).status_code == 302
    enqueue.assert_called_once()


@pytest.mark.parametrize("display_name", ["Former name", ""])
def test_stale_mapping_is_not_preselected_or_reapproved(client, episode, display_name):
    transcript = create_transcript(audio=episode.podcast_audio, podlove={"transcripts": [{"speaker": "Speaker 1"}]})
    mapping = transcript.speaker_mappings.get()
    mapping.display_name = display_name
    mapping.review_state = TranscriptSpeakerMapping.ReviewState.STALE
    mapping.save()
    context = get_speaker_mapping_context(transcript)
    form = SpeakerContributorMappingForm(**context)
    assert not form["speaker_0"].value()
    assert not form["speaker_display_name_0"].value()
    form = SpeakerContributorMappingForm(
        {"action": "map-speakers", "speaker_0": "", "speaker_display_name_0": ""}, **context
    )
    assert form.is_valid()
    assert form.save() == 0
    mapping.refresh_from_db()
    assert mapping.review_state == TranscriptSpeakerMapping.ReviewState.STALE
    assert mapping.display_name == display_name
    data = client.get(reverse("cast:podlove-transcript-json", args=(transcript.pk,))).json()
    assert not data["transcripts"][0].get("speaker")


@pytest.mark.parametrize("target", ["episode", "audio"])
def test_generation_get_without_transcript_does_not_enqueue(admin_client, episode, mocker, target):
    target_id = episode.pk if target == "episode" else episode.podcast_audio_id
    enqueue = mocker.patch("cast.views.voxhelm.enqueue_audio_transcript_generation")
    response = admin_client.get(reverse(f"cast-voxhelm:generate_{target}", args=(target_id,)))
    assert response.status_code == 302
    enqueue.assert_not_called()


def test_editor_api_explicit_post_still_regenerates(api_client, admin_user, episode, mocker):
    create_transcript(audio=episode.podcast_audio)
    api_client.force_authenticate(user=admin_user)
    generation = TranscriptGeneration.objects.create(audio=episode.podcast_audio, task_ref="test")
    enqueue = mocker.patch(
        "cast.api.editor.transcripts.enqueue_audio_transcript_generation",
        return_value=SimpleNamespace(generation=generation, enqueued=True),
    )
    response = api_client.post(reverse("cast:api:editor_episode_transcript", args=(episode.pk,)), {}, format="json")
    assert response.status_code == 202
    enqueue.assert_called_once()
