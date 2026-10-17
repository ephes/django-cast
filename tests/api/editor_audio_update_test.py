import subprocess
from datetime import time, timedelta

import pytest
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from cast import media_ingest
from cast.api.editor import media as editor_media
from cast.models import Audio, ChapterMark
from tests.factories import UserFactory

OGG_CONTENT = b"OggS\x00\x02\x00\x00\x00\x00" + b"\x00" * 64


def oga_upload(name: str = "episode.oga") -> SimpleUploadedFile:
    return SimpleUploadedFile(name, OGG_CONTENT, content_type="audio/ogg")


def grant_wagtail_admin_access(user) -> None:
    from django.contrib.auth.models import Permission

    permission = Permission.objects.get(codename="access_admin", content_type__app_label="wagtailadmin")
    user.user_permissions.add(permission)


class _FakeScopedToken:
    def __init__(self, scope: str):
        self.scope = scope


@pytest.fixture
def audio_with_chapters(audio):
    audio.duration = timedelta(seconds=60)
    audio.save(duration=False)
    audio.tags.add("python", "news")
    ChapterMark.objects.create(audio=audio, start=time(0, 0, 0), title="Intro")
    ChapterMark.objects.create(audio=audio, start=time(0, 5, 0), title="News")
    return audio


def detail_url(audio) -> str:
    return reverse("cast:api:editor_media_audio_detail", kwargs={"pk": audio.pk})


class TestEditorAudioDetail:
    pytestmark = pytest.mark.django_db

    def test_get_returns_selectable_audio(self, api_client, superuser, audio):
        api_client.force_authenticate(user=superuser)
        response = api_client.get(detail_url(audio))
        assert response.status_code == 200
        assert response.json()["id"] == audio.pk
        assert response.json()["transcript_diarization_mode"] == "inherit"

    def test_get_hides_missing_and_unselectable_audio(self, api_client, audio):
        user = UserFactory(is_staff=True)
        grant_wagtail_admin_access(user)
        api_client.force_authenticate(user=user)
        assert api_client.get(detail_url(audio)).json() == {"code": "not_found", "detail": "Audio not found."}
        missing = api_client.get(reverse("cast:api:editor_media_audio_detail", kwargs={"pk": 999999}))
        assert missing.status_code == 404

    def test_options_lists_patch(self, api_client, superuser, audio):
        api_client.force_authenticate(user=superuser)
        response = api_client.options(detail_url(audio))
        assert response.status_code == 200
        assert "PATCH" in response["Allow"]


