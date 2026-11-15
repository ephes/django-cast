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


def test_transcript_title_back_link_search_and_save(admin_client, episode):
    transcript = create_transcript(audio=episode.podcast_audio, podlove={"transcripts": [{"speaker": "Speaker 1"}]})
    edit_url = reverse("cast-transcript:edit", args=(transcript.pk,))
    content = admin_client.get(edit_url).content.decode()
    assert f"Transcript: {episode.title}" in content
    assert reverse("wagtailadmin_pages:edit", args=(episode.pk,)) in content
    response = admin_client.post(edit_url, {"audio": episode.podcast_audio_id, "collection": transcript.collection_id})
    assert response.status_code == 302
    assert response.url == edit_url
    content = admin_client.get(reverse("cast-transcript:index"), {"q": episode.title}).content.decode()
    assert edit_url in content
    assert "Voices named" in content
    assert "Files" in content


def test_transcript_list_query_count_is_constant(admin_client, episode, django_assert_num_queries):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    from cast.models import Audio, Transcript

    create_transcript(audio=episode.podcast_audio)
    url = reverse("cast-transcript:index")
    admin_client.get(url)  # warm content types and Wagtail caches
    with CaptureQueriesContext(connection) as first:
        admin_client.get(url)
    for index in range(19):
        Transcript.objects.create(audio=Audio.objects.create(title=f"Other {index}", user=episode.owner))
    with CaptureQueriesContext(connection) as second:
        response = admin_client.get(url)
    assert response.status_code == 200
    assert len(second) == len(first)


def test_transcript_title_falls_back_to_audio_and_links_all_episodes(admin_client, episode):
    from cast.models import Audio

    audio = Audio.objects.create(title="Standalone audio", user=episode.owner)
    transcript = create_transcript(audio=audio)
    url = reverse("cast-transcript:edit", args=(transcript.pk,))
    assert "Transcript: Standalone audio" in admin_client.get(url).content.decode()
    episode.podcast_audio = audio
    episode.save()
    from tests.factories import EpisodeFactory

    unpublished_episode = EpisodeFactory(
        parent=episode.get_parent(),
        owner=episode.owner,
        podcast_audio=audio,
        title="Second episode",
        slug="second-episode",
    )
    content = admin_client.get(url).content.decode()
    for item in (episode, unpublished_episode):
        assert reverse("wagtailadmin_pages:edit", args=(item.pk,)) in content


def test_long_segment_review_is_paged_and_preserves_other_pages(admin_client, episode):
    from cast.transcripts.services import artifact_revision
    from tests.known_speaker_apply_test import make_transcript

    transcript = make_transcript(
        episode.podcast_audio,
        podlove={
            "transcripts": [
                {"start_ms": index * 3000, "text": "Passage", "speaker": "Speaker 1"} for index in range(1200)
            ]
        },
        speakers={
            "segments": [{"start": index * 3.0, "speaker": None, "speaker_uncertain": True} for index in range(1200)]
        },
    )
    url = reverse("cast-transcript:edit", args=(transcript.pk,))
    response = admin_client.get(url)
    assert len(response.content) < 300_000
    form = response.context["known_speaker_review_form"]
    assert len(form.segment_field_names) == 50
    data = {name: field.initial for name, field in form.fields.items()}
    data["artifact_revision"] = artifact_revision(transcript)
    data["known_speaker_segment_0"] = "__blank__"
    assert len(data) < 100
    assert admin_client.post(url, data).status_code == 302
    transcript.refresh_from_db()
    response = admin_client.get(url, {"review_page": 2})
    form = response.context["known_speaker_review_form"]
    assert min(form.segment_field_names.values()) == 50
    data = {name: field.initial for name, field in form.fields.items()}
    data["artifact_revision"] = artifact_revision(transcript)
    data["known_speaker_segment_50"] = "__blank__"
    assert admin_client.post(url + "?review_page=2", data).status_code == 302
    transcript.refresh_from_db()
    segments = transcript.get_speaker_suggestions()
    assert segments[0]["editor_decision"] == {"action": "reject", "speaker": ""}
    assert segments[50]["editor_decision"] == {"action": "reject", "speaker": ""}
    assert "editor_decision" not in segments[100]


