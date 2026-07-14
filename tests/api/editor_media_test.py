# ruff: noqa: F401,F811,I001
import json
import subprocess

import pytest
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth.models import Group, Permission
from django.urls import reverse
from rest_framework import status
from rest_framework.response import Response
from wagtail.models import Collection, GroupCollectionPermission, GroupPagePermission, Page

from cast import media_probe
from cast.api.editor import media as editor_media
from cast.api.editor.body import (
    SUPPORTED_OVERVIEW_BLOCKS,
    _media_ref_is_available,
    author_blocks_to_overview,
    overview_to_author_blocks,
)
from cast.api.editor.errors import (
    EditorNotFound,
    EditorPermissionDenied,
    EditorValidationError,
    editor_exception_handler,
)
from cast.models import Audio, Episode, Post, Season, Video
from cast.models.snippets import PostCategory

from tests.factories import BlogFactory, EpisodeFactory, PodcastFactory, PostFactory, UserFactory


def grant_wagtail_admin_access(user) -> None:
    permission = Permission.objects.get(codename="access_admin", content_type__app_label="wagtailadmin")
    user.user_permissions.add(permission)


def grant_collection_permission(user, collection, *, app_label: str, codename: str) -> None:
    group = Group.objects.create(name=f"Collection permission {user.pk} {codename} {collection.pk}")
    permission = Permission.objects.get(codename=codename, content_type__app_label=app_label)
    GroupCollectionPermission.objects.create(group=group, collection=collection, permission=permission)
    user.groups.add(group)


def page_permission_user(*, codenames: tuple[str, ...]) -> object:
    user = UserFactory(is_staff=True)
    group = Group.objects.create(name=f"Page permissions {user.pk}")
    root_page = Page.get_first_root_node()
    assert root_page is not None
    for codename in codenames:
        permission = Permission.objects.get(codename=codename, content_type__app_label="wagtailcore")
        GroupPagePermission.objects.create(group=group, page=root_page, permission=permission)
    user.groups.add(group)
    return user


@pytest.fixture
def superuser(django_user_model):
    """A superuser, which passes every Wagtail page and image ``choose`` permission."""
    return django_user_model.objects.create_superuser(
        username="editor-su", email="editor-su@example.com", password="password"
    )