class TestEditorAudioPatch:
    pytestmark = pytest.mark.django_db

    def test_form_encoded_diarization_mode_update_preserves_everything_else(
        self, api_client, superuser, audio_with_chapters, mocker
    ):
        run_probe = mocker.patch("cast.models.audio.run_media_probe")
        api_client.force_authenticate(user=superuser)
        m4a_name = audio_with_chapters.m4a.name

        response = api_client.patch(
            detail_url(audio_with_chapters),
            "transcript_diarization_mode=enabled",
            content_type="application/x-www-form-urlencoded",
        )

        assert response.status_code == 200, response.content
        assert response.json()["transcript_diarization_mode"] == "enabled"
        audio = Audio.objects.get(pk=audio_with_chapters.pk)
        assert audio.transcript_diarization_mode == "enabled"
        assert audio.title == "foobar audio"
        assert audio.m4a.name == m4a_name
        assert sorted(tag.name for tag in audio.tags.all()) == ["news", "python"]
        assert list(audio.chaptermarks.order_by("start").values_list("title", flat=True)) == ["Intro", "News"]
        run_probe.assert_not_called()

    def test_json_update_of_metadata(self, api_client, superuser, audio):
        api_client.force_authenticate(user=superuser)
        response = api_client.patch(
            detail_url(audio),
            {"title": "New title", "subtitle": "Sub", "tags": "one, two", "transcript_diarization_mode": "disabled"},
            format="json",
        )
        assert response.status_code == 200, response.content
        data = response.json()
        assert data["title"] == "New title"
        assert data["subtitle"] == "Sub"
        assert data["tags"] == ["one", "two"]
        assert data["transcript_diarization_mode"] == "disabled"

    def test_adding_a_format_keeps_existing_files_and_chapter_marks(
        self, api_client, superuser, audio_with_chapters, mocker
    ):
        run_probe = mocker.patch(
            "cast.models.audio.run_media_probe",
            return_value=subprocess.CompletedProcess([], 0, stdout=b"62.500000\n"),
        )
        lock = mocker.patch.object(editor_media, "upload_lock", wraps=media_ingest.upload_lock)
        api_client.force_authenticate(user=superuser)
        m4a_name = audio_with_chapters.m4a.name

        response = api_client.patch(detail_url(audio_with_chapters), {"oga": oga_upload()}, format="multipart")

        assert response.status_code == 200, response.content
        data = response.json()
        assert data["file_formats"] == "m4a oga"
        assert data["oga"].startswith("/media/cast_audio/")
        audio = Audio.objects.get(pk=audio_with_chapters.pk)
        assert audio.m4a.name == m4a_name
        assert audio.oga.name.endswith(".oga")
        assert audio.duration.total_seconds() == 62.5
        assert list(audio.chaptermarks.order_by("start").values_list("title", flat=True)) == ["Intro", "News"]
        # Only the duration probe ran; chapter extraction is skipped without ``chaptermarks``.
        assert run_probe.call_count == 1
        lock.assert_called_once()
        audio.oga.delete(save=False)

    def test_sent_chaptermarks_replace_existing_marks(self, api_client, superuser, audio_with_chapters):
        api_client.force_authenticate(user=superuser)
        response = api_client.patch(
            detail_url(audio_with_chapters),
            {"chaptermarks": "00:00:00 Start\n00:10:00 Topic"},
            format="json",
        )
        assert response.status_code == 200, response.content
        assert list(audio_with_chapters.chaptermarks.order_by("start").values_list("title", flat=True)) == [
            "Start",
            "Topic",
        ]

    def test_validation_errors(self, api_client, superuser, audio, m4a_audio):
        api_client.force_authenticate(user=superuser)
        url = detail_url(audio)

        empty = api_client.patch(url, {}, format="json")
        assert empty.status_code == 400
        assert empty.json()["errors"]["non_field_errors"][0]["code"] == "required"

        unsupported = api_client.patch(url, {"collection": 1, "m4a-clear": "on"}, format="multipart")
        assert unsupported.status_code == 400
        assert set(unsupported.json()["errors"]) == {"collection", "m4a-clear"}
        assert unsupported.json()["errors"]["collection"][0]["code"] == "unsupported_field"

        invalid_mode = api_client.patch(url, {"transcript_diarization_mode": "maybe"}, format="json")
        assert invalid_mode.status_code == 400
        assert invalid_mode.json()["errors"]["transcript_diarization_mode"][0]["code"] == "invalid_choice"

        non_string = api_client.patch(url, {"tags": ["a", "b"]}, format="json")
        assert non_string.status_code == 400
        assert non_string.json()["errors"]["tags"][0]["code"] == "invalid"

        too_many = api_client.patch(url, {"oga": oga_upload(), "m4a": m4a_audio}, format="multipart")
        assert too_many.status_code == 400
        assert too_many.json()["errors"]["non_field_errors"][0]["code"] == "too_many_files"

        bad_file = SimpleUploadedFile("episode.txt", b"not audio", content_type="text/plain")
        invalid_file = api_client.patch(url, {"opus": bad_file}, format="multipart")
        assert invalid_file.status_code == 400
        assert "opus" in invalid_file.json()["errors"]

        audio.refresh_from_db()
        assert audio.transcript_diarization_mode == "inherit"
        assert not audio.oga

    def test_requires_change_permission(self, api_client, superuser, audio, mocker):
        api_client.force_authenticate(user=superuser)
        original = editor_media.audio_permission_policy.user_has_permission_for_instance

        def deny_change(user, action, instance):
            return action != "change" and original(user, action, instance)

        mocker.patch.object(
            editor_media.audio_permission_policy, "user_has_permission_for_instance", side_effect=deny_change
        )
        response = api_client.patch(detail_url(audio), {"title": "Nope"}, format="json")
        assert response.status_code == 403
        assert response.json() == {"code": "permission_denied", "detail": "You cannot change this audio."}

    def test_write_scope_is_required(self, api_client, superuser, audio):
        api_client.force_authenticate(user=superuser, token=_FakeScopedToken("publish"))
        response = api_client.patch(detail_url(audio), {"title": "Nope"}, format="json")
        assert response.status_code == 403
        assert response.json()["code"] == "insufficient_scope"

        api_client.force_authenticate(user=superuser, token=_FakeScopedToken("write"))
        assert api_client.get(detail_url(audio)).status_code == 200
        assert api_client.patch(detail_url(audio), {"title": "Yes"}, format="json").status_code == 200

    def test_file_upload_shares_the_upload_lock(self, api_client, superuser, audio):
        cache.add(media_ingest.upload_lock_key(superuser), "other-owner", timeout=60)
        try:
            api_client.force_authenticate(user=superuser)
            response = api_client.patch(detail_url(audio), {"oga": oga_upload()}, format="multipart")
        finally:
            cache.delete(media_ingest.upload_lock_key(superuser))
        assert response.status_code == 429
        assert response.json()["code"] == "rate_limited"

    def test_probe_timeout_keeps_the_stored_audio(self, api_client, superuser, audio_with_chapters, mocker):
        mocker.patch(
            "cast.models.audio.run_media_probe",
            side_effect=subprocess.TimeoutExpired(cmd="ffprobe", timeout=1),
        )
        api_client.force_authenticate(user=superuser)
        response = api_client.patch(detail_url(audio_with_chapters), {"oga": oga_upload()}, format="multipart")
        assert response.status_code == 422
        assert response.json()["code"] == "probe_timeout"
        audio = Audio.objects.get(pk=audio_with_chapters.pk)
        assert not audio.oga
        assert audio.m4a
        assert audio.chaptermarks.count() == 2

    @pytest.mark.parametrize(
        "error, expected_status, expected_code",
        [
            (media_ingest.MediaProbeFailed("bad"), 422, "probe_failed"),
            (media_ingest.MediaIngestCleanupFailed("bad"), 500, "cleanup_failed"),
        ],
    )
    def test_ingest_errors_use_media_envelopes(
        self, api_client, superuser, audio, mocker, error, expected_status, expected_code
    ):
        mocker.patch.object(editor_media, "ingest_upload", side_effect=error)
        api_client.force_authenticate(user=superuser)
        response = api_client.patch(detail_url(audio), {"title": "x"}, format="json")
        assert response.status_code == expected_status
        assert response.json()["code"] == expected_code

    def test_unexpected_ingest_error_is_reraised(self, audio):
        with pytest.raises(media_ingest.MediaUploadInProgress):
            editor_media._audio_ingest_error_response(media_ingest.MediaUploadInProgress(), audio)


