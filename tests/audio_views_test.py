import subprocess
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from wagtail.models import Collection, GroupCollectionPermission

from cast.models import Audio


def invalid_m4a_upload():
    return SimpleUploadedFile("invalid.m4a", b"not a media file", content_type="audio/mp4")


def minimal_mp3_upload(name: str = "test.mp3") -> SimpleUploadedFile:
    return SimpleUploadedFile(name, b"ID3" + b"\x00" * 32, content_type="audio/mpeg")


class TestPostWithAudioDetail:
    pytestmark = pytest.mark.django_db

    def test_get_post_with_audio_detail(self, client, post_with_audio):
        audio = post_with_audio.audios.first()
        detail_url = post_with_audio.get_url()

        r = client.get(detail_url)
        assert r.status_code == 200

        content = r.content.decode("utf-8")
        assert "html" in content

        # make sure audio is included in rendered audio block
        assert "block-audio" in content
        assert f"audio_{audio.pk}" in content


def get_endpoint_urls_without_args():
    urls = {}
    view_names = ["index", "add", "chooser", "chooser_upload"]
    for view_name in view_names:
        urls[view_name] = reverse(f"castaudio:{view_name}")
    return urls


def get_endpoint_urls_with_args(audio):
    urls = {}
    view_names = ["edit", "delete", "chosen"]
    for view_name in view_names:
        urls[view_name] = reverse(f"castaudio:{view_name}", args=(audio.id,))
    return urls


class AudioUrls:
    def __init__(self, audio):
        self.audio = audio
        self.urls = get_endpoint_urls_without_args()
        self.urls.update(get_endpoint_urls_with_args(audio))

    def __getattr__(self, item):
        return self.urls[item]


@pytest.fixture
def audio_urls(audio):
    return AudioUrls(audio)


class TestAllAudioEndpoints:
    pytestmark = pytest.mark.django_db

    def test_get_all_not_authenticated(self, client, audio_urls):
        for view_name, url in audio_urls.urls.items():
            r = client.get(url)

            # redirect to log in
            assert r.status_code == 302
            login_url = reverse("wagtailadmin_login")
            assert login_url in r.url

    def test_get_index_authenticated_without_permissions(self, authenticated_client, audio_urls):
        r = authenticated_client.get(audio_urls.index)
        assert r.status_code in {302, 403}
        if r.status_code == 302:
            assert reverse("wagtailadmin_login") in r.url

    def test_get_all_authenticated(self, admin_client, audio_urls):
        for view_name, url in audio_urls.urls.items():
            r = admin_client.get(url)

            # assert we are not redirected to log in
            assert r.status_code == 200


class TestAudioIndex:
    pytestmark = pytest.mark.django_db

    def test_get_index(self, admin_client, audio_urls):
        r = admin_client.get(audio_urls.index)

        assert r.status_code == 200
        content = r.content.decode("utf-8")

        # make sure it's the media results page
        assert "html" in content
        assert "media-results" in content

        # make sure audio_urls.audio is included in results
        assert audio_urls.audio.title in content

    def test_get_index_ajax(self, admin_client, audio_urls):
        headers = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"}
        r = admin_client.get(audio_urls.index, **headers)

        assert r.status_code == 200
        content = r.content.decode("utf-8")

        # make sure it's the media results page
        assert "table" in content
        assert "listing" in content

        # make sure audio_urls.audio is included in results
        assert audio_urls.audio.title in content

    def test_get_index_with_search(self, admin_client, audio_urls):
        r = admin_client.get(audio_urls.index, {"q": audio_urls.audio.title})

        assert r.status_code == 200
        content = r.content.decode("utf-8")

        # make sure it's the media results page
        assert "html" in content
        assert "media-results" in content

        # make sure audio_urls.audio is included in results
        assert audio_urls.audio.title in content

    def test_get_index_with_search_invalid(self, admin_client, audio_urls):
        r = admin_client.get(audio_urls.index, {"q": " "})

        assert r.status_code == 200
        content = r.content.decode("utf-8")

        # make sure it's the media results page
        assert "html" in content
        assert "media-results" in content

        # make sure audio_urls.audio is included in results
        assert audio_urls.audio.title in content

    def test_get_index_with_empty_normalized_search(self, admin_client, audio_urls):
        r = admin_client.get(audio_urls.index, {"q": "---\x00"})

        assert r.status_code == 200
        assert r.context["query_string"] is None
        assert r.context["is_searching"] is False
        assert audio_urls.audio in r.context["audios"]

    def test_get_index_with_pagination(self, admin_client, user):
        audio_models = []
        for i in range(1, 3):
            audio = Audio(user=user, title=f"audio {i}")
            audio.save()
            audio_models.append(audio)
        index_url = reverse("castaudio:index")
        with patch("cast.views.media.MENU_ITEM_PAGINATION", return_value=1):
            r = admin_client.get(index_url, {"p": "1"})
        audios = r.context["audios"]

        # make sure we got last audio from first page
        assert len(audios) == 1
        assert audios[0] == audio_models[-1]

        with patch("cast.views.media.MENU_ITEM_PAGINATION", return_value=1):
            r = admin_client.get(index_url, {"p": "2"})
        audios = r.context["audios"]

        # make sure we got first audio from last page
        assert len(audios) == 1
        assert audios[0] == audio_models[0]


