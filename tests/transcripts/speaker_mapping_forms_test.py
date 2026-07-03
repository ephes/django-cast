# ruff: noqa: F401,F811,I001
import json
import re
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction
from django.test import override_settings
from django.template import TemplateDoesNotExist
from django.urls import reverse
from django.utils import translation

from cast.devdata import create_transcript
from cast.views import transcript as transcript_views
from cast.forms import DRAFT_SPEAKER_ASSIGNMENT_PREFIX, SpeakerContributorMappingForm
from cast.models import Contributor, EpisodeContributor, Transcript, TranscriptSpeakerMapping
from cast.transcripts import parsing, speaker_samples, webvtt
from cast.views.transcript import (
    _resolve_transcript_template,
    get_speaker_mapping_context,
    get_transcript_audio_sources,
)

from tests.factories import BlogFactory, EpisodeFactory, UserFactory
from tests.multisite_helpers import create_site_root


def get_endpoint_urls_without_args():
    urls = {}
    view_names = ["index", "add", "chooser", "chooser_upload"]
    for view_name in view_names:
        urls[view_name] = reverse(f"cast-transcript:{view_name}")
    return urls


def get_endpoint_urls_with_args(transcript):
    urls = {}
    view_names = ["edit", "delete", "chosen"]
    for view_name in view_names:
        urls[view_name] = reverse(f"cast-transcript:{view_name}", args=(transcript.id,))
    return urls


class TranscriptUrls:
    def __init__(self, transcript):
        self.transcript = transcript
        self.urls = get_endpoint_urls_without_args()
        self.urls.update(get_endpoint_urls_with_args(transcript))

    def __getattr__(self, item):
        return self.urls[item]


@pytest.fixture
def transcript_urls(transcript):
    return TranscriptUrls(transcript)