class TestEditorAudioPatchConcurrency:
    pytestmark = pytest.mark.django_db

    def test_metadata_patch_saves_the_current_row_not_a_stale_read(self, api_client, superuser, audio, mocker):
        # Another request replaced the m4a after this request looked the audio up.
        stale = Audio.objects.get(pk=audio.pk)
        replacement = SimpleUploadedFile("replacement.m4a", audio.m4a.read(), content_type="audio/mp4")
        audio.m4a.save("replacement.m4a", replacement, save=False)
        audio.duration = timedelta(seconds=60)
        audio.save(duration=False)
        current_name = audio.m4a.name
        assert stale.m4a.name != current_name
        mocker.patch.object(editor_media.EditorAudioDetailView, "_get_audio", return_value=stale)
        api_client.force_authenticate(user=superuser)

        response = api_client.patch(detail_url(audio), {"title": "Renamed"}, format="json")

        assert response.status_code == 200, response.content
        audio.refresh_from_db()
        assert audio.title == "Renamed"
        assert audio.m4a.name == current_name
        assert audio.m4a.storage.exists(current_name)
        audio.m4a.delete(save=False)

    def test_audio_deleted_after_lookup_is_not_found(self, api_client, superuser, audio, mocker):
        stale = Audio.objects.get(pk=audio.pk)
        mocker.patch.object(editor_media.EditorAudioDetailView, "_get_audio", return_value=stale)
        Audio.objects.filter(pk=audio.pk).delete()
        api_client.force_authenticate(user=superuser)

        response = api_client.patch(detail_url(stale), {"title": "Gone"}, format="json")

        assert response.status_code == 404
        assert response.json()["code"] == "not_found"
