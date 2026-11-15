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


def test_episode_transcript_hub_and_upload_initial(admin_client, episode, settings):
    settings.CAST_VOXHELM_API_BASE = "https://voxhelm.example"
    settings.CAST_VOXHELM_API_KEY = "secret"
    url = reverse("wagtailadmin_pages:edit", args=(episode.pk,))
    content = admin_client.get(url).content.decode()
    upload = reverse("cast-transcript:add") + f"?audio={episode.podcast_audio_id}"
    assert upload in content
    assert "Upload transcript files" in content
    response = admin_client.get(upload)
    assert str(response.context["form"]["audio"].value()) == str(episode.podcast_audio_id)
    transcript = create_transcript(audio=episode.podcast_audio, podlove={"transcripts": [{"speaker": "Speaker 1"}]})
    content = admin_client.get(url).content.decode()
    assert "0 of 1 voices named" in content
    assert reverse("cast-transcript:edit", args=(transcript.pk,)) in content
    from cast.models import Episode

    panels = Episode.content_panels
    index = next(i for i, panel in enumerate(panels) if getattr(panel, "field_name", "") == "podcast_audio")
    assert str(panels[index + 1].heading) == "Contributors"
    assert panels[index + 1].classname != "collapsed"


def test_hub_counts_use_materialized_mappings_without_file_reads(episode, mocker):
    from cast.transcripts.generation_status import transcript_voice_counts

    transcript = create_transcript(audio=episode.podcast_audio, podlove={"transcripts": [{"speaker": "Speaker 1"}]})
    opened = mocker.patch.object(
        transcript.podlove.storage, "open", side_effect=AssertionError("No file reads in panel")
    )
    assert transcript_voice_counts(transcript) == {"named": 0, "total": 1}
    opened.assert_not_called()


def test_hub_without_audio_or_configuration(admin_client, unpublished_episode_without_audio, settings, monkeypatch):
    settings.CAST_VOXHELM_API_BASE = ""
    settings.CAST_VOXHELM_API_KEY = ""
    monkeypatch.delenv("CAST_VOXHELM_API_BASE", raising=False)
    monkeypatch.delenv("CAST_VOXHELM_API_KEY", raising=False)
    content = admin_client.get(
        reverse("wagtailadmin_pages:edit", args=(unpublished_episode_without_audio.pk,))
    ).content.decode()
    assert "Choose the podcast audio and save first." in content


@pytest.mark.parametrize("state", ["queued", "running", "failed", "succeeded"])
def test_hub_generation_states(admin_client, episode, state):
    TranscriptGeneration.objects.create(
        audio=episode.podcast_audio,
        task_ref="test",
        status=state,
        error_message="Problem" if state == "failed" else "",
    )
    content = admin_client.get(reverse("wagtailadmin_pages:edit", args=(episode.pk,))).content.decode()
    assert state.capitalize() in content
    if state in {"queued", "running"}:
        assert "Upload transcript files" not in content
    if state == "failed":
        assert "Problem" in content


def test_hub_counts_only_current_approvals(episode):
    from cast.transcripts.generation_status import transcript_voice_counts

    transcript = create_transcript(
        audio=episode.podcast_audio, podlove={"transcripts": [{"speaker": "Speaker 1"}, {"speaker": "Speaker 2"}]}
    )
    mapping = transcript.speaker_mappings.first()
    mapping.display_name = "Host"
    mapping.review_state = TranscriptSpeakerMapping.ReviewState.APPROVED
    mapping.save()
    assert transcript_voice_counts(transcript) == {"named": 1, "total": 2}
    mapping.source_artifact_fingerprint = "outdated"
    mapping.save()
    assert transcript_voice_counts(transcript) == {"named": 0, "total": 2}