class TestTranscriptSpeakerMapping:
    pytestmark = pytest.mark.django_db

    def test_speaker_mapping_form_maps_to_episode_contributor_display_name(self, episode):
        contributor = Contributor.objects.create(display_name="Alice", slug="alice")
        assignment = EpisodeContributor.objects.create(
            episode=episode,
            contributor=contributor,
            role=EpisodeContributor.ROLE_HOST,
        )
        form = SpeakerContributorMappingForm(
            {"action": "map-speakers", "speaker_0": str(assignment.pk)},
            speaker_labels=["Speaker 1"],
            contributor_assignments=[assignment],
        )

        assert form.is_valid()
        assert form.speaker_mapping == {"Speaker 1": "Alice"}
        assert form.fields["speaker_0"].choices == [("", "Unmapped"), (str(assignment.pk), "Alice (Host)")]

    def test_speaker_mapping_form_stores_one_off_display_name(self, episode):
        transcript = create_transcript(
            audio=episode.podcast_audio,
            podlove={"transcripts": [{"speaker": "Speaker 1", "voice": "Speaker 1", "text": "Hello"}]},
        )
        form = SpeakerContributorMappingForm(
            {"action": "map-speakers", "speaker_0": "", "speaker_display_name_0": "Guest Voice"},
            **get_speaker_mapping_context(transcript),
        )

        assert form.is_valid()
        assert form.speaker_mapping == {"Speaker 1": "Guest Voice"}
        assert form.save() == 1
        mapping = transcript.speaker_mappings.get(speaker_label="Speaker 1")
        assert mapping.contributor is None
        assert mapping.display_name == "Guest Voice"
        assert mapping.review_state == TranscriptSpeakerMapping.ReviewState.APPROVED

    def test_speaker_mapping_form_rejects_contributor_and_display_name(self, episode):
        contributor = Contributor.objects.create(display_name="Alice", slug="one-off-conflict-alice")
        assignment = EpisodeContributor.objects.create(
            episode=episode,
            contributor=contributor,
            role=EpisodeContributor.ROLE_HOST,
        )
        transcript = create_transcript(
            audio=episode.podcast_audio,
            podlove={"transcripts": [{"speaker": "Speaker 1", "voice": "Speaker 1", "text": "Hello"}]},
        )
        form = SpeakerContributorMappingForm(
            {"action": "map-speakers", "speaker_0": str(assignment.pk), "speaker_display_name_0": "Guest Voice"},
            **get_speaker_mapping_context(transcript),
        )

        assert not form.is_valid()
        assert "Use either a contributor or a display name." in form.errors["speaker_display_name_0"]

    def test_speaker_mapping_form_rejects_one_off_display_name_that_matches_raw_label(self, episode):
        transcript = create_transcript(
            audio=episode.podcast_audio,
            podlove={
                "transcripts": [
                    {"speaker": "Speaker 1", "text": "Hello"},
                    {"speaker": "Speaker 2", "text": "Raw label"},
                ]
            },
        )
        form = SpeakerContributorMappingForm(
            {"action": "map-speakers", "speaker_0": "", "speaker_display_name_0": "Speaker 2"},
            **get_speaker_mapping_context(transcript),
        )

        assert not form.is_valid()
        assert (
            "Use a display name that does not match a raw transcript speaker label."
            in form.errors["speaker_display_name_0"]
        )

    def test_speaker_mapping_form_saves_multiple_rows_with_one_fingerprint_read(self, episode, mocker):
        transcript = create_transcript(
            audio=episode.podcast_audio,
            podlove={
                "transcripts": [
                    {"speaker": "Speaker 1", "text": "Hello"},
                    {"speaker": "Speaker 2", "text": "Hi"},
                ]
            },
        )
        form = SpeakerContributorMappingForm(
            {
                "action": "map-speakers",
                "speaker_0": "",
                "speaker_display_name_0": "Guest One",
                "speaker_1": "",
                "speaker_display_name_1": "Guest Two",
            },
            **get_speaker_mapping_context(transcript),
        )
        fingerprint = transcript.transcript_artifact_fingerprint()
        fingerprint_mock = mocker.patch(
            "cast.models.transcript.Transcript.transcript_artifact_fingerprint",
            autospec=True,
            return_value=fingerprint,
        )

        assert form.is_valid()
        assert form.save() == 2
        assert fingerprint_mock.call_count == 1
        assert set(transcript.speaker_mappings.values_list("display_name", "source_artifact_fingerprint")) == {
            ("Guest One", fingerprint),
            ("Guest Two", fingerprint),
        }

    def test_speaker_mapping_form_handles_initial_values_duplicate_choices_and_compatibility_save(self, episode):
        contributor = Contributor.objects.create(display_name="Alice", slug="initial-mapping-alice")
        assignment = EpisodeContributor.objects.create(
            episode=episode,
            contributor=contributor,
            role=EpisodeContributor.ROLE_HOST,
        )
        transcript = create_transcript(
            audio=episode.podcast_audio,
            podlove={
                "transcripts": [
                    {"speaker": "Speaker 1", "voice": "Speaker 1", "text": "Hello"},
                    {"speaker": "Speaker 2", "voice": "Speaker 2", "text": "Hi"},
                ]
            },
        )
        speaker_one = transcript.speaker_mappings.get(speaker_label="Speaker 1")
        speaker_one.contributor = contributor
        speaker_one.review_state = TranscriptSpeakerMapping.ReviewState.APPROVED
        speaker_one.save()
        speaker_two = transcript.speaker_mappings.get(speaker_label="Speaker 2")
        speaker_two.display_name = "Guest Voice"
        speaker_two.review_state = TranscriptSpeakerMapping.ReviewState.APPROVED
        speaker_two.save()
        context = get_speaker_mapping_context(transcript)
        context["contributor_assignments"].append(assignment)

        form = SpeakerContributorMappingForm(**context)

        assert form.fields["speaker_0"].initial == str(assignment.pk)
        assert form.fields["speaker_display_name_1"].initial == "Guest Voice"
        assert form.fields["speaker_0"].choices == [("", "Unmapped"), (str(assignment.pk), "Alice (Host)")]

        compatibility_form = SpeakerContributorMappingForm(
            {"action": "map-speakers", "speaker_0": ""},
            speaker_labels=["Speaker X"],
            contributor_assignments=[],
        )
        assert compatibility_form.is_valid()
        assert compatibility_form.save() == 0

        fake_assignment = SimpleNamespace(
            pk=None,
            episode=SimpleNamespace(pk=episode.pk, title=episode.title),
            contributor_id=None,
            contributor=None,
            role=EpisodeContributor.ROLE_GUEST,
            display_name="No Contributor",
            get_role_display=lambda: "Guest",
        )
        fake_form = SpeakerContributorMappingForm(
            speaker_labels=["Speaker Y"],
            contributor_assignments=[fake_assignment],
        )
        assert fake_form.fields["speaker_0"].choices == [
            ("", "Unmapped"),
            (
                f"{DRAFT_SPEAKER_ASSIGNMENT_PREFIX}{episode.pk}:None:{EpisodeContributor.ROLE_GUEST}",
                "No Contributor (Guest)",
            ),
        ]

    def test_speaker_mapping_form_reports_tampered_contributor_choice(self, episode):
        contributor = Contributor.objects.create(display_name="Alice", slug="tampered-mapping-alice")
        assignment = EpisodeContributor.objects.create(
            episode=episode,
            contributor=contributor,
            role=EpisodeContributor.ROLE_HOST,
        )
        form = SpeakerContributorMappingForm(
            {"action": "map-speakers", "speaker_0": str(assignment.pk)},
            speaker_labels=["Speaker 1"],
            contributor_assignments=[assignment],
        )
        form.contributor_lookup.clear()

        assert not form.is_valid()
        assert "Select a valid contributor." in form.errors["speaker_0"]

    def test_speaker_mapping_form_labels_multiple_episodes(self, episode, podcast_episode_with_same_audio):
        alice = Contributor.objects.create(display_name="Alice", slug="alice")
        bob = Contributor.objects.create(display_name="Bob", slug="bob")
        first_assignment = EpisodeContributor.objects.create(
            episode=episode,
            contributor=alice,
            role=EpisodeContributor.ROLE_HOST,
        )
        second_assignment = EpisodeContributor.objects.create(
            episode=podcast_episode_with_same_audio,
            contributor=bob,
            role=EpisodeContributor.ROLE_GUEST,
        )
        transcript = create_transcript(
            audio=episode.podcast_audio,
            podlove={"transcripts": [{"speaker": "Speaker 1", "voice": "Speaker 1", "text": "Hello"}]},
        )

        context = get_speaker_mapping_context(transcript)
        form = SpeakerContributorMappingForm(**context)

        assert context["multiple_episodes"] is True
        assert context["contributor_assignments"] == [first_assignment, second_assignment]
        assert form.fields["speaker_0"].choices == [
            ("", "Unmapped"),
            (str(first_assignment.pk), f"Alice (Host) — {episode.title}"),
            (str(second_assignment.pk), f"Bob (Guest) — {podcast_episode_with_same_audio.title}"),
        ]

    def test_speaker_mapping_context_uses_draft_contributor_assignments(self, episode):
        contributor = Contributor.objects.create(display_name="Draft Host", slug="draft-host")
        episode.contributor_assignments.add(
            EpisodeContributor(
                contributor=contributor,
                role=EpisodeContributor.ROLE_HOST,
            )
        )
        episode.save_revision()
        transcript = create_transcript(
            audio=episode.podcast_audio,
            podlove={"transcripts": [{"speaker": "Speaker 1", "voice": "Speaker 1", "text": "Hello"}]},
        )

        context = get_speaker_mapping_context(transcript)
        form = SpeakerContributorMappingForm(**context)

        assert EpisodeContributor.objects.filter(episode=episode).count() == 0
        assert [assignment.display_name for assignment in context["contributor_assignments"]] == ["Draft Host"]
        assert context["contributor_assignments"][0].pk is None
        draft_value = f"{DRAFT_SPEAKER_ASSIGNMENT_PREFIX}{episode.pk}:{contributor.pk}:{EpisodeContributor.ROLE_HOST}"
        assert form.fields["speaker_0"].choices == [("", "Unmapped"), (draft_value, "Draft Host (Host)")]

    def test_speaker_mapping_context_uses_stable_draft_assignment_values_with_mixed_assignments(self, episode):
        saved_contributor = Contributor.objects.create(display_name="Saved Host", slug="saved-host")
        saved_assignment = EpisodeContributor.objects.create(
            episode=episode,
            contributor=saved_contributor,
            role=EpisodeContributor.ROLE_HOST,
            sort_order=0,
        )
        draft_contributor = Contributor.objects.create(display_name="Draft Guest", slug="draft-guest")
        hidden_contributor = Contributor.objects.create(
            display_name="Hidden Guest", slug="hidden-guest", visible=False
        )
        episode.contributor_assignments.add(
            EpisodeContributor(
                contributor=draft_contributor,
                role=EpisodeContributor.ROLE_GUEST,
                sort_order=1,
            )
        )
        episode.contributor_assignments.add(
            EpisodeContributor(
                contributor=hidden_contributor,
                role=EpisodeContributor.ROLE_GUEST,
                sort_order=2,
            )
        )
        episode.save_revision()
        transcript = create_transcript(
            audio=episode.podcast_audio,
            podlove={"transcripts": [{"speaker": "Speaker 1", "voice": "Speaker 1", "text": "Hello"}]},
        )

        form = SpeakerContributorMappingForm(**get_speaker_mapping_context(transcript))

        draft_value = (
            f"{DRAFT_SPEAKER_ASSIGNMENT_PREFIX}{episode.pk}:{draft_contributor.pk}:{EpisodeContributor.ROLE_GUEST}"
        )
        assert form.fields["speaker_0"].choices == [
            ("", "Unmapped"),
            (str(saved_assignment.pk), "Saved Host (Host)"),
            (draft_value, "Draft Guest (Guest)"),
        ]

    def test_post_speaker_mapping_uses_draft_contributor_assignments(self, admin_client, episode):
        contributor = Contributor.objects.create(display_name="Draft Host", slug="draft-host")
        episode.contributor_assignments.add(
            EpisodeContributor(
                contributor=contributor,
                role=EpisodeContributor.ROLE_HOST,
            )
        )
        episode.save_revision()
        transcript = create_transcript(
            audio=episode.podcast_audio,
            podlove={"transcripts": [{"speaker": "Speaker 1", "voice": "Speaker 1", "text": "Hello"}]},
        )
        edit_url = reverse("cast-transcript:edit", args=(transcript.pk,))

        draft_value = f"{DRAFT_SPEAKER_ASSIGNMENT_PREFIX}{episode.pk}:{contributor.pk}:{EpisodeContributor.ROLE_HOST}"

        response = admin_client.post(edit_url, {"action": "map-speakers", "speaker_0": draft_value})

        assert response.status_code == 302
        mapping = transcript.speaker_mappings.get(speaker_label="Speaker 1")
        assert mapping.contributor == contributor
        assert mapping.review_state == TranscriptSpeakerMapping.ReviewState.APPROVED
        with transcript.podlove.open("r") as podlove_file:
            assert json.load(podlove_file)["transcripts"][0]["speaker"] == "Speaker 1"

    def test_post_speaker_mapping_stores_mapping_without_rewriting_transcript_files(self, admin_client, episode):
        contributor = Contributor.objects.create(display_name="Alice", slug="alice")
        assignment = EpisodeContributor.objects.create(
            episode=episode,
            contributor=contributor,
            role=EpisodeContributor.ROLE_HOST,
        )
        transcript = create_transcript(
            audio=episode.podcast_audio,
            podlove={"transcripts": [{"speaker": "Speaker 1", "voice": "Speaker 1", "text": "Hello"}]},
            dote={"lines": [{"speakerDesignation": "Speaker 1", "text": "Hello"}]},
        )
        edit_url = reverse("cast-transcript:edit", args=(transcript.pk,))

        response = admin_client.post(edit_url, {"action": "map-speakers", "speaker_0": str(assignment.pk)})

        assert response.status_code == 302
        assert response.url == edit_url
        mapping = transcript.speaker_mappings.get(speaker_label="Speaker 1")
        assert mapping.contributor == contributor
        assert mapping.display_name == ""
        assert mapping.review_state == TranscriptSpeakerMapping.ReviewState.APPROVED
        assert mapping.source_artifact_fingerprint == transcript.transcript_artifact_fingerprint()
        assert mapping.reviewed_at is not None
        with transcript.podlove.open("r") as podlove_file:
            assert json.load(podlove_file)["transcripts"][0]["speaker"] == "Speaker 1"
        with transcript.dote.open("r") as dote_file:
            assert json.load(dote_file)["lines"][0]["speakerDesignation"] == "Speaker 1"

    def test_post_speaker_mapping_with_no_selected_contributor_keeps_labels(self, admin_client, episode):
        contributor = Contributor.objects.create(display_name="Alice", slug="alice")
        EpisodeContributor.objects.create(episode=episode, contributor=contributor, role=EpisodeContributor.ROLE_HOST)
        transcript = create_transcript(
            audio=episode.podcast_audio,
            podlove={"transcripts": [{"speaker": "Speaker 1", "voice": "Speaker 1", "text": "Hello"}]},
        )
        edit_url = reverse("cast-transcript:edit", args=(transcript.pk,))

        response = admin_client.post(edit_url, {"action": "map-speakers", "speaker_0": ""})

        assert response.status_code == 302
        mapping = transcript.speaker_mappings.get(speaker_label="Speaker 1")
        assert mapping.review_state == TranscriptSpeakerMapping.ReviewState.UNMAPPED
        assert mapping.contributor is None
        assert mapping.display_name == ""
        with transcript.podlove.open("r") as podlove_file:
            assert json.load(podlove_file)["transcripts"][0]["speaker"] == "Speaker 1"

    def test_post_speaker_mapping_invalid_form(self, admin_client, episode):
        contributor = Contributor.objects.create(display_name="Alice", slug="alice")
        EpisodeContributor.objects.create(episode=episode, contributor=contributor, role=EpisodeContributor.ROLE_HOST)
        transcript = create_transcript(
            audio=episode.podcast_audio,
            podlove={"transcripts": [{"speaker": "Speaker 1", "voice": "Speaker 1", "text": "Hello"}]},
        )
        edit_url = reverse("cast-transcript:edit", args=(transcript.pk,))

        response = admin_client.post(edit_url, {"action": "map-speakers", "speaker_0": "99999"})

        assert response.status_code == 200
        assert response.context["message"] == "The speaker labels could not be updated due to errors."

    def test_post_speaker_mapping_without_contributors_rejects_bypassed_disabled_button(self, admin_client, episode):
        transcript = create_transcript(
            audio=episode.podcast_audio,
            podlove={"transcripts": [{"speaker": "Speaker 1", "voice": "Speaker 1", "text": "Hello"}]},
        )
        edit_url = reverse("cast-transcript:edit", args=(transcript.pk,))

        response = admin_client.post(edit_url, {"action": "map-speakers", "speaker_0": "99999"})

        assert response.status_code == 200
        assert response.context["message"] == "The speaker labels could not be updated due to errors."
        with transcript.podlove.open("r") as podlove_file:
            assert json.load(podlove_file)["transcripts"][0]["speaker"] == "Speaker 1"

    def test_get_edit_transcript_renders_speaker_samples_and_audio_seek_controls(self, admin_client, audio):
        transcript = create_transcript(
            audio=audio,
            podlove={
                "transcripts": [
                    {
                        "speaker": "Speaker 1",
                        "start": "00:00:01.500",
                        "text": "This sample sentence is long enough to identify the diarized speaker.",
                    }
                ]
            },
        )
        edit_url = reverse("cast-transcript:edit", args=(transcript.pk,))

        with translation.override("de"):
            response = admin_client.get(edit_url)

        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert "cast-speaker-mapping__row" in content
        assert "This sample sentence is long enough to identify the diarized speaker." in content
        assert "data-cast-speaker-audio" in content
        assert 'type="audio/mp4"' in content
        assert 'data-cast-speaker-seek="1.5"' in content

    def test_get_edit_transcript_omits_audio_seek_controls_when_audio_file_is_missing(self, admin_client, audio):
        transcript = create_transcript(
            audio=audio,
            podlove={
                "transcripts": [
                    {
                        "speaker": "Speaker 1",
                        "start": "00:00:01.500",
                        "text": "This sample sentence is long enough to render without playable audio.",
                    }
                ]
            },
        )
        audio.m4a.storage.delete(audio.m4a.name)
        edit_url = reverse("cast-transcript:edit", args=(transcript.pk,))

        response = admin_client.get(edit_url)

        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert "This sample sentence is long enough to render without playable audio." in content
        assert "<audio controls" not in content
        assert 'data-cast-speaker-seek="1.5"' not in content
        assert "00:01" in content

    def test_get_transcript_audio_sources_skips_unplayable_fields(self):
        class MissingUrlField:
            name = "cast_audio/no-url.mp3"

        class ExistingStorage:
            def exists(self, name):
                return True

        class BrokenUrlField:
            name = "cast_audio/broken.m4a"
            storage = ExistingStorage()

            @property
            def url(self):
                raise OSError

        audio = SimpleNamespace(
            uploaded_audio_files=[("mp3", MissingUrlField()), ("m4a", BrokenUrlField())],
            mime_lookup={"mp3": "audio/mpeg", "m4a": "audio/mp4"},
            title_lookup={"mp3": "Audio MP3", "m4a": "Audio M4A"},
            get_file_size=lambda _audio_format: 1,
        )
        transcript = SimpleNamespace(audio=audio)

        assert get_transcript_audio_sources(transcript) == []
