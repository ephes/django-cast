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


class TestGetTranscriptAsJson:
    pytestmark = pytest.mark.django_db

    def test_get_transcript_as_json_not_found(self, client):
        url = reverse("cast:podlove-transcript-json", kwargs={"pk": 1})
        r = client.get(url)
        assert r.status_code == 404

    def test_get_transcript_as_json_no_podlove(self, client, episode):
        # Given a transcript without a podlove file, anchored to a live episode
        transcript = create_transcript(audio=episode.podcast_audio)

        # When we request the transcript as JSON
        url = reverse("cast:podlove-transcript-json", kwargs={"pk": transcript.id})
        r = client.get(url)

        # Then we get a 404 response with an error message
        assert r.status_code == 404
        assert r.content.decode("utf-8") == "Podlove file not available"

    def test_get_transcript_as_json_not_valid_json(self, client, episode):
        # Given a transcript that is not valid JSON, anchored to a live episode
        transcript = create_transcript(audio=episode.podcast_audio)
        transcript.podlove.save("podlove.json", ContentFile("not valid json"))
        transcript.save()

        # When we request the transcript as JSON
        url = reverse("cast:podlove-transcript-json", kwargs={"pk": transcript.id})
        r = client.get(url)

        # Then we get a 400 response with an error message
        assert r.status_code == 400
        assert r.content.decode("utf-8") == "Invalid JSON format in podlove file"

    def test_get_transcript_as_json_success(self, client, episode):
        # Given a transcript in podlove format
        podlove = {
            "transcripts": [
                {
                    "start": "00:00:00.620",
                    "start_ms": 620,
                    "end": "00:00:05.160",
                    "end_ms": 5160,
                    "speaker": "",
                    "voice": "",
                    "text": "Ja, hallo liebe Hörerinnen und Hörer. Willkommen beim Python-Podcast der 5ten Episode.",
                }
            ]
        }
        transcript = create_transcript(audio=episode.podcast_audio, podlove=podlove)

        # When we request the transcript as JSON
        url = reverse("cast:podlove-transcript-json", kwargs={"pk": transcript.id})
        r = client.get(url)
        assert r.status_code == 200

        # Then we get the transcript in the expected format
        assert r.json()["transcripts"] == podlove["transcripts"]

    def test_get_transcript_as_json_sanitizes_public_speaker_labels(self, client, episode):
        live_contributor = Contributor.objects.create(display_name="Live Host", slug="live-host")
        EpisodeContributor.objects.create(
            episode=episode,
            contributor=live_contributor,
            role=EpisodeContributor.ROLE_HOST,
            sort_order=0,
        )
        draft_contributor = Contributor.objects.create(display_name="Draft Guest", slug="draft-guest")
        episode.contributor_assignments.add(
            EpisodeContributor(contributor=draft_contributor, role=EpisodeContributor.ROLE_GUEST, sort_order=1)
        )
        episode.save_revision()
        transcript = create_transcript(
            audio=episode.podcast_audio,
            podlove={
                "transcripts": [
                    {"speaker": "Live Host", "voice": "Live Host", "text": "Live speaker"},
                    {"speaker": "Draft Guest", "voice": "Draft Guest", "text": "Draft speaker"},
                    {"speaker": "Speaker 1", "voice": "Speaker 1", "text": "Unmapped speaker"},
                ]
            },
        )

        url = reverse("cast:podlove-transcript-json", kwargs={"pk": transcript.id})
        response = client.get(url)

        assert response.status_code == 200
        data = response.json()
        assert data["transcripts"][0]["speaker"] == "Live Host"
        assert "speaker" not in data["transcripts"][1]
        assert "voice" not in data["transcripts"][1]
        assert "speaker" not in data["transcripts"][2]
        assert "voice" not in data["transcripts"][2]
        with transcript.podlove.open("r") as podlove_file:
            stored_data = json.load(podlove_file)
        assert stored_data["transcripts"][1]["speaker"] == "Draft Guest"

    def test_public_direct_endpoints_reject_draft_only_audio(self, client, episode):
        # A draft-only episode (never published) must not expose its transcript to
        # the anonymous public on any direct object endpoint: each returns 404 and
        # the stored file stays untouched.
        episode.live = False
        episode.save(update_fields=["live"])
        transcript = create_transcript(
            audio=episode.podcast_audio,
            podlove={
                "transcripts": [
                    {"speaker": "Draft Guest", "voice": "Draft Guest", "text": "Draft speaker"},
                    {"speaker": "Speaker 1", "voice": "Speaker 1", "text": "Unmapped speaker"},
                ]
            },
            dote={
                "lines": [
                    {
                        "startTime": "00:00:00,000",
                        "endTime": "00:00:01,000",
                        "speakerDesignation": "Draft Guest",
                        "text": "Draft speaker",
                    },
                ]
            },
            vtt=("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\n<v Draft Guest>Draft speaker</v>\n"),
        )

        podlove_response = client.get(reverse("cast:podlove-transcript-json", kwargs={"pk": transcript.id}))
        podcastindex_response = client.get(reverse("cast:podcastindex-transcript-json", kwargs={"pk": transcript.id}))
        vtt_response = client.get(reverse("cast:webvtt-transcript", kwargs={"pk": transcript.id}))
        html_response = client.get(reverse("cast:html-transcript-no-post", kwargs={"transcript_pk": transcript.id}))

        assert podlove_response.status_code == 404
        assert podcastindex_response.status_code == 404
        assert vtt_response.status_code == 404
        assert html_response.status_code == 404
        with transcript.podlove.open("r") as podlove_file:
            stored_data = json.load(podlove_file)
        assert stored_data["transcripts"][0]["speaker"] == "Draft Guest"

    def test_disabled_audio_suppresses_public_speaker_labels_without_rewriting_files(self, client, episode):
        live_contributor = Contributor.objects.create(display_name="Live Host", slug="disabled-live-host")
        EpisodeContributor.objects.create(
            episode=episode,
            contributor=live_contributor,
            role=EpisodeContributor.ROLE_HOST,
        )
        audio = episode.podcast_audio
        audio.transcript_diarization_mode = audio.TranscriptDiarizationMode.DISABLED
        audio.save(update_fields=["transcript_diarization_mode"], duration=False, cache_file_sizes=False)
        transcript = create_transcript(
            audio=audio,
            podlove={
                "transcripts": [
                    {
                        "start": "00:00:00.000",
                        "end": "00:00:01.000",
                        "speaker": "Live Host",
                        "voice": "Live Host",
                        "text": "Live speaker",
                    },
                    {
                        "start": "00:00:01.000",
                        "end": "00:00:02.000",
                        "speaker": "Speaker 1",
                        "voice": "Speaker 1",
                        "text": "Generic speaker",
                    },
                ]
            },
            dote={
                "lines": [
                    {
                        "startTime": "00:00:00,000",
                        "endTime": "00:00:01,000",
                        "speakerDesignation": "Live Host",
                        "text": "Live speaker",
                    },
                    {
                        "startTime": "00:00:01,000",
                        "endTime": "00:00:02,000",
                        "speakerDesignation": "Speaker 1",
                        "text": "Generic speaker",
                    },
                ]
            },
            vtt=(
                "WEBVTT\n\n"
                "00:00:00.000 --> 00:00:01.000\n"
                "<v Live Host>Live speaker</v>\n\n"
                "00:00:01.000 --> 00:00:02.000\n"
                "Speaker 1: Generic speaker\n"
            ),
        )

        podlove_response = client.get(reverse("cast:podlove-transcript-json", kwargs={"pk": transcript.id}))
        podcastindex_response = client.get(reverse("cast:podcastindex-transcript-json", kwargs={"pk": transcript.id}))
        vtt_response = client.get(reverse("cast:webvtt-transcript", kwargs={"pk": transcript.id}))
        html_response = client.get(
            reverse("cast:episode-transcript", kwargs={"blog_slug": episode.blog.slug, "episode_slug": episode.slug})
        )

        assert podlove_response.status_code == 200
        podlove_data = podlove_response.json()
        assert "speaker" not in podlove_data["transcripts"][0]
        assert "voice" not in podlove_data["transcripts"][0]
        assert "speaker" not in podlove_data["transcripts"][1]
        assert "voice" not in podlove_data["transcripts"][1]
        assert podcastindex_response.status_code == 200
        assert [segment["speaker"] for segment in podcastindex_response.json()["segments"]] == ["", ""]
        assert vtt_response.status_code == 200
        assert vtt_response.content.decode("utf-8") == (
            "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nLive speaker\n\n00:00:01.000 --> 00:00:02.000\nGeneric speaker\n"
        )
        assert html_response.status_code == 200
        html_content = html_response.content.decode("utf-8")
        assert "Live Host" not in html_content
        assert "Speaker 1" not in html_content
        assert "Live speaker" in html_content
        assert "Generic speaker" in html_content
        with transcript.podlove.open("r") as podlove_file:
            stored_podlove = json.load(podlove_file)
        with transcript.dote.open("r") as dote_file:
            stored_dote = json.load(dote_file)
        with transcript.vtt.open("r") as vtt_file:
            stored_vtt = vtt_file.read()
        assert stored_podlove["transcripts"][0]["speaker"] == "Live Host"
        assert stored_podlove["transcripts"][1]["speaker"] == "Speaker 1"
        assert stored_dote["lines"][0]["speakerDesignation"] == "Live Host"
        assert "<v Live Host>Live speaker</v>" in stored_vtt

    def test_approved_speaker_mappings_apply_to_every_public_output_without_rewriting_files(
        self, client, api_client, episode
    ):
        contributor = Contributor.objects.create(display_name="Alice", slug="mapped-alice")
        EpisodeContributor.objects.create(
            episode=episode,
            contributor=contributor,
            role=EpisodeContributor.ROLE_HOST,
        )
        transcript = create_transcript(
            audio=episode.podcast_audio,
            podlove={
                "transcripts": [
                    {"start": "00:00:00.000", "speaker": "Speaker 1", "voice": "Speaker 1", "text": "Alice line"},
                    {"start": "00:00:01.000", "speaker": "Speaker 2", "voice": "Speaker 2", "text": "Guest line"},
                    {"start": "00:00:02.000", "speaker": "Speaker 3", "voice": "Speaker 3", "text": "Raw line"},
                ]
            },
            dote={
                "lines": [
                    {
                        "startTime": "00:00:00,000",
                        "endTime": "00:00:01,000",
                        "speakerDesignation": "Speaker 1",
                        "text": "Alice line",
                    },
                    {
                        "startTime": "00:00:01,000",
                        "endTime": "00:00:02,000",
                        "speakerDesignation": "Speaker 2",
                        "text": "Guest line",
                    },
                    {
                        "startTime": "00:00:02,000",
                        "endTime": "00:00:03,000",
                        "speakerDesignation": "Speaker 3",
                        "text": "Raw line",
                    },
                ]
            },
            vtt=(
                "WEBVTT\n\n"
                "00:00:00.000 --> 00:00:01.000\n"
                "<v Speaker 1>Alice line</v>\n\n"
                "00:00:01.000 --> 00:00:02.000\n"
                "Speaker 2: Guest line\n\n"
                "00:00:02.000 --> 00:00:03.000\n"
                "<v Speaker 3>Raw line</v>\n"
            ),
        )
        fingerprint = transcript.transcript_artifact_fingerprint()
        speaker_one = transcript.speaker_mappings.get(speaker_label="Speaker 1")
        speaker_one.contributor = contributor
        speaker_one.review_state = TranscriptSpeakerMapping.ReviewState.APPROVED
        speaker_one.source_artifact_fingerprint = fingerprint
        speaker_one.save()
        speaker_two = transcript.speaker_mappings.get(speaker_label="Speaker 2")
        speaker_two.display_name = "Guest Voice"
        speaker_two.review_state = TranscriptSpeakerMapping.ReviewState.APPROVED
        speaker_two.source_artifact_fingerprint = fingerprint
        speaker_two.save()

        podlove_response = client.get(reverse("cast:podlove-transcript-json", kwargs={"pk": transcript.pk}))
        podcastindex_response = client.get(reverse("cast:podcastindex-transcript-json", kwargs={"pk": transcript.pk}))
        vtt_response = client.get(reverse("cast:webvtt-transcript", kwargs={"pk": transcript.pk}))
        html_response = client.get(
            reverse("cast:episode-transcript", kwargs={"blog_slug": episode.blog.slug, "episode_slug": episode.slug})
        )
        api_response = api_client.get(
            reverse("cast:api:audio_podlove_detail", kwargs={"pk": episode.podcast_audio.pk, "post_id": episode.pk}),
            format="json",
        )

        assert podlove_response.status_code == 200
        podlove_data = podlove_response.json()
        assert podlove_data["transcripts"][0]["speaker"] == "Alice"
        assert podlove_data["transcripts"][0]["voice"] == "Alice"
        assert podlove_data["transcripts"][1]["speaker"] == "Guest Voice"
        assert "speaker" not in podlove_data["transcripts"][2]
        assert podcastindex_response.status_code == 200
        assert [segment["speaker"] for segment in podcastindex_response.json()["segments"]] == [
            "Alice",
            "Guest Voice",
            "",
        ]
        assert vtt_response.status_code == 200
        vtt_content = vtt_response.content.decode("utf-8")
        assert "<v Alice>Alice line</v>" in vtt_content
        assert "Guest Voice: Guest line" in vtt_content
        assert "Speaker 3" not in vtt_content
        assert html_response.status_code == 200
        html_content = html_response.content.decode("utf-8")
        assert "Alice" in html_content
        assert "Guest Voice" in html_content
        assert "Speaker 3" not in html_content
        assert api_response.status_code == 200
        api_data = api_response.json()
        assert api_data["contributors"] == [
            {"id": "Alice", "name": "Alice"},
            {"id": "Guest Voice", "name": "Guest Voice"},
        ]
        assert [segment.get("speaker", "") for segment in api_data["transcripts"]] == ["Alice", "Guest Voice", ""]
        with transcript.podlove.open("r") as podlove_file:
            stored_podlove = json.load(podlove_file)
        with transcript.dote.open("r") as dote_file:
            stored_dote = json.load(dote_file)
        with transcript.vtt.open("r") as vtt_file:
            stored_vtt = vtt_file.read()
        assert stored_podlove["transcripts"][0]["speaker"] == "Speaker 1"
        assert stored_dote["lines"][1]["speakerDesignation"] == "Speaker 2"
        assert "<v Speaker 1>Alice line</v>" in stored_vtt

    def test_public_mapping_sanitizer_blocks_stale_hidden_deleted_draft_and_disabled_targets(self, client, episode):
        draft_contributor = Contributor.objects.create(display_name="Draft Host", slug="mapped-draft-host")
        episode.contributor_assignments.add(
            EpisodeContributor(contributor=draft_contributor, role=EpisodeContributor.ROLE_HOST)
        )
        hidden_contributor = Contributor.objects.create(
            display_name="Hidden Host", slug="mapped-hidden-host", visible=False
        )
        EpisodeContributor.objects.create(
            episode=episode,
            contributor=hidden_contributor,
            role=EpisodeContributor.ROLE_GUEST,
        )
        deleted_contributor = Contributor.objects.create(display_name="Deleted Host", slug="mapped-deleted-host")
        transcript = create_transcript(
            audio=episode.podcast_audio,
            podlove={
                "transcripts": [
                    {"speaker": "Speaker 1", "voice": "Speaker 1", "text": "Stale line"},
                    {"speaker": "Speaker 2", "voice": "Speaker 2", "text": "Hidden line"},
                    {"speaker": "Speaker 3", "voice": "Speaker 3", "text": "Deleted line"},
                    {"speaker": "Speaker 4", "voice": "Speaker 4", "text": "Draft line"},
                    {"speaker": "Speaker 5", "voice": "Speaker 5", "text": "Unmapped line"},
                ]
            },
        )
        fingerprint = transcript.transcript_artifact_fingerprint()
        stale = transcript.speaker_mappings.get(speaker_label="Speaker 1")
        stale.display_name = "Stale Guest"
        stale.review_state = TranscriptSpeakerMapping.ReviewState.STALE
        stale.source_artifact_fingerprint = fingerprint
        stale.save()
        hidden = transcript.speaker_mappings.get(speaker_label="Speaker 2")
        hidden.contributor = hidden_contributor
        hidden.review_state = TranscriptSpeakerMapping.ReviewState.APPROVED
        hidden.source_artifact_fingerprint = fingerprint
        hidden.save()
        deleted = transcript.speaker_mappings.get(speaker_label="Speaker 3")
        deleted.contributor = deleted_contributor
        deleted.review_state = TranscriptSpeakerMapping.ReviewState.APPROVED
        deleted.source_artifact_fingerprint = fingerprint
        deleted.save()
        deleted_contributor.delete()
        draft = transcript.speaker_mappings.get(speaker_label="Speaker 4")
        draft.contributor = draft_contributor
        draft.review_state = TranscriptSpeakerMapping.ReviewState.APPROVED
        draft.source_artifact_fingerprint = fingerprint
        draft.save()

        response = client.get(reverse("cast:podlove-transcript-json", kwargs={"pk": transcript.pk}))

        assert response.status_code == 200
        serialized = response.content.decode("utf-8")
        for forbidden in [
            "Stale Guest",
            "Hidden Host",
            "Deleted Host",
            "Draft Host",
            "Speaker 1",
            "Speaker 2",
            "Speaker 3",
            "Speaker 4",
            "Speaker 5",
        ]:
            assert forbidden not in serialized

        one_off = transcript.speaker_mappings.get(speaker_label="Speaker 5")
        one_off.display_name = "Disabled Guest"
        one_off.review_state = TranscriptSpeakerMapping.ReviewState.APPROVED
        one_off.source_artifact_fingerprint = fingerprint
        one_off.save()
        audio = episode.podcast_audio
        audio.transcript_diarization_mode = audio.TranscriptDiarizationMode.DISABLED
        audio.save(update_fields=["transcript_diarization_mode"], duration=False, cache_file_sizes=False)

        disabled_response = client.get(reverse("cast:podlove-transcript-json", kwargs={"pk": transcript.pk}))

        assert disabled_response.status_code == 200
        assert "Disabled Guest" not in disabled_response.content.decode("utf-8")

    def test_public_one_off_mapping_matching_raw_label_does_not_allow_unmapped_label(self, client, episode):
        transcript = create_transcript(
            audio=episode.podcast_audio,
            podlove={
                "transcripts": [
                    {"speaker": "Speaker 1", "text": "Mapped line"},
                    {"speaker": "Speaker 2", "text": "Unmapped line"},
                ]
            },
        )
        fingerprint = transcript.transcript_artifact_fingerprint()
        mapping = transcript.speaker_mappings.get(speaker_label="Speaker 1")
        mapping.display_name = "Speaker 2"
        mapping.review_state = TranscriptSpeakerMapping.ReviewState.APPROVED
        mapping.source_artifact_fingerprint = fingerprint
        mapping.save()

        response = client.get(reverse("cast:podlove-transcript-json", kwargs={"pk": transcript.pk}))

        assert response.status_code == 200
        data = response.json()
        assert [segment.get("speaker") for segment in data["transcripts"]] == [None, None]
        assert "Speaker 1" not in response.content.decode("utf-8")
        assert "Speaker 2" not in response.content.decode("utf-8")
