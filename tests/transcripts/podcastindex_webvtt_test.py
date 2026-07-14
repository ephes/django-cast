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


class TestGetTranscriptAsPodcastIndexJson:
    pytestmark = pytest.mark.django_db

    def test_get_transcript_as_json_not_found(self, client):
        url = reverse("cast:podcastindex-transcript-json", kwargs={"pk": 1})
        r = client.get(url)
        assert r.status_code == 404

    def test_get_transcript_as_json_no_dote(self, client, episode):
        # Given a transcript without a dote file, anchored to a live episode
        transcript = create_transcript(audio=episode.podcast_audio)

        # When we request the transcript as JSON
        url = reverse("cast:podcastindex-transcript-json", kwargs={"pk": transcript.id})
        r = client.get(url)

        # Then we get a 404 response with an error message
        assert r.status_code == 404
        assert r.content.decode("utf-8") == "podcastindex JSON file not available"

    def test_get_transcript_as_json_not_valid_json(self, client, episode):
        # Given a transcript that is not valid JSON, anchored to a live episode
        transcript = create_transcript(audio=episode.podcast_audio)
        transcript.dote.save("dote.json", ContentFile("not valid json"))
        transcript.save()

        # When we request the transcript as JSON
        url = reverse("cast:podcastindex-transcript-json", kwargs={"pk": transcript.id})
        r = client.get(url)

        # Then we get a 400 response with an error message
        assert r.status_code == 400
        assert r.content.decode("utf-8") == "Invalid JSON format in dote file"

    def test_get_transcript_as_json_success(self, client, episode):
        # Given a transcript in podlove format
        dote = {
            "lines": [
                {
                    "startTime": "00:00:00,620",
                    "endTime": "00:00:05,160",
                    "speakerDesignation": "speaker",
                    "text": "Ja, hallo liebe Hörerinnen und Hörer. Willkommen beim Python-Podcast der 5ten Episode.",
                }
            ]
        }
        transcript = create_transcript(audio=episode.podcast_audio, dote=dote)

        # When we request the transcript as JSON
        url = reverse("cast:podcastindex-transcript-json", kwargs={"pk": transcript.id})
        r = client.get(url)
        assert r.status_code == 200

        # Then we get the transcript in the expected format
        assert r.json() == {
            "version": "1.0",
            "segments": [
                {
                    "startTime": 0.62,
                    "endTime": 5.16,
                    "speaker": "",
                    "body": "Ja, hallo liebe Hörerinnen und Hörer. Willkommen beim Python-Podcast der 5ten Episode.",
                },
            ],
        }

    def test_get_transcript_as_json_empty_dote_lines_returns_empty_segments(self, client, episode):
        transcript = create_transcript(audio=episode.podcast_audio, dote={"lines": []})

        url = reverse("cast:podcastindex-transcript-json", kwargs={"pk": transcript.id})
        response = client.get(url)

        assert response.status_code == 200
        assert response.json() == {"version": "1.0", "segments": []}

    def test_get_transcript_as_json_empty_dote_object_returns_empty_json(self, client, episode):
        transcript = create_transcript(audio=episode.podcast_audio)
        transcript.dote.save("empty-dote.json", ContentFile("{}"))
        transcript.save()

        url = reverse("cast:podcastindex-transcript-json", kwargs={"pk": transcript.id})
        response = client.get(url)

        assert response.status_code == 200
        assert response.json() == {}

    def test_get_transcript_as_json_missing_dote_file_returns_404(self, client, episode):
        transcript = create_transcript(audio=episode.podcast_audio, dote={"lines": []})
        transcript.dote.storage.delete(transcript.dote.name)

        url = reverse("cast:podcastindex-transcript-json", kwargs={"pk": transcript.id})
        response = client.get(url)

        assert response.status_code == 404
        assert response.content.decode("utf-8") == "podcastindex JSON file missing"

    def test_get_transcript_as_json_sanitizes_public_speaker_labels(self, client, episode):
        live_contributor = Contributor.objects.create(display_name="Live Host", slug="live-host")
        EpisodeContributor.objects.create(
            episode=episode, contributor=live_contributor, role=EpisodeContributor.ROLE_HOST
        )
        draft_contributor = Contributor.objects.create(display_name="Draft Guest", slug="draft-guest")
        episode.contributor_assignments.add(
            EpisodeContributor(contributor=draft_contributor, role=EpisodeContributor.ROLE_GUEST)
        )
        episode.save_revision()
        transcript = create_transcript(
            audio=episode.podcast_audio,
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
                        "speakerDesignation": "Draft Guest",
                        "text": "Draft speaker",
                    },
                    {
                        "startTime": "00:00:02,000",
                        "endTime": "00:00:03,000",
                        "speakerDesignation": "Speaker 1",
                        "text": "Unmapped speaker",
                    },
                ]
            },
        )

        url = reverse("cast:podcastindex-transcript-json", kwargs={"pk": transcript.id})
        response = client.get(url)

        assert response.status_code == 200
        data = response.json()
        assert [segment["speaker"] for segment in data["segments"]] == ["Live Host", "", ""]
        assert "Draft Guest" not in response.content.decode("utf-8")
        assert "Speaker 1" not in response.content.decode("utf-8")
        with transcript.dote.open("r") as dote_file:
            stored_data = json.load(dote_file)
        assert stored_data["lines"][1]["speakerDesignation"] == "Draft Guest"


