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


@pytest.fixture
def transcript_with_podlove(audio):
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
    return create_transcript(audio=audio, podlove=podlove)


class TestGetTranscriptAsHtml:
    pytestmark = pytest.mark.django_db

    def test_resolve_transcript_template_falls_back_for_missing_theme(self, mocker):
        mocker.patch("cast.views.transcript.get_template", side_effect=TemplateDoesNotExist("missing"))

        assert _resolve_transcript_template("theme-without-transcript") == "cast/plain/transcript.html"

    def test_get_transcript_as_html_not_found(self, client):
        url = reverse("cast:html-transcript-no-post", kwargs={"transcript_pk": 1})
        r = client.get(url)
        assert r.status_code == 404

    def test_get_transcript_as_html_no_podlove(self, client, episode):
        transcript = create_transcript(audio=episode.podcast_audio)
        url = reverse("cast:html-transcript-no-post", kwargs={"transcript_pk": transcript.pk})
        r = client.get(url)
        assert r.status_code == 404

    def test_get_transcript_as_html_broken_json(self, client, episode):
        # Given a transcript that is not valid JSON, anchored to a live episode
        transcript = create_transcript(audio=episode.podcast_audio)
        transcript.podlove.save("podlove.json", ContentFile("not valid json"))
        transcript.save()

        # When we request the transcript as JSON
        url = reverse("cast:html-transcript-no-post", kwargs={"transcript_pk": transcript.id})
        r = client.get(url)

        # Then we get a 400 response with an error message
        assert r.status_code == 400
        assert r.content.decode("utf-8") == "Invalid JSON format in podlove file"

    def test_get_transcript_as_html_success(self, client, episode, transcript_with_podlove):
        # Given a transcript in podlove format, anchored to a live episode
        transcript = transcript_with_podlove

        # When we request the transcript as HTML
        url = reverse("cast:html-transcript-no-post", kwargs={"transcript_pk": transcript.id})
        r = client.get(url)
        assert r.status_code == 200

        # Then we get the transcript in the expected format
        content = r.content.decode("utf-8")
        assert "hallo liebe Hörerinnen und Hörer" in content

    def test_get_transcript_as_html_falls_back_to_plain_template_for_missing_optional_theme_template(
        self, client, episode, transcript_with_podlove, mocker
    ):
        transcript = transcript_with_podlove
        template_base_dir = "theme-without-transcript"

        mocker.patch("cast.views.transcript.get_template_base_dir", return_value=template_base_dir)

        def fake_get_template(name: str):
            if name == f"cast/{template_base_dir}/transcript.html":
                raise TemplateDoesNotExist(name)
            return object()

        mocker.patch("cast.views.transcript.get_template", side_effect=fake_get_template)

        url = reverse("cast:html-transcript-no-post", kwargs={"transcript_pk": transcript.id})
        response = client.get(url)

        assert response.status_code == 200
        assert "cast/plain/transcript.html" in [template.name for template in response.templates]

    def test_get_transcript_as_html_success_from_post(self, client, transcript_with_podlove, post_with_audio):
        # Given a transcript in podlove format whose audio is in a live post's body
        transcript = transcript_with_podlove

        # When we request the transcript as HTML anchored to that post
        url = reverse("cast:html-transcript", kwargs={"transcript_pk": transcript.id, "post_pk": post_with_audio.id})
        r = client.get(url)
        assert r.status_code == 200

        # Then we get the transcript in the expected format
        content = r.content.decode("utf-8")
        assert "hallo liebe Hörerinnen und Hörer" in content

    def test_get_transcript_as_html_redirects_for_episode(self, client, episode):
        podlove = {
            "transcripts": [
                {
                    "start": "00:00:00.620",
                    "end": "00:00:05.160",
                    "speaker": "Host",
                    "text": "Hallo und willkommen.",
                }
            ]
        }
        transcript = create_transcript(audio=episode.podcast_audio, podlove=podlove)
        url = reverse("cast:html-transcript", kwargs={"transcript_pk": transcript.id, "post_pk": episode.id})

        r = client.get(url)

        assert r.status_code == 302
        assert r.url == reverse(
            "cast:episode-transcript",
            kwargs={"blog_slug": episode.blog.slug, "episode_slug": episode.slug},
        )

    def test_get_transcript_as_html_canonical_success(self, client, episode):
        contributor = Contributor.objects.create(display_name="Host", slug="host")
        EpisodeContributor.objects.create(episode=episode, contributor=contributor, role=EpisodeContributor.ROLE_HOST)
        podlove = {
            "transcripts": [
                {
                    "start": "00:00:00.620",
                    "end": "00:00:05.160",
                    "speaker": "Host",
                    "text": "Hallo und willkommen.",
                }
            ]
        }
        create_transcript(audio=episode.podcast_audio, podlove=podlove)
        url = reverse("cast:episode-transcript", kwargs={"blog_slug": episode.blog.slug, "episode_slug": episode.slug})

        r = client.get(url)

        assert r.status_code == 200
        content = r.content.decode("utf-8")
        assert "Hallo und willkommen." in content
        assert "Host" in content
        assert episode.title in content
        assert episode.get_url() in content

    def test_get_transcript_as_html_canonical_sanitizes_public_speaker_labels(self, client, episode):
        live_contributor = Contributor.objects.create(display_name="Live Host", slug="live-host")
        EpisodeContributor.objects.create(
            episode=episode, contributor=live_contributor, role=EpisodeContributor.ROLE_HOST
        )
        draft_contributor = Contributor.objects.create(display_name="Draft Guest", slug="draft-guest")
        episode.contributor_assignments.add(
            EpisodeContributor(contributor=draft_contributor, role=EpisodeContributor.ROLE_GUEST)
        )
        episode.save_revision()
        create_transcript(
            audio=episode.podcast_audio,
            podlove={
                "transcripts": [
                    {"start": "00:00:00.000", "speaker": "Live Host", "text": "Live speaker"},
                    {"start": "00:00:01.000", "speaker": "Draft Guest", "text": "Draft speaker"},
                    {"start": "00:00:02.000", "speaker": "Speaker 1", "text": "Unmapped speaker"},
                ]
            },
        )
        url = reverse("cast:episode-transcript", kwargs={"blog_slug": episode.blog.slug, "episode_slug": episode.slug})

        response = client.get(url)

        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert "Live Host" in content
        assert "Live speaker" in content
        assert "Draft Guest" not in content
        assert "Draft speaker" in content
        assert "Speaker 1" not in content
        assert "Unmapped speaker" in content

    def test_get_transcript_as_html_canonical_applies_mapping_after_s3_style_prior_read(
        self, client, episode, s3_style_fieldfile_reopen_guard
    ):
        contributor = Contributor.objects.create(display_name="Alice", slug="html-s3-alice")
        EpisodeContributor.objects.create(episode=episode, contributor=contributor, role=EpisodeContributor.ROLE_HOST)
        transcript = create_transcript(
            audio=episode.podcast_audio,
            podlove={
                "transcripts": [
                    {"start": "00:00:00.000", "speaker": "Speaker 1", "voice": "Speaker 1", "text": "Mapped line"}
                ]
            },
        )
        fingerprint = transcript.transcript_artifact_fingerprint()
        mapping = transcript.speaker_mappings.get(speaker_label="Speaker 1")
        mapping.contributor = contributor
        mapping.review_state = TranscriptSpeakerMapping.ReviewState.APPROVED
        mapping.source_artifact_fingerprint = fingerprint
        mapping.save()
        s3_style_fieldfile_reopen_guard()
        url = reverse("cast:episode-transcript", kwargs={"blog_slug": episode.blog.slug, "episode_slug": episode.slug})

        response = client.get(url)

        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert "Alice" in content
        assert "Speaker 1" not in content

    def test_get_transcript_as_html_canonical_without_transcript(self, client, episode):
        url = reverse("cast:episode-transcript", kwargs={"blog_slug": episode.blog.slug, "episode_slug": episode.slug})

        r = client.get(url)

        assert r.status_code == 404

    def test_get_transcript_as_html_canonical_mismatched_blog(self, client, episode, blog):
        url = reverse("cast:episode-transcript", kwargs={"blog_slug": blog.slug, "episode_slug": episode.slug})

        r = client.get(url)

        assert r.status_code == 404