class TestAudioAdd:
    pytestmark = pytest.mark.django_db

    def test_get_add_audio_scopes_collections_for_restricted_user(self, client):
        user = get_user_model().objects.create_user(
            username="limited-audio-admin",
            password="password",
            is_staff=True,
        )
        group = Group.objects.create(name="Limited audio admins")
        group.permissions.add(Permission.objects.get(codename="access_admin", content_type__app_label="wagtailadmin"))

        root = Collection.get_first_root_node()
        assert root is not None
        permitted = root.add_child(instance=Collection(name="Permitted Audio"))
        root.add_child(instance=Collection(name="Forbidden Audio"))
        add_audio_permission = Permission.objects.get(codename="add_audio", content_type__app_label="cast")
        GroupCollectionPermission.objects.create(group=group, collection=permitted, permission=add_audio_permission)

        group.user_set.add(user)
        assert client.login(username="limited-audio-admin", password="password")

        response = client.get(reverse("castaudio:add"))

        assert response.status_code == 200
        form = response.context["form"]
        assert "collection" not in form.fields
        assert list(form.collections.values_list("id", flat=True)) == [permitted.id]

    def test_get_add_audio(self, admin_client, audio_urls):
        r = admin_client.get(audio_urls.add)

        assert r.status_code == 200
        content = r.content.decode("utf-8")
        assert "Uploading…" in content

    def test_post_add_audio_invalid_form(self, admin_client):
        add_url = reverse("castaudio:add")

        post_data = {
            "title": "foobar",
            "m4a": invalid_m4a_upload(),
            "tags": "foo,bar,baz",
        }
        r = admin_client.post(add_url, post_data)

        # make sure we don't get redirected to index
        assert r.status_code == 200
        assert r.context["message"] == "The audio file could not be saved due to errors."

        # make sure we didn't create an audio
        assert Audio.objects.first() is None

    def test_post_add_audio_refuses_concurrent_upload(self, admin_client, admin_user, m4a_audio):
        key = f"cast:editor-media-upload:{admin_user.pk}"
        cache.set(key, "other", timeout=60)
        try:
            response = admin_client.post(
                reverse("castaudio:add"),
                {"title": "Locked audio", "m4a": m4a_audio},
            )
        finally:
            cache.delete(key)

        assert response.status_code == 200
        assert response.context["form"].non_field_errors() == ["Another audio or video upload is already in progress."]
        assert not Audio.objects.filter(title="Locked audio").exists()

    @pytest.mark.parametrize(
        ("probe_result", "message"),
        [
            (subprocess.TimeoutExpired(cmd="ffprobe", timeout=1), "Audio probing exceeded the upload budget."),
            (subprocess.CompletedProcess([], 0, stdout=b"N/A\n"), "Audio probing failed."),
        ],
    )
    def test_post_add_audio_maps_probe_failure_and_cleans_up(
        self, admin_client, admin_user, m4a_audio, mocker, probe_result, message
    ):
        if isinstance(probe_result, Exception):
            mocker.patch("cast.models.audio.run_media_probe", side_effect=probe_result)
        else:
            mocker.patch("cast.models.audio.run_media_probe", return_value=probe_result)
        storage = Audio._meta.get_field("m4a").storage
        delete = mocker.spy(storage, "delete")

        response = admin_client.post(
            reverse("castaudio:add"),
            {"title": "Failed probe", "m4a": m4a_audio},
        )

        assert response.status_code == 200
        assert response.context["form"].non_field_errors() == [message]
        assert Audio.objects.count() == 0
        deleted_name = delete.call_args.args[0]
        assert not storage.exists(deleted_name)
        assert cache.get(f"cast:editor-media-upload:{admin_user.pk}") is None

    def test_post_add_audio(self, admin_client, minimal_mp4):
        add_url = reverse("castaudio:add")

        post_data = {
            "title": "foobar",
            "tags": "foo,bar,baz",
            "original": minimal_mp4,
        }
        r = admin_client.post(add_url, post_data)

        # make sure we get redirected to index
        assert r.status_code == 302
        assert r.url == reverse("castaudio:index")

        # make sure field were saved correctly
        audio = Audio.objects.first()
        assert audio.title == post_data["title"]

        actual_tags = {t.name for t in audio.tags.all()}
        expected_tags = set(post_data["tags"].split(","))
        assert actual_tags == expected_tags


