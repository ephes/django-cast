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


class TestTranscriptEdit:
    pytestmark = pytest.mark.django_db

    def test_get_edit_transcript(self, admin_client, transcript_urls):
        r = admin_client.get(transcript_urls.edit)

        assert r.status_code == 200
        content = r.content.decode("utf-8")
        assert "Delete" in content

    def test_get_edit_transcript_detail(self, admin_client, transcript):
        edit_url = reverse("cast-transcript:edit", args=(transcript.id,))
        r = admin_client.get(edit_url)

        assert r.status_code == 200
        content = r.content.decode("utf-8")
        assert "Delete" in content

    def test_post_edit_transcript_invalid_form(self, admin_client, transcript_urls, podlove_transcript):
        podlove_transcript.seek(podlove_transcript.size)  # seek to end to make file empty/invalid
        post_data = {"podlove": podlove_transcript}
        r = admin_client.post(transcript_urls.edit, post_data)

        # make sure we don't get redirected to index
        assert r.status_code == 200

    def test_post_edit_audio_podlove(self, admin_client, transcript_urls, podlove_transcript):
        audio = transcript_urls.transcript.audio
        post_data = {
            "podlove": podlove_transcript,
            "audio": audio.id,
        }
        r = admin_client.post(transcript_urls.edit, post_data)

        # make sure we get redirected to index
        assert r.status_code == 302
        assert r.url == transcript_urls.index

        # make sure transcript in podlove was changes
        transcript = transcript_urls.transcript
        transcript.refresh_from_db()

        with transcript.podlove.open("r") as file:
            saved_transcript_content = file.read()
        podlove_transcript.seek(0)
        submitted_transcript_content = podlove_transcript.read().decode("utf-8")
        assert saved_transcript_content == submitted_transcript_content


class TestTranscriptDelete:
    pytestmark = pytest.mark.django_db

    def test_get_delete_transcript(self, admin_client, transcript_urls):
        r = admin_client.get(transcript_urls.delete)

        assert r.status_code == 200
        content = r.content.decode("utf-8")
        assert "Are you sure you want to delete this transcript?" in content

    def test_post_delete_transcript(self, admin_client, transcript_urls):
        # post data is necessary because of if request.POST
        r = admin_client.post(transcript_urls.delete, {"delete": "yes"})

        # make sure we get redirected to index
        assert r.status_code == 302
        assert r.url == transcript_urls.index

        # make sure transcript was deleted
        transcript = transcript_urls.transcript
        with pytest.raises(Transcript.DoesNotExist):
            transcript.refresh_from_db()


class TestTranscriptChosen:
    pytestmark = pytest.mark.django_db

    def test_get_chosen_transcript_not_found(self, admin_client, transcript_urls):
        transcript_urls.transcript.delete()
        r = admin_client.get(transcript_urls.chosen)

        assert r.status_code == 404

    def test_get_chosen_transcript_success(self, admin_client, transcript_urls):
        r = admin_client.get(transcript_urls.chosen)

        assert r.status_code == 200

        # make sure returned data belongs to the right transcript instance
        data = r.json()
        assert data["result"]["id"] == transcript_urls.transcript.id


class TestTranscriptChooser:
    pytestmark = pytest.mark.django_db

    def test_get_transcript_in_chooser(self, admin_client, transcript_urls):
        audio = transcript_urls.transcript.audio
        r = admin_client.get(transcript_urls.chooser)

        assert r.status_code == 200

        # make sure existing transcript is in chooser
        content = r.content.decode("utf-8")
        assert audio.title in content

        # make sure prefix for form fields is set
        assert "media-chooser-upload" in content

    def test_get_chooser_with_search(self, admin_client, transcript_urls):
        r = admin_client.get(transcript_urls.chooser, {"q": transcript_urls.transcript.audio.title})

        assert r.status_code == 200

        # make sure searched transcript is included in results
        assert r.context["transcripts"][0] == transcript_urls.transcript

    def test_get_chooser_with_search_invalid(self, admin_client, transcript_urls):
        # {"p": "1"} (page 1) leads to the search form being invalid
        r = admin_client.get(transcript_urls.chooser, {"p": "1"})

        assert r.status_code == 200

        # make sure searched transcripts is included in results
        assert r.context["transcripts"][0] == transcript_urls.transcript


class TestTranscriptChooserUpload:
    pytestmark = pytest.mark.django_db

    def test_get_transcript_in_chooser_upload(self, admin_client, transcript_urls):
        audio = transcript_urls.transcript.audio
        r = admin_client.get(transcript_urls.chooser_upload)

        assert r.status_code == 200
        content = r.content.decode("utf-8")
        assert audio.title in content

    def test_post_upload_transcript_form_invalid(self, admin_client, podlove_transcript):
        podlove_transcript.seek(podlove_transcript.size)  # seek to end to make file empty/invalid
        upload_url = reverse("cast-transcript:chooser_upload")
        post_data = {"media-chooser-podlove": podlove_transcript}
        r = admin_client.post(upload_url, post_data)

        assert r.status_code == 200
        assert r.context["message"] == "The transcript could not be saved due to errors."

    def test_post_upload_transcript(self, admin_client, podlove_transcript, settings, audio):
        settings.DEFAULT_FILE_STORAGE = "django.core.files.storage.FileSystemStorage"
        upload_url = reverse("cast-transcript:chooser_upload")
        prefix = "media-chooser-upload"
        post_data = {
            f"{prefix}-audio": audio.id,
            f"{prefix}-podlove": podlove_transcript,
        }
        r = admin_client.post(upload_url, post_data)

        assert r.status_code == 200

        # make sure field was saved correctly
        transcript = Transcript.objects.first()
        with transcript.podlove.open("r") as file:
            saved_transcript_content = file.read()
        podlove_transcript.seek(0)
        submitted_transcript_content = podlove_transcript.read().decode("utf-8")
        assert saved_transcript_content == submitted_transcript_content

        # teardown
        transcript.podlove.delete()