def test_segment_review_filter_and_missing_post_fields(admin_client, episode):
    from cast.forms import KnownSpeakerSegmentReviewForm
    from tests.known_speaker_apply_test import make_transcript

    segments = [
        {"start": 0, "speaker": "Host"},
        {"start": 1, "speaker": "Host", "low_margin": True},
        {"start": 2, "speaker": None},
        {"start": 3, "speaker": "Host", "editor_decision": {"action": "approve", "speaker": "Host"}},
    ]
    transcript = make_transcript(episode.podcast_audio, speakers={"segments": segments})
    url = reverse("cast-transcript:edit", args=(transcript.pk,))
    response = admin_client.get(url)
    assert list(response.context["known_speaker_review_form"].segment_field_names.values()) == [1, 2, 3]
    response = admin_client.get(url, {"review_filter": "all", "review_page": "bad"})
    assert len(response.context["known_speaker_review_form"].segment_field_names) == 4
    form = KnownSpeakerSegmentReviewForm(
        {"action": "review-known-speakers"}, segments=segments, contributor_assignments=[], segment_positions=[3]
    )
    assert form.is_valid()
    assert form.segment_decisions == {}


@pytest.mark.parametrize("state", [None, "queued", "running", "failed", "succeeded", "interrupted"])
def test_generation_status_json(admin_client, episode, state):
    from datetime import timedelta

    from django.utils import timezone

    create_transcript(audio=episode.podcast_audio)
    if state is not None:
        generation = TranscriptGeneration.objects.create(
            audio=episode.podcast_audio,
            task_ref="test",
            status="running" if state == "interrupted" else state,
            error_message="Upstream failure" if state == "failed" else "",
        )
        if state == "interrupted":
            TranscriptGeneration.objects.filter(pk=generation.pk).update(updated_at=timezone.now() - timedelta(days=1))
    response = admin_client.get(reverse("cast-voxhelm:status_audio", args=(episode.podcast_audio_id,)))
    assert response.status_code == 200
    data = response.json()
    assert data["transcript_generation_active"] == (state in {"queued", "running"})
    assert data["transcript_generation_status"] == (state.capitalize() if state else "")
    if state == "succeeded":
        assert data["transcript_generation_transcript_url"]
    if state == "failed":
        assert data["transcript_generation_error"] == "Upstream failure"


def test_status_denies_audio_change_without_permission(rf, user, audio):
    from django.core.exceptions import PermissionDenied

    from cast.views.voxhelm import audio_transcript_status

    request = rf.get("/")
    request.user = user
    with pytest.raises(PermissionDenied):
        audio_transcript_status(request, audio.pk)


def test_generation_readiness_uses_draft_contributors_and_audio_override(admin_client, episode, settings, mocker):
    from cast.models import Audio, Contributor, EpisodeContributor

    settings.CAST_VOXHELM_API_BASE = "https://voxhelm.example"
    settings.CAST_VOXHELM_API_KEY = "secret"
    settings.CAST_VOXHELM_DIARIZATION_ENABLED = False
    settings.CAST_VOXHELM_KNOWN_SPEAKER_ENABLED = True
    host = Contributor.objects.create(display_name="Host", slug="host")
    guest = Contributor.objects.create(display_name="Missing Guest", slug="missing-guest")
    episode.contributor_assignments.add(
        EpisodeContributor(contributor=host, role="host"), EpisodeContributor(contributor=guest, role="guest")
    )
    episode.save_revision()
    audio = episode.podcast_audio
    audio.transcript_diarization_mode = Audio.TranscriptDiarizationMode.ENABLED
    audio.save(update_fields=["transcript_diarization_mode"], duration=False, cache_file_sizes=False)
    build = mocker.patch("cast.views.voxhelm.build_known_speaker_references", return_value=[{"id": str(host.pk)}])
    content = admin_client.get(reverse("wagtailadmin_pages:edit", args=(episode.pk,))).content.decode()
    assert "Speaker detection: on" in content
    assert "1 of 2" in content
    assert "Missing Guest" in content
    assert build.call_args.args[0].pk == episode.pk