class TestAudioEdit:
    pytestmark = pytest.mark.django_db

    def test_get_edit_audio(self, admin_client, audio_urls):
        r = admin_client.get(audio_urls.edit)

        assert r.status_code == 200
        content = r.content.decode("utf-8")
        assert "Delete" in content

    def test_get_edit_audio_without_m4a(self, admin_client, audio_without_m4a):
        audio = audio_without_m4a
        edit_url = reverse("castaudio:edit", args=(audio.id,))
        r = admin_client.get(edit_url)

        assert r.status_code == 200
        content = r.content.decode("utf-8")
        assert "Delete" in content

    def test_get_edit_audio_without_m4a_no_filesize(self, settings, admin_client, audio_without_m4a):
        settings.DEFAULT_FILE_STORAGE = "django.core.files.storage.FileSystemStorage"
        audio = audio_without_m4a

        # set the name to make bool(audio.m4a) True and save it (yes, this is needed)
        audio.m4a.name = "foobar"
        audio.save()

        edit_url = reverse("castaudio:edit", args=(audio.id,))
        r = admin_client.get(edit_url)

        assert r.status_code == 200
        content = r.content.decode("utf-8")
        assert "Delete" in content

    def test_post_edit_audio_invalid_form(self, admin_client, audio_urls):
        post_data = {"m4a": invalid_m4a_upload()}
        r = admin_client.post(audio_urls.edit, post_data)

        # make sure we don't get redirected to index
        assert r.status_code == 200

    def test_post_edit_audio_refuses_concurrent_upload(self, admin_client, admin_user, audio_urls, m4a_audio):
        old_name = audio_urls.audio.m4a.name
        key = f"cast:editor-media-upload:{admin_user.pk}"
        cache.set(key, "other", timeout=60)
        try:
            response = admin_client.post(audio_urls.edit, {"m4a": m4a_audio})
        finally:
            cache.delete(key)

        assert response.status_code == 200
        assert response.context["form"].non_field_errors() == ["Another audio or video upload is already in progress."]
        audio_urls.audio.refresh_from_db()
        assert audio_urls.audio.m4a.name == old_name

    def test_post_edit_audio_title(self, admin_client, audio_urls, django_capture_on_commit_callbacks):
        audio = audio_urls.audio
        old_name = audio.m4a.name
        post_data = {
            "title": "changed title",
        }
        with django_capture_on_commit_callbacks(execute=False) as callbacks:
            r = admin_client.post(audio_urls.edit, post_data)

        # make sure we get redirected to index
        assert r.status_code == 302
        assert r.url == audio_urls.index

        # make sure title was changes
        audio.refresh_from_db()
        assert audio.title == post_data["title"]
        assert audio.m4a.name == old_name
        assert callbacks == []

    def test_post_edit_audio_m4a(self, admin_client, audio_urls, m4a_audio, django_capture_on_commit_callbacks):
        old_name = audio_urls.audio.m4a.name
        storage = audio_urls.audio.m4a.storage
        m4a_audio.seek(0)  # don't know why this is necessary :/
        post_data = {"m4a": m4a_audio}
        with django_capture_on_commit_callbacks(execute=False) as callbacks:
            r = admin_client.post(audio_urls.edit, post_data)

        # make sure we get redirected to index
        assert r.status_code == 302
        assert r.url == audio_urls.index

        audio_urls.audio.refresh_from_db()
        new_name = audio_urls.audio.m4a.name
        assert new_name != old_name
        assert storage.exists(old_name) and storage.exists(new_name)

        assert len(callbacks) == 1
        callbacks[0]()
        assert not storage.exists(old_name)
        assert storage.exists(new_name)

        audio_urls.audio.m4a.delete()

    def test_post_edit_audio_mp3_deletes_only_replaced_format_after_commit(
        self, admin_client, audio_urls, django_capture_on_commit_callbacks, mocker
    ):
        audio = audio_urls.audio
        m4a_name = audio.m4a.name
        audio.mp3.save("old.mp3", minimal_mp3_upload("old.mp3"))
        old_mp3_name = audio.mp3.name
        storage = audio.mp3.storage

        def probe(command, **kwargs):
            stdout = b'{"chapters": []}' if "-show_chapters" in command else b"1.000000\n"
            return subprocess.CompletedProcess(command, 0, stdout=stdout)

        mocker.patch("cast.models.audio.run_media_probe", side_effect=probe)

        with django_capture_on_commit_callbacks(execute=False) as callbacks:
            response = admin_client.post(audio_urls.edit, {"mp3": minimal_mp3_upload()})

        assert response.status_code == 302
        audio.refresh_from_db()
        new_mp3_name = audio.mp3.name
        assert new_mp3_name != old_mp3_name
        assert audio.m4a.name == m4a_name
        assert all(storage.exists(name) for name in (old_mp3_name, new_mp3_name, m4a_name))

        assert len(callbacks) == 1
        callbacks[0]()
        assert not storage.exists(old_mp3_name)
        assert storage.exists(new_mp3_name) and storage.exists(m4a_name)
        audio.mp3.delete(save=False)

    def test_post_edit_audio_probe_failure_keeps_old_file_and_name(self, admin_client, audio_urls, m4a_audio, mocker):
        audio = audio_urls.audio
        old_name = audio.m4a.name
        storage = audio.m4a.storage
        delete = mocker.spy(storage, "delete")
        mocker.patch(
            "cast.models.audio.run_media_probe",
            return_value=subprocess.CompletedProcess([], 0, stdout=b"N/A\n"),
        )
        m4a_audio.seek(0)

        response = admin_client.post(audio_urls.edit, {"m4a": m4a_audio})

        assert response.status_code == 200
        assert response.context["form"].non_field_errors() == ["Audio probing failed."]
        audio.refresh_from_db()
        assert audio.m4a.name == old_name
        assert response.context["form"].instance.m4a.name == old_name
        assert storage.exists(old_name)
        deleted_names = [call.args[0] for call in delete.call_args_list]
        assert deleted_names and old_name not in deleted_names
        assert all(not storage.exists(name) for name in deleted_names)

    def test_post_edit_audio_m4a_reprobes_duration(self, admin_client, audio_urls, m4a_audio, fixture_dir):
        """Replacing an audio file has to replace the duration probed from the old file."""
        audio = audio_urls.audio
        stale_duration = timedelta(hours=3)
        Audio.objects.filter(pk=audio.pk).update(duration=stale_duration)
        m4a_audio.seek(0)

        r = admin_client.post(audio_urls.edit, {"m4a": m4a_audio})

        assert r.status_code == 302
        audio.refresh_from_db()
        assert audio.duration == Audio._get_audio_duration(Path(fixture_dir) / "test.m4a")
        assert audio.duration != stale_duration

        # teardown
        audio.m4a.delete()

    def test_post_edit_audio_without_file_change_keeps_duration(self, admin_client, audio_urls):
        """An edit that does not touch an audio file must not discard the stored duration."""
        audio = audio_urls.audio
        duration = timedelta(seconds=61, microseconds=234000)
        Audio.objects.filter(pk=audio.pk).update(duration=duration)

        r = admin_client.post(audio_urls.edit, {"title": "changed title"})

        assert r.status_code == 302
        audio.refresh_from_db()
        assert audio.duration == duration


