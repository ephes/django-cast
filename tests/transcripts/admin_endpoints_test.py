from unittest.mock import patch

import pytest
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.urls import reverse

from cast.models import Transcript
from cast.views import transcript as transcript_views
from tests.factories import UserFactory


class TestAllTranscriptEndpoints:
    pytestmark = pytest.mark.django_db

    def test_get_all_not_authenticated(self, client, transcript_urls):
        for view_name, url in transcript_urls.urls.items():
            r = client.get(url)

            # redirect to log in
            assert r.status_code == 302
            login_url = reverse("wagtailadmin_login")
            assert login_url in r.url

    def test_get_all_authenticated(self, admin_client, transcript_urls):
        for view_name, url in transcript_urls.urls.items():
            r = admin_client.get(url)

            # assert we are not redirected to log in
            assert r.status_code == 200

    def test_shared_admin_views_require_collection_permissions(self, rf):
        user = UserFactory()

        for view in (
            transcript_views.index,
            transcript_views.add,
            transcript_views.chooser,
            transcript_views.chooser_upload,
        ):
            request = rf.get("/")
            request.user = user

            with pytest.raises(PermissionDenied):
                view(request)


class TestTranscriptIndex:
    pytestmark = pytest.mark.django_db

    def test_get_index(self, admin_client, transcript_urls):
        r = admin_client.get(transcript_urls.index)

        assert r.status_code == 200
        content = r.content.decode("utf-8")

        # make sure it's the media results page
        assert "html" in content
        assert "media-results" in content

        assert transcript_urls.transcript.audio.title in content

    def test_get_index_ajax(self, admin_client, transcript_urls):
        headers = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"}
        r = admin_client.get(transcript_urls.index, **headers)

        assert r.status_code == 200
        content = r.content.decode("utf-8")

        # make sure it's the media results page
        assert "table" in content
        assert "listing" in content

        # make sure transcript_urls.transcript is included in results
        assert transcript_urls.transcript.audio.title in content

    def test_get_index_with_search(self, admin_client, transcript_urls):
        r = admin_client.get(transcript_urls.index, {"q": transcript_urls.transcript.audio.title})

        assert r.status_code == 200
        content = r.content.decode("utf-8")

        # make sure it's the media results page
        assert "html" in content
        assert "media-results" in content

        # make sure transcript_urls.transcript.audio is included in results
        assert transcript_urls.transcript.audio.title in content

    def test_get_index_with_search_invalid(self, admin_client, transcript_urls):
        r = admin_client.get(transcript_urls.index, {"q": " "})

        assert r.status_code == 200
        content = r.content.decode("utf-8")

        # make sure it's the media results page
        assert "html" in content
        assert "media-results" in content

        # make sure transcript_urls.transcript.audio is included in results
        assert transcript_urls.transcript.audio.title in content

    def test_get_index_with_pagination(self, admin_client, user, audio):
        transcript = Transcript(audio=audio)
        transcript.save()
        index_url = reverse("cast-transcript:index")
        with patch("cast.views.media.MENU_ITEM_PAGINATION", return_value=1):
            r = admin_client.get(index_url, {"p": "1"})
        transcripts = r.context["transcripts"]

        # make sure we got last transcript from first page
        assert len(transcripts) == 1
        assert transcripts[0] == transcripts[-1]

        with patch("cast.views.media.MENU_ITEM_PAGINATION", return_value=1):
            r = admin_client.get(index_url, {"p": "2"})
        transcripts = r.context["transcripts"]

        # make sure we got first transcript from last page
        assert len(transcripts) == 1
        assert transcripts[0] == transcripts[0]


class TestTranscriptAdd:
    pytestmark = pytest.mark.django_db

    def test_get_add_transcript(self, admin_client, transcript_urls):
        r = admin_client.get(transcript_urls.add)

        assert r.status_code == 200
        content = r.content.decode("utf-8")
        assert "Uploading…" in content

    def test_post_add_transcript_invalid_form(self, admin_client, podlove_transcript):
        podlove_transcript.seek(podlove_transcript.size)  # seek to end to make file empty/invalid
        add_url = reverse("cast-transcript:add")

        post_data = {
            "podlove": podlove_transcript,
            "tags": "foo,bar,baz",  # invalid
        }
        r = admin_client.post(add_url, post_data)

        # make sure we don't get redirected to index
        assert r.status_code == 200
        assert r.context["message"] == "The transcript file could not be saved due to errors."

        # make sure we didn't create an transcript
        assert Transcript.objects.first() is None

    def test_post_add_transcript(self, admin_client, audio, podlove_transcript):
        add_url = reverse("cast-transcript:add")

        post_data = {
            "podlove": podlove_transcript,
            "audio": audio.id,
        }
        r = admin_client.post(add_url, post_data)

        # make sure we get redirected to index
        assert r.status_code == 302
        assert r.url == reverse("cast-transcript:index")

        # make sure field were saved correctly
        transcript = Transcript.objects.first()
        with transcript.podlove.open("r") as file:
            saved_transcript_content = file.read()
        podlove_transcript.seek(0)
        submitted_transcript_content = podlove_transcript.read().decode("utf-8")
        assert saved_transcript_content == submitted_transcript_content

    def test_post_add_transcript_ignores_media_upload_lock(self, admin_client, admin_user, audio, podlove_transcript):
        key = f"cast:editor-media-upload:{admin_user.pk}"
        cache.set(key, "other", timeout=60)
        try:
            response = admin_client.post(
                reverse("cast-transcript:add"),
                {"podlove": podlove_transcript, "audio": audio.pk},
            )
        finally:
            cache.delete(key)

        assert response.status_code == 302
        transcript = Transcript.objects.get(audio=audio)
        transcript.podlove.delete(save=False)