def test_failed_resubmission_replaces_previous_success(audio, site, mocker):
    from cast.voxhelm import VoxhelmError, enqueue_audio_transcript_generation
    from tests.voxhelm.stale_recovery_test import mock_resubmission

    generation = TranscriptGeneration.objects.create(audio=audio, status="succeeded", task_ref="test")
    service, _ = mock_resubmission(mocker, audio)
    service.submit_for_audio.side_effect = VoxhelmError("Submission failed")
    with pytest.raises(VoxhelmError, match="Submission failed"):
        enqueue_audio_transcript_generation(audio=audio, request_or_site=site)
    generation.refresh_from_db()
    assert generation.status == "failed"
    assert generation.error_message == "Submission failed"


def test_invalid_generation_readiness_is_visible(rf, episode, settings):
    from cast.views.voxhelm import get_generation_readiness

    settings.CAST_VOXHELM_DIARIZATION_ENABLED = "not-a-boolean"
    context = get_generation_readiness(request=rf.get("/"), audio=episode.podcast_audio, episode=episode)
    assert "CAST_VOXHELM_DIARIZATION_ENABLED" in context["readiness_error"]


def test_stale_contributor_mapping_shows_former_name_and_stays_private(admin_client, client, episode):
    from cast.models import Contributor, EpisodeContributor

    host = Contributor.objects.create(display_name="Previous Host", slug="previous-host")
    EpisodeContributor.objects.create(episode=episode, contributor=host, role="host")
    episode.save_revision()
    transcript = create_transcript(
        audio=episode.podcast_audio, podlove={"transcripts": [{"speaker": "Speaker 1", "text": "Changed voice"}]}
    )
    transcript.speaker_mappings.update(contributor=host, review_state="stale")
    url = reverse("cast-transcript:edit", args=(transcript.pk,))
    response = admin_client.get(url)
    assert not response.context["speaker_mapping_form"]["speaker_0"].value()
    assert "Before the transcript changed: Previous Host." in response.content.decode()
    assert (
        admin_client.post(url, {"action": "map-speakers", "speaker_0": "", "speaker_display_name_0": ""}).status_code
        == 302
    )
    mapping = transcript.speaker_mappings.get()
    assert mapping.contributor == host
    assert mapping.review_state == "stale"
    assert (
        not client.get(reverse("cast:podlove-transcript-json", args=(transcript.pk,)))
        .json()["transcripts"][0]
        .get("speaker")
    )


def test_episode_hub_does_not_open_transcript_artifacts(admin_client, episode, mocker):
    transcript = create_transcript(
        audio=episode.podcast_audio,
        podlove={"transcripts": [{"speaker": "Speaker 1"}]},
        vtt="WEBVTT\n",
        dote={"lines": []},
    )
    opened = mocker.patch.object(
        transcript.podlove.storage, "open", side_effect=AssertionError("Panel must not read files")
    )
    response = admin_client.get(reverse("wagtailadmin_pages:edit", args=(episode.pk,)))
    assert response.status_code == 200
    assert "0 of 1 voices named" in response.content.decode()
    opened.assert_not_called()


def test_browser_stub_completes_real_generation_import(episode, mocker):
    from django.test import TestCase

    from cast.voxhelm import enqueue_audio_transcript_generation
    from tests.transcript_admin_browser_test import BrowserVoxhelmClient

    transcript = create_transcript(
        audio=episode.podcast_audio, podlove={"transcripts": [{"speaker": "Speaker 1", "text": "Original"}]}
    )
    transcript.speaker_mappings.update(display_name="Former Host", review_state="approved")
    mocker.patch("cast.voxhelm.service.VoxhelmClient.from_settings", return_value=BrowserVoxhelmClient())
    mocker.patch("cast.voxhelm.service.resolve_audio_source_url", return_value="https://media.example/audio.m4a")
    with TestCase.captureOnCommitCallbacks(execute=True):
        result = enqueue_audio_transcript_generation(audio=episode.podcast_audio, episode=episode)
    result.generation.refresh_from_db()
    assert result.generation.status == "succeeded"
    transcript.refresh_from_db()
    assert transcript.podlove_data["transcripts"][0]["text"] == "Regenerated"
    assert transcript.speaker_mappings.get().review_state == "stale"