class TestAudioDelete:
    pytestmark = pytest.mark.django_db

    def test_get_delete_audio(self, admin_client, audio_urls):
        r = admin_client.get(audio_urls.delete)

        assert r.status_code == 200
        content = r.content.decode("utf-8")
        assert "Are you sure you want to delete this audio?" in content

    def test_post_delete_audio(self, admin_client, audio_urls):
        audio = audio_urls.audio
        # post data is necessary because of if request.POST
        r = admin_client.post(audio_urls.delete, {"delete": "yes"})

        # make sure we get redirected to index
        assert r.status_code == 302
        assert r.url == audio_urls.index

        # make sure audio was deleted
        with pytest.raises(Audio.DoesNotExist):
            audio.refresh_from_db()


class TestAudioChosen:
    pytestmark = pytest.mark.django_db

    def test_get_chosen_audio_not_found(self, admin_client, audio_urls):
        audio = audio_urls.audio
        audio.delete()
        r = admin_client.get(audio_urls.chosen)

        assert r.status_code == 404

    def test_get_chosen_audio_success(self, admin_client, audio_urls):
        audio = audio_urls.audio
        r = admin_client.get(audio_urls.chosen)

        assert r.status_code == 200

        # make sure returned data belongs to the right audio instance
        data = r.json()
        assert data["result"]["title"] == audio.title


