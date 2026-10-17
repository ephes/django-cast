import pytest
from django.contrib.auth.models import AnonymousUser
from django.test import Client
from django.urls import reverse

from cast.devdata import create_transcript
from cast.models import Contributor, Episode, EpisodeContributor
from cast.transcript_sanitization import editor_speaker_preview_episode
from tests.factories import UserFactory

PODLOVE = {
    "transcripts": [
        {"start": "00:00:00.000", "end": "00:00:01.000", "speaker": "Draft Host", "voice": "Draft Host", "text": "A"},
        {"start": "00:00:01.000", "end": "00:00:02.000", "speaker": "Speaker 2", "voice": "Speaker 2", "text": "B"},
    ]
}
DOTE = {
    "lines": [
        {"startTime": "00:00:00,000", "endTime": "00:00:01,000", "speakerDesignation": "Draft Host", "text": "A"},
        {"startTime": "00:00:01,000", "endTime": "00:00:02,000", "speakerDesignation": "Speaker 2", "text": "B"},
    ]
}
VTT = "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\n<v Draft Host>A</v>\n\n00:00:01.000 --> 00:00:02.000\n<v Speaker 2>B</v>\n"


def assign_draft_host(episode):
    """Credit a contributor on the latest revision only, like an unpublished admin or API edit."""
    contributor = Contributor.objects.create(display_name="Draft Host", slug="draft-host")
    episode.contributor_assignments.add(
        EpisodeContributor(contributor=contributor, role=EpisodeContributor.ROLE_HOST, sort_order=0)
    )
    episode.save_revision()
    EpisodeContributor.objects.filter(episode=episode).delete()
    return contributor


@pytest.fixture
def draft_episode(episode):
    episode.live = False
    episode.save(update_fields=["live"])
    assign_draft_host(episode)
    return episode


@pytest.fixture
def draft_transcript(draft_episode):
    return create_transcript(audio=draft_episode.podcast_audio, podlove=PODLOVE, dote=DOTE, vtt=VTT)


class TestEditorSpeakerPreviewEpisode:
    pytestmark = pytest.mark.django_db

    def test_returns_marked_latest_revision_for_an_editor(self, draft_episode, admin_user):
        preview = editor_speaker_preview_episode(draft_episode, admin_user)
        assert preview is not None
        assert preview.pk == draft_episode.pk
        assert [assignment.contributor.slug for assignment in preview.visible_contributor_assignments] == [
            "draft-host"
        ]

    def test_returns_none_outside_editor_draft_previews(self, draft_episode, episode, post, admin_user):
        assert editor_speaker_preview_episode(None, admin_user) is None
        assert editor_speaker_preview_episode(post, admin_user) is None
        assert editor_speaker_preview_episode(draft_episode, None) is None
        assert editor_speaker_preview_episode(draft_episode, AnonymousUser()) is None
        assert editor_speaker_preview_episode(draft_episode, UserFactory(is_staff=True)) is None
        draft_episode.live = True
        assert editor_speaker_preview_episode(draft_episode, admin_user) is None