@pytest.mark.django_db
def test_episode_transcript_uses_current_site_for_duplicate_blog_slug(client, user, audio):
    site1, site1_root = create_site_root(
        owner=user, hostname="transcript-site1.local", slug="transcript-site1-root", title="Transcript Site 1"
    )
    _site2, site2_root = create_site_root(
        owner=user, hostname="transcript-site2.local", slug="transcript-site2-root", title="Transcript Site 2"
    )
    blog1 = BlogFactory(owner=user, title="Blog 1", slug="shared-transcript-blog", parent=site1_root)
    blog2 = BlogFactory(owner=user, title="Blog 2", slug="shared-transcript-blog", parent=site2_root)
    episode1 = EpisodeFactory(
        owner=user, title="Episode 1", slug="shared-transcript-episode", parent=blog1, podcast_audio=audio
    )
    EpisodeFactory(owner=user, title="Episode 2", slug="shared-transcript-episode", parent=blog2, podcast_audio=audio)
    create_transcript(
        audio=audio,
        podlove={
            "transcripts": [
                {
                    "start": "00:00:00.620",
                    "end": "00:00:05.160",
                    "speaker": "Host",
                    "text": "Hello multisite transcript.",
                }
            ]
        },
    )

    url = reverse(
        "cast:episode-transcript",
        kwargs={"blog_slug": blog1.slug, "episode_slug": episode1.slug},
    )
    with override_settings(ALLOWED_HOSTS=["testserver", site1.hostname, "transcript-site2.local"]):
        response = client.get(url, HTTP_HOST=site1.hostname)

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "Episode 1" in content
    assert "Episode 2" not in content