class TestAudioChooser:
    pytestmark = pytest.mark.django_db

    def test_get_audio_in_chooser(self, admin_client, audio_urls):
        audio = audio_urls.audio
        r = admin_client.get(audio_urls.chooser)

        assert r.status_code == 200

        # make sure existing audio is in chooser
        content = r.content.decode("utf-8")
        assert audio.title in content

        # make sure prefix for form fields is set
        assert "media-chooser-upload" in content

    def test_get_chooser_with_search(self, admin_client, audio_urls):
        r = admin_client.get(audio_urls.chooser, {"q": audio_urls.audio.title})

        assert r.status_code == 200

        # make sure searched audio is included in results
        assert r.context["audios"][0] == audio_urls.audio

    def test_get_chooser_with_search_invalid(self, admin_client, audio_urls):
        # {"p": "1"} (page 1) leads to the search form being invalid
        r = admin_client.get(audio_urls.chooser, {"p": "1"})

        assert r.status_code == 200

        # make sure searched audios is included in results
        assert r.context["audios"][0] == audio_urls.audio

    def test_get_chooser_with_empty_normalized_search(self, admin_client, audio_urls):
        r = admin_client.get(audio_urls.chooser, {"q": "---\x00"})

        assert r.status_code == 200
        assert r.context["query_string"] is None
        assert r.context["is_searching"] is False
        assert r.context["audios"][0] == audio_urls.audio

    def test_get_chooser_with_pagination(self, admin_client, user):
        audio_models = []
        for i in range(1, 3):
            audio = Audio(user=user, title=f"audio {i}")
            audio.save()
            audio_models.append(audio)
        chooser_url = reverse("castaudio:chooser")
        with patch("cast.views.media.CHOOSER_PAGINATION", return_value=1):
            r = admin_client.get(chooser_url, {"p": "1"})
        audios = r.context["audios"]

        # make sure we got last audio from first page
        assert len(audios) == 1
        assert audios[0] == audio_models[-1]

        with patch("cast.views.media.CHOOSER_PAGINATION", return_value=1):
            r = admin_client.get(chooser_url, {"p": "2"})
        audios = r.context["audios"]

        # make sure we got first audio from last page
        assert len(audios) == 1
        assert audios[0] == audio_models[0]


class TestAudioChooserUpload:
    pytestmark = pytest.mark.django_db

    def test_get_audio_in_chooser_upload(self, admin_client, audio_urls):
        audio = audio_urls.audio
        r = admin_client.get(audio_urls.chooser_upload)

        assert r.status_code == 200
        content = r.content.decode("utf-8")
        assert audio.title in content

    def test_post_upload_audio_form_invalid(self, admin_client):
        upload_url = reverse("castaudio:chooser_upload")
        post_data = {"media-chooser-upload-m4a": invalid_m4a_upload()}
        r = admin_client.post(upload_url, post_data)

        assert r.status_code == 200
        assert r.context["message"] == "The audio could not be saved due to errors."

    def test_post_upload_audio_refuses_concurrent_upload(self, admin_client, admin_user, m4a_audio):
        key = f"cast:editor-media-upload:{admin_user.pk}"
        cache.set(key, "other", timeout=60)
        try:
            response = admin_client.post(
                reverse("castaudio:chooser_upload"),
                {
                    "media-chooser-upload-title": "Locked chooser audio",
                    "media-chooser-upload-m4a": m4a_audio,
                },
            )
        finally:
            cache.delete(key)

        assert response.status_code == 200
        assert response.context["uploadform"].non_field_errors() == [
            "Another audio or video upload is already in progress."
        ]
        assert not Audio.objects.filter(title="Locked chooser audio").exists()

    def test_post_upload_audio(self, admin_client, m4a_audio, settings):
        settings.DEFAULT_FILE_STORAGE = "django.core.files.storage.FileSystemStorage"
        upload_url = reverse("castaudio:chooser_upload")
        prefix = "media-chooser-upload"
        post_data = {
            f"{prefix}-title": "foobar",
            f"{prefix}-tags": "foo,bar,baz",
            f"{prefix}-m4a": m4a_audio,
        }
        r = admin_client.post(upload_url, post_data)

        assert r.status_code == 200

        # make sure field were saved correctly
        audio = Audio.objects.first()
        assert audio.title == post_data[f"{prefix}-title"]

        actual_tags = {t.name for t in audio.tags.all()}
        expected_tags = set(post_data[f"{prefix}-tags"].split(","))
        assert actual_tags == expected_tags

        # teardown
        audio.m4a.delete()
