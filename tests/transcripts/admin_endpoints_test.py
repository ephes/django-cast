from unittest.mock import patch

import pytest
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from cast.file_replacement import FileFieldReplacementGuard
from cast.media_ingest import upload_lock_key
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


class TestTranscriptEditIngestion:
    pytestmark = pytest.mark.django_db

    files = {
        "podlove": ("application/json", b'{"transcripts": []}'),
        "dote": ("application/json", b'{"lines": []}'),
        "vtt": ("text/vtt", b"WEBVTT\n"),
    }

    def test_replacements_delete_old_files_only_after_commit(
        self, admin_client, admin_user, transcript_urls, django_capture_on_commit_callbacks
    ):
        transcript = transcript_urls.transcript
        for field_name, (_content_type, content) in self.files.items():
            getattr(transcript, field_name).save(f"old.{field_name}", ContentFile(content), save=False)
        transcript.save()
        old_names = {field_name: getattr(transcript, field_name).name for field_name in self.files}
        storage = transcript.podlove.storage
        uploads = {
            field_name: SimpleUploadedFile(f"new.{field_name}", content, content_type=content_type)
            for field_name, (content_type, content) in self.files.items()
        }

        key = upload_lock_key(admin_user)
        cache.set(key, "other", timeout=60)
        try:
            with django_capture_on_commit_callbacks(execute=False) as callbacks:
                response = admin_client.post(
                    transcript_urls.edit,
                    {"audio": transcript.audio_id, **uploads},
                )
            assert cache.get(key) == "other"
        finally:
            cache.delete(key)

        assert response.status_code == 302
        transcript.refresh_from_db()
        new_names = {field_name: getattr(transcript, field_name).name for field_name in self.files}
        assert all(new_names[name] != old_names[name] for name in self.files)
        assert all(storage.exists(name) for name in (*old_names.values(), *new_names.values()))

        assert len(callbacks) == 1
        callbacks[0]()
        assert all(not storage.exists(name) for name in old_names.values())
        assert all(storage.exists(name) for name in new_names.values())
        for field_name in self.files:
            getattr(transcript, field_name).delete(save=False)

    def test_replacement_failure_keeps_old_file_and_name(
        self, admin_client, transcript_urls, django_capture_on_commit_callbacks, mocker
    ):
        transcript = transcript_urls.transcript
        transcript.podlove.save("old.podlove.json", ContentFile(b'{"transcripts": []}'), save=True)
        old_name = transcript.podlove.name
        storage = transcript.podlove.storage
        delete = mocker.spy(storage, "delete")
        original_commit = FileFieldReplacementGuard.commit

        def fail_after_commit(guard):
            original_commit(guard)
            raise RuntimeError("replacement commit failed")

        mocker.patch.object(FileFieldReplacementGuard, "commit", fail_after_commit)
        upload = SimpleUploadedFile(
            "new.podlove.json",
            b'{"transcripts": [{"text": "new"}]}',
            content_type="application/json",
        )

        with django_capture_on_commit_callbacks(execute=True) as callbacks:
            with pytest.raises(RuntimeError, match="replacement commit failed"):
                admin_client.post(transcript_urls.edit, {"audio": transcript.audio_id, "podlove": upload})

        transcript.refresh_from_db()
        assert transcript.podlove.name == old_name
        assert storage.exists(old_name)
        assert callbacks == []
        deleted_names = [call.args[0] for call in delete.call_args_list]
        assert deleted_names and old_name not in deleted_names
        assert all(not storage.exists(name) for name in deleted_names)
        transcript.podlove.delete(save=False)
