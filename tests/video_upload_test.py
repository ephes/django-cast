import pytest
from django.core.cache import cache
from django.contrib.auth.models import Permission
from django.urls import reverse
from wagtail.models import Collection

from cast import media_probe
from cast.api.editor.media import LegacyVideoCreateView
from cast.models import Video


class TestVideoUpload:
    def test_legacy_upload_tolerates_custom_form_without_title(self, mocker):
        form = mocker.Mock(fields={})
        form_class = mocker.Mock(return_value=form)
        request = mocker.Mock(FILES={}, user=mocker.Mock())

        result = LegacyVideoCreateView()._video_form(form_class, {}, request, mocker.Mock())

        assert result is form

        title = mocker.Mock(required=True)
        form = mocker.Mock(fields={"title": title})
        form_class.return_value = form
        LegacyVideoCreateView()._video_form(form_class, {}, request, mocker.Mock())
        assert title.required is False

    @pytest.mark.django_db
    def test_upload_video_not_authenticated(self, client, minimal_mp4):
        upload_url = reverse("cast:api:upload_video")

        minimal_mp4.seek(0)
        r = client.post(upload_url, {"original": minimal_mp4})
        assert r.status_code == 403

    @pytest.mark.django_db
    def test_upload_video_authenticated(self, client, admin_user, minimal_mp4):
        assert not admin_user.is_superuser
        # login
        r = client.login(username=admin_user.username, password=admin_user._password)

        self.called_create_poster = False

        def set_called_create_poster():
            self.called_create_poster = True

        # mock create poster?
        # Video._saved_create_poster = Video._create_poster
        # Video._create_poster = lambda x: set_called_create_poster()

        # upload
        upload_url = reverse("cast:api:upload_video")
        minimal_mp4.seek(0)
        r = client.post(upload_url, {"original": minimal_mp4})

        # unmock
        # Video._create_poster = Video._saved_create_poster

        assert r.status_code == 201, r.json()
        assert int(r.content.decode("utf-8")) > 0

        # check mocked function has been called - no longer necessary since we use
        # a real mp4 now.
        # assert self.called_create_poster

    @pytest.mark.django_db
    def test_upload_video_denies_user_without_wagtail_access_before_storage(self, client, user, minimal_mp4, mocker):
        client.login(username=user.username, password=user._password)
        storage_save = mocker.spy(Video._meta.get_field("original").storage, "save")
        probe = mocker.spy(media_probe, "run_media_probe")

        r = client.post(reverse("cast:api:upload_video"), {"original": minimal_mp4})

        assert r.status_code == 403
        storage_save.assert_not_called()
        probe.assert_not_called()
        assert not Video.objects.filter(user=user).exists()

    @pytest.mark.django_db
    def test_upload_video_denies_admin_without_collection_add_permission(self, client, user, minimal_mp4, mocker):
        user.user_permissions.add(
            Permission.objects.get(codename="access_admin", content_type__app_label="wagtailadmin")
        )
        assert user.has_perm("wagtailadmin.access_admin")
        client.login(username=user.username, password=user._password)
        storage_save = mocker.spy(Video._meta.get_field("original").storage, "save")
        probe = mocker.spy(media_probe, "run_media_probe")

        r = client.post(reverse("cast:api:upload_video"), {"original": minimal_mp4})

        assert r.status_code == 403
        assert r.json()["code"] == "no_upload_collection"
        storage_save.assert_not_called()
        probe.assert_not_called()
        assert not Video.objects.filter(user=user).exists()

    @pytest.mark.django_db
    def test_upload_video_shares_editor_upload_lock(self, client, admin_user, minimal_mp4):
        client.login(username=admin_user.username, password=admin_user._password)
        key = f"cast:editor-media-upload:{admin_user.pk}"
        cache.set(key, "other", timeout=60)

        try:
            r = client.post(reverse("cast:api:upload_video"), {"original": minimal_mp4})
        finally:
            cache.delete(key)

        assert r.status_code == 429
        assert r.json()["code"] == "rate_limited"

    @pytest.mark.django_db
    def test_upload_video_requires_collection_when_multiple_are_available(self, client, admin_user, minimal_mp4):
        client.login(username=admin_user.username, password=admin_user._password)
        Collection.get_first_root_node().add_child(instance=Collection(name="Other"))

        r = client.post(reverse("cast:api:upload_video"), {"original": minimal_mp4})

        assert r.status_code == 400
        assert r.json()["errors"]["collection"][0]["code"] == "ambiguous"

    @pytest.mark.django_db
    def test_upload_video_accepts_explicit_authorized_collection(self, client, admin_user, minimal_mp4):
        client.login(username=admin_user.username, password=admin_user._password)
        root = Collection.get_first_root_node()
        child = root.add_child(instance=Collection(name="Selected"))

        r = client.post(reverse("cast:api:upload_video"), {"original": minimal_mp4, "collection": child.pk})

        assert r.status_code == 201
        assert Video.objects.get(pk=int(r.content)).collection == child

    @pytest.mark.django_db
    @pytest.mark.parametrize("scope", ["", "delete", ["write"]])
    def test_upload_video_rejects_empty_wrong_or_malformed_scope(
        self, api_client, admin_user, minimal_mp4, scope, mocker
    ):
        token = type("Token", (), {"scope": scope})()
        api_client.force_authenticate(user=admin_user, token=token)
        storage_save = mocker.spy(Video._meta.get_field("original").storage, "save")
        probe = mocker.spy(media_probe, "run_media_probe")

        r = api_client.post(reverse("cast:api:upload_video"), {"original": minimal_mp4}, format="multipart")

        assert r.status_code == 403
        storage_save.assert_not_called()
        probe.assert_not_called()

    @pytest.mark.django_db
    def test_upload_video_accepts_write_scope(self, api_client, admin_user, minimal_mp4):
        token = type("Token", (), {"scope": "write"})()
        api_client.force_authenticate(user=admin_user, token=token)

        r = api_client.post(reverse("cast:api:upload_video"), {"original": minimal_mp4}, format="multipart")

        assert r.status_code == 201
        assert int(r.content) > 0