class TestEditorMediaEndpoints:
    pytestmark = pytest.mark.django_db

    def test_media_lists_filter_by_query_and_tag(self, api_client, superuser, image, audio, video):
        image.title = "Desk photo"
        image.tags.add("weeknotes", "desk")
        image.save()
        audio.title = "Episode audio"
        audio.subtitle = "Interview mix"
        audio.tags.add("weeknotes")
        audio.save(duration=False)
        video.title = "Demo clip"
        video.tags.add("weeknotes")
        video.save(poster=False)

        api_client.force_authenticate(user=superuser)

        image_url = reverse("cast:api:editor_media_images")
        image_response = api_client.get(f"{image_url}?q=Desk&tag=weeknotes", format="json")
        assert image_response.status_code == 200
        image_results = image_response.json()["results"]
        assert image_results[0]["id"] == image.id
        assert image_results[0]["file"].startswith("/media/")
        assert image_results[0]["collection"]["id"] == image.collection_id

        audio_url = reverse("cast:api:editor_media_audios")
        audio_response = api_client.get(f"{audio_url}?q=Interview&tag=weeknotes", format="json")
        assert audio_response.status_code == 200
        assert audio_response.json()["results"][0]["id"] == audio.id
        assert audio_response.json()["results"][0]["transcript_diarization_mode"] == "inherit"

        video_url = reverse("cast:api:editor_media_videos")
        video_response = api_client.get(f"{video_url}?q=Demo&tag=weeknotes", format="json")
        assert video_response.status_code == 200
        assert video_response.json()["results"][0]["id"] == video.id

    def test_media_lists_without_query_and_nullable_serialization(self, api_client, superuser, audio, video):
        audio.m4a = None
        audio.save(duration=False)
        video.poster = None
        video.save(poster=False)
        api_client.force_authenticate(user=superuser)

        image_response = api_client.get(reverse("cast:api:editor_media_images"), format="json")
        assert image_response.status_code == 200

        audio_response = api_client.get(reverse("cast:api:editor_media_audios"), format="json")
        assert audio_response.status_code == 200
        audio_item = next(item for item in audio_response.json()["results"] if item["id"] == audio.id)
        assert audio_item["m4a"] is None

        video_response = api_client.get(reverse("cast:api:editor_media_videos"), format="json")
        assert video_response.status_code == 200
        video_item = next(item for item in video_response.json()["results"] if item["id"] == video.id)
        assert video_item["poster"] is None

    def test_media_list_rejects_unsupported_parameter(self, api_client, superuser):
        api_client.force_authenticate(user=superuser)
        url = reverse("cast:api:editor_media_images")
        response = api_client.get(f"{url}?tags=weeknotes", format="json")
        assert response.status_code == 400
        assert response.json()["errors"]["tags"][0]["code"] == "unsupported_parameter"

    def test_media_list_out_of_range_page_uses_editor_envelope(self, api_client, superuser):
        api_client.force_authenticate(user=superuser)
        url = reverse("cast:api:editor_media_images")
        response = api_client.get(f"{url}?page=999999", format="json")
        assert response.status_code == 404
        assert response.json()["code"] == "not_found"
        assert "Invalid page" in response.json()["detail"]

    def test_media_endpoint_requires_wagtail_admin_access_envelope(self, api_client):
        user = UserFactory(is_staff=True)
        api_client.force_authenticate(user=user)
        response = api_client.get(reverse("cast:api:editor_media_images"), format="json")
        assert response.status_code == 403
        assert response.json() == {
            "code": "permission_denied",
            "detail": "You do not have access to the Wagtail admin.",
        }

    def test_collection_discovery_validation_and_success(self, api_client, superuser):
        api_client.force_authenticate(user=superuser)
        url = reverse("cast:api:editor_media_collections")

        missing = api_client.get(url, format="json")
        assert missing.status_code == 400
        assert missing.json()["errors"]["type"][0]["code"] == "required"

        invalid = api_client.get(f"{url}?type=file", format="json")
        assert invalid.status_code == 400
        assert invalid.json()["errors"]["type"][0]["code"] == "invalid_choice"

        valid = api_client.get(f"{url}?type=audio", format="json")
        assert valid.status_code == 200
        assert valid.json()["results"][0]["id"] == Collection.get_first_root_node().id
        assert "breadcrumb" in valid.json()["results"][0]

        image = api_client.get(f"{url}?type=image", format="json")
        assert image.status_code == 200
        video = api_client.get(f"{url}?type=video", format="json")
        assert video.status_code == 200

        root = Collection.get_first_root_node()
        child = root.add_child(instance=Collection(name="Child fallback"))
        assert editor_media._collection_item(child)["ancestors"][0]["id"] == root.id

    def test_collection_discovery_rejects_unsupported_parameter(self, api_client, superuser):
        api_client.force_authenticate(user=superuser)
        url = reverse("cast:api:editor_media_collections")
        response = api_client.get(f"{url}?type=audio&q=x", format="json")
        assert response.status_code == 400
        assert response.json()["errors"]["q"][0]["code"] == "unsupported_parameter"

    def test_image_upload_and_no_collection_error(self, api_client, superuser, image_1px):
        api_client.force_authenticate(user=superuser)
        url = reverse("cast:api:editor_media_images")
        response = api_client.post(
            url,
            {"title": "Uploaded image", "file": image_1px, "collection": Collection.get_first_root_node().id},
            format="multipart",
        )
        assert response.status_code == 201, response.content
        data = response.json()
        assert data["title"] == "Uploaded image"
        assert data["collection"]["id"] == Collection.get_first_root_node().id

        user = UserFactory(is_staff=True)
        grant_wagtail_admin_access(user)
        api_client.force_authenticate(user=user)
        denied = api_client.post(url, {"title": "No collection", "file": image_1px}, format="multipart")
        assert denied.status_code == 403
        assert denied.json()["code"] == "no_upload_collection"

    def test_image_upload_collection_validation_and_form_errors(self, api_client, superuser):
        api_client.force_authenticate(user=superuser)
        url = reverse("cast:api:editor_media_images")

        malformed = api_client.post(url, {"collection": "nope"}, format="multipart")
        assert malformed.status_code == 400
        assert malformed.json()["errors"]["collection"][0]["code"] == "invalid"
        with pytest.raises(EditorValidationError):
            editor_media._parse_collection_id(True)

        missing = api_client.post(url, {"collection": 999999}, format="multipart")
        assert missing.status_code == 400
        assert missing.json()["errors"]["collection"][0]["code"] == "collection_permission_denied"

        form_error = api_client.post(url, {"title": "Missing file"}, format="multipart")
        assert form_error.status_code == 400
        assert form_error.json()["errors"]["file"][0]["code"] == "required"

    def test_image_upload_ambiguous_collection(self, api_client, image_1px):
        image_bytes = image_1px.read()
        user = UserFactory(is_staff=True)
        grant_wagtail_admin_access(user)
        root = Collection.get_first_root_node()
        child = root.add_child(instance=Collection(name="Second media collection"))
        for collection in (root, child):
            for codename in ("add_image", "choose_image"):
                grant_collection_permission(user, collection, app_label="wagtailimages", codename=codename)
        api_client.force_authenticate(user=user)

        response = api_client.post(
            reverse("cast:api:editor_media_images"),
            {
                "title": "Ambiguous",
                "file": SimpleUploadedFile("ambiguous.png", image_bytes, content_type="image/png"),
            },
            format="multipart",
        )

        assert response.status_code == 400
        assert response.json()["errors"]["collection"][0]["code"] == "ambiguous"

        explicit = api_client.post(
            reverse("cast:api:editor_media_images"),
            {
                "title": "Explicit collection",
                "file": SimpleUploadedFile("explicit.png", image_bytes, content_type="image/png"),
                "collection": child.id,
            },
            format="multipart",
        )

        assert explicit.status_code == 201, explicit.content
        assert explicit.json()["collection"]["id"] == child.id

    def test_audio_upload_uses_probe_budget_and_rejects_enabled_diarization(
        self, api_client, superuser, m4a_audio, mp3_audio, mocker
    ):
        run_probe = mocker.patch(
            "cast.models.audio.run_media_probe",
            side_effect=[
                subprocess.CompletedProcess([], 0, stdout=b"1.000000\n"),
                subprocess.CompletedProcess([], 0, stdout=b'{"chapters": []}'),
            ],
        )
        api_client.force_authenticate(user=superuser)
        url = reverse("cast:api:editor_media_audios")
        response = api_client.post(url, {"title": "Uploaded audio", "m4a": m4a_audio}, format="multipart")
        assert response.status_code == 201, response.content
        data = response.json()
        assert data["title"] == "Uploaded audio"
        assert data["m4a"].startswith("/media/")
        assert run_probe.call_count == 2

        blocked = api_client.post(
            url,
            {
                "title": "Diarization",
                "transcript_diarization_mode": Audio.TranscriptDiarizationMode.ENABLED,
                "mp3": mp3_audio,
            },
            format="multipart",
        )
        assert blocked.status_code == 400
        assert blocked.json()["errors"]["transcript_diarization_mode"][0]["code"] == "unsupported"

    def test_audio_upload_rejects_multiple_files_and_form_errors(self, api_client, superuser, m4a_audio, mp3_audio):
        api_client.force_authenticate(user=superuser)
        url = reverse("cast:api:editor_media_audios")

        missing = api_client.post(url, {"title": "Missing audio"}, format="multipart")
        assert missing.status_code == 400
        assert missing.json()["errors"]["non_field_errors"][0]["code"] == "required"

        too_many = api_client.post(url, {"m4a": m4a_audio, "mp3": mp3_audio}, format="multipart")
        assert too_many.status_code == 400
        assert too_many.json()["errors"]["non_field_errors"][0]["code"] == "too_many_files"

        invalid_upload = SimpleUploadedFile("bad.txt", b"ID3-not-really-enough", content_type="audio/mpeg")
        invalid = api_client.post(url, {"title": "Invalid audio", "mp3": invalid_upload}, format="multipart")
        assert invalid.status_code == 400
        assert invalid.json()["errors"]["mp3"][0]["code"] == "invalid_extension"

    def test_audio_post_save_permission_denied_and_cleanup_failed(self, api_client, superuser, m4a_audio, mocker):
        upload_bytes = m4a_audio.read()
        first_upload = SimpleUploadedFile("first.m4a", upload_bytes, content_type="audio/mp4")
        second_upload = SimpleUploadedFile("second.m4a", upload_bytes, content_type="audio/mp4")
        mocker.patch(
            "cast.models.audio.run_media_probe",
            side_effect=[
                subprocess.CompletedProcess([], 0, stdout=b"1.000000\n"),
                subprocess.CompletedProcess([], 0, stdout=b'{"chapters": []}'),
                subprocess.CompletedProcess([], 0, stdout=b"1.000000\n"),
                subprocess.CompletedProcess([], 0, stdout=b'{"chapters": []}'),
            ],
        )
        mocker.patch.object(
            editor_media.audio_permission_policy, "user_has_permission_for_instance", return_value=False
        )
        api_client.force_authenticate(user=superuser)
        url = reverse("cast:api:editor_media_audios")

        denied = api_client.post(url, {"title": "Denied audio", "m4a": first_upload}, format="multipart")
        assert denied.status_code == 403
        assert denied.json()["code"] == "post_save_permission_denied"
        assert not Audio.objects.filter(title="Denied audio").exists()

        mocker.patch("cast.api.editor.media._cleanup_media_object", return_value=False)
        failed = api_client.post(url, {"title": "Cleanup audio", "m4a": second_upload}, format="multipart")
        assert failed.status_code == 500
        assert failed.json()["code"] == "cleanup_failed"

    def test_audio_upload_timeout_cleans_up(self, api_client, superuser, m4a_audio, mocker):
        mocker.patch(
            "cast.models.audio.run_media_probe",
            side_effect=subprocess.TimeoutExpired(cmd="ffprobe", timeout=1),
        )
        api_client.force_authenticate(user=superuser)
        url = reverse("cast:api:editor_media_audios")

        response = api_client.post(url, {"title": "Slow audio", "m4a": m4a_audio}, format="multipart")

        assert response.status_code == 422
        assert response.json()["code"] == "probe_timeout"
        assert not Audio.objects.filter(title="Slow audio").exists()

    def test_audio_upload_probe_failure_cleans_up(self, api_client, superuser, m4a_audio, mocker):
        mocker.patch(
            "cast.models.audio.run_media_probe",
            return_value=subprocess.CompletedProcess([], 0, stdout=b"N/A\n"),
        )
        api_client.force_authenticate(user=superuser)
        url = reverse("cast:api:editor_media_audios")

        response = api_client.post(url, {"title": "Bad duration audio", "m4a": m4a_audio}, format="multipart")

        assert response.status_code == 422
        assert response.json()["code"] == "probe_failed"
        assert not Audio.objects.filter(title="Bad duration audio").exists()

    def test_audio_upload_probe_oserror_cleans_up(self, api_client, superuser, m4a_audio, mocker):
        mocker.patch("cast.models.audio.run_media_probe", side_effect=OSError("ffprobe missing"))
        api_client.force_authenticate(user=superuser)
        url = reverse("cast:api:editor_media_audios")

        response = api_client.post(url, {"title": "Missing ffprobe audio", "m4a": m4a_audio}, format="multipart")

        assert response.status_code == 422
        assert response.json()["code"] == "probe_failed"
        assert not Audio.objects.filter(title="Missing ffprobe audio").exists()

    def test_audio_upload_probe_failure_cleanup_failed(self, api_client, superuser, m4a_audio, mocker):
        mocker.patch(
            "cast.models.audio.run_media_probe",
            side_effect=subprocess.CalledProcessError(returncode=1, cmd="ffprobe"),
        )
        mocker.patch("cast.api.editor.media._cleanup_media_object", return_value=False)
        api_client.force_authenticate(user=superuser)
        url = reverse("cast:api:editor_media_audios")

        response = api_client.post(url, {"title": "Bad cleanup audio", "m4a": m4a_audio}, format="multipart")

        assert response.status_code == 500
        assert response.json()["code"] == "cleanup_failed"

    def test_audio_upload_chapter_timeout_keeps_saved_audio(self, api_client, superuser, m4a_audio, mocker):
        run_probe = mocker.patch(
            "cast.models.audio.run_media_probe",
            side_effect=[
                subprocess.CompletedProcess([], 0, stdout=b"1.000000\n"),
                subprocess.TimeoutExpired(cmd="ffprobe", timeout=1),
            ],
        )
        api_client.force_authenticate(user=superuser)
        url = reverse("cast:api:editor_media_audios")

        response = api_client.post(
            url, {"title": "Audio without extracted chapters", "m4a": m4a_audio}, format="multipart"
        )

        assert response.status_code == 201, response.content
        audio = Audio.objects.get(id=response.json()["id"])
        assert audio.title == "Audio without extracted chapters"
        assert audio.chaptermarks.count() == 0
        assert run_probe.call_count == 2

    def test_audio_upload_malformed_chapter_marks_keep_saved_audio(self, api_client, superuser, m4a_audio, mocker):
        mocker.patch(
            "cast.models.audio.run_media_probe",
            side_effect=[
                subprocess.CompletedProcess([], 0, stdout=b"1.000000\n"),
                subprocess.CompletedProcess([], 0, stdout=b'{"chapters": [{"start_time": "1.000000", "tags": {}}]}'),
            ],
        )
        api_client.force_authenticate(user=superuser)
        url = reverse("cast:api:editor_media_audios")

        response = api_client.post(
            url, {"title": "Audio with malformed chapters", "m4a": m4a_audio}, format="multipart"
        )

        assert response.status_code == 201, response.content
        audio = Audio.objects.get(id=response.json()["id"])
        assert audio.title == "Audio with malformed chapters"
        assert audio.chaptermarks.count() == 0

    def test_editor_media_probe_budget_setting_is_used(self, api_client, superuser, m4a_audio, mocker, settings):
        settings.CAST_EDITOR_MEDIA_PROBE_SECONDS = 3
        budget = mocker.patch("cast.api.editor.media.media_probe_budget", wraps=media_probe.media_probe_budget)
        mocker.patch(
            "cast.models.audio.run_media_probe",
            side_effect=[
                subprocess.CompletedProcess([], 0, stdout=b"1.000000\n"),
                subprocess.CompletedProcess([], 0, stdout=b'{"chapters": []}'),
            ],
        )
        api_client.force_authenticate(user=superuser)

        response = api_client.post(
            reverse("cast:api:editor_media_audios"), {"title": "Budget audio", "m4a": m4a_audio}, format="multipart"
        )

        assert response.status_code == 201, response.content
        budget.assert_called_once_with(3.0)

    def test_audio_upload_timeout_cleanup_failed(self, api_client, superuser, m4a_audio, mocker):
        mocker.patch(
            "cast.models.audio.run_media_probe",
            side_effect=subprocess.TimeoutExpired(cmd="ffprobe", timeout=1),
        )
        mocker.patch("cast.api.editor.media._cleanup_media_object", return_value=False)
        api_client.force_authenticate(user=superuser)
        url = reverse("cast:api:editor_media_audios")

        response = api_client.post(url, {"title": "Slow cleanup audio", "m4a": m4a_audio}, format="multipart")

        assert response.status_code == 500
        assert response.json()["code"] == "cleanup_failed"

    def test_audio_video_upload_lock(self, api_client, superuser):
        api_client.force_authenticate(user=superuser)
        cache.set(f"cast:editor-media-upload:{superuser.pk}", "1", timeout=60)
        url = reverse("cast:api:editor_media_audios")
        response = api_client.post(url, {"title": "Locked"}, format="multipart")
        assert response.status_code == 429
        assert response.json()["code"] == "rate_limited"
        cache.delete(f"cast:editor-media-upload:{superuser.pk}")

    def test_upload_lock_does_not_release_another_owner(self, superuser):
        key = f"cast:editor-media-upload:{superuser.pk}"
        cache.delete(key)

        def callback():
            cache.set(key, "other-owner", timeout=60)
            return Response({"ok": True})

        response = editor_media._with_upload_lock(superuser, callback)

        assert response.status_code == 200
        assert cache.get(key) == "other-owner"
        cache.delete(key)

    def test_video_upload_with_supplied_poster(self, api_client, superuser, minimal_mp4, image_1px):
        api_client.force_authenticate(user=superuser)
        url = reverse("cast:api:editor_media_videos")

        response = api_client.post(
            url,
            {"title": "Uploaded video", "original": minimal_mp4, "poster": image_1px},
            format="multipart",
        )

        assert response.status_code == 201, response.content
        data = response.json()
        assert data["title"] == "Uploaded video"
        assert data["original"].startswith("/media/")
        assert data["poster"].startswith("/media/")
        assert Video.objects.filter(id=data["id"]).exists()

    def test_video_upload_with_explicit_collection_when_multiple_exist(self, api_client, minimal_mp4, image_1px):
        video_bytes = minimal_mp4.read()
        poster_bytes = image_1px.read()
        user = UserFactory(is_staff=True)
        grant_wagtail_admin_access(user)
        root = Collection.get_first_root_node()
        child = root.add_child(instance=Collection(name="Second video collection"))
        for collection in (root, child):
            for codename in ("add_video", "choose_video"):
                grant_collection_permission(user, collection, app_label="cast", codename=codename)
        api_client.force_authenticate(user=user)

        response = api_client.post(
            reverse("cast:api:editor_media_videos"),
            {
                "title": "Explicit video collection",
                "original": SimpleUploadedFile("explicit.mp4", video_bytes, content_type="video/mp4"),
                "poster": SimpleUploadedFile("explicit.png", poster_bytes, content_type="image/png"),
                "collection": child.id,
            },
            format="multipart",
        )

        assert response.status_code == 201, response.content
        assert response.json()["collection"]["id"] == child.id

    def test_video_upload_poster_probe_timeout_succeeds_without_poster(
        self, api_client, superuser, minimal_mp4, mocker
    ):
        run_probe = mocker.patch(
            "cast.models.video.run_media_probe",
            side_effect=subprocess.TimeoutExpired(cmd="ffprobe", timeout=1),
        )
        api_client.force_authenticate(user=superuser)

        response = api_client.post(
            reverse("cast:api:editor_media_videos"),
            {"title": "Video without poster", "original": minimal_mp4},
            format="multipart",
        )

        assert response.status_code == 201, response.content
        data = response.json()
        assert data["poster"] is None
        assert Video.objects.filter(id=data["id"]).exists()
        assert run_probe.call_count == 1

    def test_video_upload_form_and_post_save_errors(self, api_client, superuser, minimal_mp4, mocker):
        upload_bytes = minimal_mp4.read()
        first_upload = SimpleUploadedFile("first.mp4", upload_bytes, content_type="video/mp4")
        second_upload = SimpleUploadedFile("second.mp4", upload_bytes, content_type="video/mp4")
        api_client.force_authenticate(user=superuser)
        url = reverse("cast:api:editor_media_videos")

        missing = api_client.post(url, {"title": "Missing original"}, format="multipart")
        assert missing.status_code == 400
        assert missing.json()["errors"]["original"][0]["code"] == "required"

        mocker.patch.object(
            editor_media.video_permission_policy, "user_has_permission_for_instance", return_value=False
        )
        denied = api_client.post(url, {"title": "Denied video", "original": first_upload}, format="multipart")
        assert denied.status_code == 403
        assert denied.json()["code"] == "post_save_permission_denied"

        mocker.patch("cast.api.editor.media._cleanup_media_object", return_value=False)
        failed = api_client.post(url, {"title": "Cleanup video", "original": second_upload}, format="multipart")
        assert failed.status_code == 500
        assert failed.json()["code"] == "cleanup_failed"

    def test_private_media_helpers(self, audio, superuser, mocker):
        assert editor_media._relative_field_url(False) is None
        assert editor_media._collection_ref(object()) is None

        class BrokenField:
            @property
            def url(self):
                raise ValueError

        assert editor_media._relative_field_url(BrokenField()) is None

        class AbsoluteField:
            url = "https://cdn.example.com/media/audio/test.mp3?token=abc"

        assert editor_media._relative_field_url(AbsoluteField()) == "/media/audio/test.mp3?token=abc"

        policy = mocker.Mock()
        policy.user_has_permission_for_instance.return_value = False
        assert editor_media._edit_url(superuser, audio, policy=policy, route_name="castaudio:edit") is None
        policy.user_has_permission_for_instance.return_value = True
        assert editor_media._edit_url(superuser, audio, policy=policy, route_name="missing:route") is None

        class FormError:
            code = None
            messages = ["bad form"]

        class ErrorData(dict):
            def as_data(self):
                return {"__all__": [FormError()]}

        class Form:
            errors = ErrorData()

        assert editor_media._form_errors(Form()) == {"non_field_errors": [{"code": "invalid", "message": "bad form"}]}

        class FailingField:
            name = "stored.bin"

            def delete(self, *, save):
                raise OSError("delete failed")

        class ObjectWithFailingField:
            pk = None
            broken = FailingField()
            _meta = mocker.Mock(label="cast.Broken")

        assert editor_media._cleanup_media_object(ObjectWithFailingField(), ("broken",)) is False

        class EmptyField:
            name = ""

        class UnsavedObject:
            pk = None
            empty = EmptyField()
            _meta = mocker.Mock(label="cast.Empty")

        assert editor_media._cleanup_media_object(UnsavedObject(), ("empty",)) is True


class TestMediaProbeBudget:
    def test_remaining_timeout_defaults_and_budget(self):
        assert media_probe.remaining_probe_timeout(12) == 12
        assert media_probe.media_probe_budget_active() is False
        with media_probe.media_probe_budget(30):
            assert media_probe.media_probe_budget_active() is True
            assert 0 < media_probe.remaining_probe_timeout(60) <= 30
        assert media_probe.media_probe_budget_active() is False

    def test_expired_budget_raises(self):
        with pytest.raises(subprocess.TimeoutExpired):
            with media_probe.media_probe_budget(-1):
                media_probe.remaining_probe_timeout(60)

    def test_run_media_probe_applies_timeout(self, mocker):
        run = mocker.patch("cast.media_probe.subprocess.run")
        media_probe.run_media_probe(["ffprobe"], check=True, timeout=7)
        assert run.call_args.kwargs["timeout"] == 7