class TestEditorDraftSpeakerLabels:
    pytestmark = pytest.mark.django_db

    def test_transcript_endpoints_show_draft_speaker_names_to_editors(
        self, admin_client, draft_episode, draft_transcript
    ):
        query = {"episode_id": draft_episode.pk}

        podlove = admin_client.get(reverse("cast:podlove-transcript-json", kwargs={"pk": draft_transcript.pk}), query)
        assert podlove.status_code == 200
        assert podlove["Cache-Control"] == "private, no-store"
        segments = podlove.json()["transcripts"]
        assert segments[0]["speaker"] == "Draft Host"
        assert "speaker" not in segments[1]

        dote = admin_client.get(
            reverse("cast:podcastindex-transcript-json", kwargs={"pk": draft_transcript.pk}), query
        )
        assert dote.status_code == 200
        assert [segment["speaker"] for segment in dote.json()["segments"]] == ["Draft Host", ""]

        vtt = admin_client.get(reverse("cast:webvtt-transcript", kwargs={"pk": draft_transcript.pk}), query)
        assert vtt.status_code == 200
        content = vtt.content.decode()
        assert "<v Draft Host>A</v>" in content
        assert "Speaker 2" not in content

    def test_audio_podlove_and_player_endpoints_show_draft_speaker_names_to_editors(
        self, api_client, admin_user, draft_episode, draft_transcript
    ):
        audio = draft_episode.podcast_audio
        api_client.force_authenticate(user=admin_user)

        by_post = api_client.get(
            reverse("cast:api:audio_podlove_detail", kwargs={"pk": audio.pk, "post_id": draft_episode.pk})
        )
        assert by_post.status_code == 200
        assert by_post["Cache-Control"] == "private, no-store"
        assert by_post.json()["transcripts"][0]["speaker"] == "Draft Host"
        assert by_post.json()["contributors"] == [{"id": "Draft Host", "name": "Draft Host"}]

        by_episode_id = api_client.get(
            reverse("cast:api:audio_podlove_detail", kwargs={"pk": audio.pk}), {"episode_id": draft_episode.pk}
        )
        assert by_episode_id.status_code == 200
        assert by_episode_id.json()["transcripts"][0]["speaker"] == "Draft Host"

        player = api_client.get(
            reverse("cast:api:audio_player_transcript", kwargs={"pk": audio.pk}), {"post_id": draft_episode.pk}
        )
        assert player.status_code == 200
        assert player["Cache-Control"] == "private, no-store"
        assert [cue["speaker"] for cue in player.json()["cues"]] == ["Draft Host", ""]

    def test_live_episode_output_is_unchanged_for_editors(self, admin_client, episode):
        # The draft-only credit must not leak into the live episode's public labels.
        assign_draft_host(episode)
        transcript = create_transcript(audio=episode.podcast_audio, podlove=PODLOVE)

        response = admin_client.get(
            reverse("cast:podlove-transcript-json", kwargs={"pk": transcript.pk}), {"episode_id": episode.pk}
        )

        assert response.status_code == 200
        assert "speaker" not in response.json()["transcripts"][0]


class TestDraftOnlyAudioReference:
    pytestmark = pytest.mark.django_db

    def test_editor_reaches_audio_referenced_only_by_the_latest_draft(
        self, admin_client, api_client, admin_user, draft_episode
    ):
        from cast.devdata import create_audio

        new_audio = create_audio()
        draft = draft_episode.get_latest_revision_as_object()
        draft.podcast_audio = new_audio
        draft.save_revision()
        assert Episode.objects.get(pk=draft_episode.pk).podcast_audio_id != new_audio.pk
        transcript = create_transcript(audio=new_audio, podlove=PODLOVE)

        podlove = admin_client.get(
            reverse("cast:podlove-transcript-json", kwargs={"pk": transcript.pk}), {"episode_id": draft_episode.pk}
        )
        assert podlove.status_code == 200
        assert podlove["Cache-Control"] == "private, no-store"
        assert podlove.json()["transcripts"][0]["speaker"] == "Draft Host"

        api_client.force_authenticate(user=admin_user)
        player = api_client.get(
            reverse("cast:api:audio_player_transcript", kwargs={"pk": new_audio.pk}), {"post_id": draft_episode.pk}
        )
        assert player.status_code == 200
        assert player["Cache-Control"] == "private, no-store"

        anonymous = Client().get(
            reverse("cast:podlove-transcript-json", kwargs={"pk": transcript.pk}), {"episode_id": draft_episode.pk}
        )
        assert anonymous.status_code == 404

    def test_live_page_draft_only_audio_stays_unreachable(self, admin_client, episode):
        from cast.devdata import create_audio

        new_audio = create_audio()
        draft = episode.get_latest_revision_as_object()
        draft.podcast_audio = new_audio
        draft.save_revision()
        transcript = create_transcript(audio=new_audio, podlove=PODLOVE)

        response = admin_client.get(
            reverse("cast:podlove-transcript-json", kwargs={"pk": transcript.pk}), {"episode_id": episode.pk}
        )

        assert response.status_code == 404