class TestGetTranscriptAsWebVtt:
    pytestmark = pytest.mark.django_db

    def test_get_transcript_as_vtt_not_found(self, client):
        url = reverse("cast:webvtt-transcript", kwargs={"pk": 1})
        r = client.get(url)
        assert r.status_code == 404

    def test_get_transcript_as_json_no_vtt(self, client, episode):
        # Given a transcript without a vtt file, anchored to a live episode
        transcript = create_transcript(audio=episode.podcast_audio)

        # When we request the transcript as JSON
        url = reverse("cast:webvtt-transcript", kwargs={"pk": transcript.id})
        r = client.get(url)

        # Then we get a 404 response with an error message
        assert r.status_code == 404
        assert r.content.decode("utf-8") == "WebVTT file not available"

    def test_get_transcript_as_vtt_success(self, client, episode):
        # Given a transcript in vtt format
        vtt = "WEBVTT\n\n00:00:00.620 --> 00:00:05.160\nJa, hallo liebe Hörerinnen und Hörer."
        transcript = create_transcript(audio=episode.podcast_audio, vtt=vtt)

        # When we request the transcript as JSON
        url = reverse("cast:webvtt-transcript", kwargs={"pk": transcript.id})
        r = client.get(url)
        assert r.status_code == 200

        # Then we get the transcript in the expected format
        content = r.content.decode("utf-8")
        assert content == vtt

    def test_get_transcript_as_vtt_sanitizes_generated_speaker_labels(self, client, episode):
        live_contributor = Contributor.objects.create(display_name="Live Host", slug="live-host")
        EpisodeContributor.objects.create(
            episode=episode, contributor=live_contributor, role=EpisodeContributor.ROLE_HOST
        )
        vtt = (
            "WEBVTT\n\n"
            "00:00:00.000 --> 00:00:01.000\n"
            "Live Host: Hallo\n\n"
            "00:00:01.000 --> 00:00:02.000\n"
            "Speaker 1: Unmapped speaker\n\n"
            "00:00:02.000 --> 00:00:03.000\n"
            "<v Speaker 2>Voice span speaker</v>\n"
        )
        transcript = create_transcript(audio=episode.podcast_audio, vtt=vtt)

        url = reverse("cast:webvtt-transcript", kwargs={"pk": transcript.id})
        response = client.get(url)

        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert "Live Host: Hallo" in content
        assert "Speaker 1" not in content
        assert "Unmapped speaker" in content
        assert "Speaker 2" not in content
        assert "Voice span speaker" in content
