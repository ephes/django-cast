import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, nullcontext
from types import SimpleNamespace

import pytest
from django.contrib.auth.models import Group, Permission
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.core.files.storage import InMemoryStorage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, connection, connections, transaction
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework.response import Response
from taggit.models import Tag
from wagtail.models import Collection, GroupCollectionPermission, GroupPagePermission, Page

from cast import media_ingest, media_probe
from cast.api.editor import media as editor_media
from cast.api.editor.errors import (
    EditorValidationError,
)
from cast.models import Audio, Video
from tests.factories import UserFactory


@pytest.mark.parametrize("value", [1, "1", 123, "123"])
def test_collection_id_accepts_exact_positive_integers(value):
    assert editor_media._parse_collection_id(value) == int(value)


@pytest.mark.parametrize(
    "value",
    [
        1.9,
        1.0,
        float("inf"),
        float("-inf"),
        float("nan"),
        True,
        False,
        None,
        [],
        {},
        0,
        -1,
        "",
        "01",
        "+1",
        " 1",
        "1 ",
        "1.0",
        "1e0",
        "١",
        "1_0",
    ],
)
def test_collection_id_rejects_noncanonical_values(value):
    with pytest.raises(EditorValidationError) as exc:
        editor_media._parse_collection_id(value)
    assert exc.value.error_map["collection"][0]["code"] == "invalid"


@pytest.mark.django_db
@pytest.mark.parametrize("value", [1.9, True, None, []])
def test_collection_resolution_rejects_malformed_values_before_lookup(value, mocker):
    usable = Collection.objects.all()
    lookup = mocker.patch.object(usable, "filter")
    with pytest.raises(EditorValidationError):
        editor_media._resolve_collection(SimpleNamespace(data={"collection": value}), usable)
    lookup.assert_not_called()


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


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("use_snapshot", [True, False])
def test_collection_breadcrumbs_survive_move_after_page_read(api_client, monkeypatch, use_snapshot):
    if not use_snapshot:
        monkeypatch.setattr(editor_media, "_collection_read_snapshot", lambda using: nullcontext(False))
    elif connection.vendor != "postgresql":
        # Only PostgreSQL takes the snapshot in production; a WAL read
        # transaction exercises the same view branch on SQLite.
        @contextmanager
        def wal_snapshot(using):
            with transaction.atomic(using=using):
                yield True

        monkeypatch.setattr(editor_media, "_collection_read_snapshot", wal_snapshot)

    root = Collection.get_first_root_node() or Collection.add_root(name="Synthetic root")
    destination = root.add_child(name="Destination")
    source = root.add_child(name="Source")
    parent = source.add_child(name="Moved parent")
    child = parent.add_child(name="Selected child")
    assert child.get_parent().get_parent().pk == source.pk
    permitted = Collection.objects.filter(pk=child.pk)
    monkeypatch.setattr(editor_media, "_usable_image_collections", lambda user: permitted)
    api_client.force_authenticate(user=UserFactory(is_staff=True, is_superuser=True))

    def move_parent():
        try:
            Collection.objects.get(pk=parent.pk).move(Collection.objects.get(pk=destination.pk), pos="sorted-child")
        finally:
            connections.close_all()

    paginator = editor_media.EditorMediaCollectionsView.pagination_class
    paginate = paginator.paginate_queryset
    moved = False

    def paginate_before_move(self, *args, **kwargs):
        nonlocal moved
        page = paginate(self, *args, **kwargs)
        if not moved:
            with ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(move_parent).result(timeout=10)
            moved = True
        return page

    monkeypatch.setattr(paginator, "paginate_queryset", paginate_before_move)
    original_mode = None
    if connection.vendor == "sqlite":
        with connection.cursor() as cursor:
            cursor.execute("PRAGMA journal_mode")
            original_mode = cursor.fetchone()[0]
            cursor.execute("PRAGMA journal_mode=WAL")
    try:
        url = reverse("cast:api:editor_media_collections")
        for branch in (source, destination):
            response = api_client.get(url, {"type": "image", "pageSize": 1})
            assert response.status_code == 200, response.content
            assert moved
            assert response.json() == {
                "count": 1,
                "next": None,
                "previous": None,
                "results": [
                    {
                        "id": child.pk,
                        "name": child.name,
                        "breadcrumb": " / ".join(node.name for node in (root, branch, parent, child)),
                        "ancestors": [{"id": node.pk, "name": node.name} for node in (root, branch, parent)],
                    }
                ],
            }
    finally:
        if original_mode is not None:
            with connection.cursor() as cursor:
                cursor.execute(f"PRAGMA journal_mode={original_mode}")


@pytest.mark.django_db
def test_collection_read_snapshot_opens_no_sqlite_transaction(mocker):
    db = mocker.MagicMock(vendor="sqlite")
    mocker.patch.object(editor_media, "connections", {"default": db})
    atomic = mocker.patch.object(editor_media.transaction, "atomic")
    with editor_media._collection_read_snapshot("default") as has_snapshot:
        assert has_snapshot is False
    atomic.assert_not_called()
    db.cursor.assert_not_called()


@pytest.mark.django_db
@pytest.mark.parametrize("autocommit", [True, False])
def test_collection_read_snapshot_only_sets_postgres_isolation_when_it_owns_transaction(mocker, autocommit):
    db = mocker.MagicMock(vendor="postgresql")
    db.get_autocommit.return_value = autocommit
    mocker.patch.object(editor_media, "connections", {"default": db})
    with editor_media._collection_read_snapshot("default") as has_snapshot:
        assert has_snapshot is autocommit
    if autocommit:
        db.cursor.return_value.__enter__.return_value.execute.assert_called_once_with(
            "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
        )
    else:
        db.cursor.assert_not_called()


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

    def test_media_list_falls_back_for_unparseable_storage_url(self, api_client, superuser, monkeypatch):
        class LegacyStorage(InMemoryStorage):
            def url(self, name):
                if name == "legacy.mp3":
                    return "https://[storage.example.test/legacy.mp3"
                return f"https://storage.example.test/media/{name}?token=synthetic#start"

        monkeypatch.setattr(Audio._meta.get_field("mp3"), "storage", LegacyStorage())
        legacy = Audio.objects.create(user=superuser, title="Legacy file", mp3="legacy.mp3")
        current = Audio.objects.create(user=superuser, title="Current file", mp3="current.mp3")
        api_client.force_authenticate(user=superuser)

        response = api_client.get(reverse("cast:api:editor_media_audios"))

        assert response.status_code == 200, response.content
        assert [(item["id"], item["mp3"]) for item in response.json()["results"]] == [
            (current.pk, "/media/current.mp3?token=synthetic#start"),
            (legacy.pk, None),
        ]

    def test_repeated_media_tags_reuse_count_joins_and_preserve_and_ordering(self, api_client, superuser):
        oldest = Audio.objects.create(user=superuser, title="First match")
        newest = Audio.objects.create(user=superuser, title="Second match")
        single = Audio.objects.create(user=superuser, title="One tag only")
        oldest.tags.add("weeknotes", "desk")
        newest.tags.add("weeknotes", "desk")
        single.tags.add("weeknotes")
        api_client.force_authenticate(user=superuser)
        url = reverse("cast:api:editor_media_audios")

        def fetch(tags):
            with CaptureQueriesContext(connection) as queries:
                response = api_client.get(url, {"tag": tags})
            assert response.status_code == 200, response.content
            data = response.json()
            assert data["count"] == 2
            assert [item["id"] for item in data["results"]] == [newest.pk, oldest.pk]
            return [query["sql"] for query in queries if "COUNT(" in query["sql"] and "cast_audio" in query["sql"]]

        baseline = fetch(["weeknotes", "desk"])
        assert len(baseline) == 1
        assert fetch(["weeknotes"] * 26 + ["desk", "weeknotes"]) == baseline

    def test_media_list_rejects_too_many_distinct_tags_before_counting(self, api_client, superuser):
        api_client.force_authenticate(user=superuser)
        url = reverse("cast:api:editor_media_audios")
        tags = [f"synthetic-{index}" for index in range(21)]
        at_limit = api_client.get(url, {"tag": tags[:-1]})
        assert at_limit.status_code == 200, at_limit.content

        with CaptureQueriesContext(connection) as queries:
            response = api_client.get(url, {"tag": tags})
        assert response.status_code == 400, response.content
        assert response.json()["errors"]["tag"][0]["code"] == "too_many"
        assert not any("cast_audio" in query["sql"] for query in queries)

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

    @pytest.mark.parametrize("value", ["01", "+1", " 1", "1.0", "", "1_0"])
    def test_image_upload_rejects_noncanonical_collection_without_writes(
        self, api_client, superuser, image_1px, value
    ):
        image_model = editor_media.get_image_model()
        count = image_model.objects.count()
        api_client.force_authenticate(user=superuser)
        response = api_client.post(
            reverse("cast:api:editor_media_images"),
            {"title": "Invalid collection", "file": image_1px, "collection": value},
            format="multipart",
        )
        assert response.status_code == 400
        assert response.json()["errors"]["collection"][0]["code"] == "invalid"
        assert image_model.objects.count() == count

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

    def test_audio_upload_uses_probe_budget_and_accepts_enabled_diarization(
        self, api_client, superuser, m4a_audio, mp3_audio, mocker
    ):
        run_probe = mocker.patch(
            "cast.models.audio.run_media_probe",
            side_effect=[
                subprocess.CompletedProcess([], 0, stdout=b"1.000000\n"),
                subprocess.CompletedProcess([], 0, stdout=b'{"chapters": []}'),
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
        assert data["transcript_diarization_mode"] == "inherit"
        audio = Audio.objects.get(pk=data["id"])
        assert re.fullmatch(r"cast_audio/.+-[0-9a-f]{12}\.m4a", audio.m4a.name)
        assert run_probe.call_count == 2

        # Simulate expiry before testing another independent upload outcome.
        cache.delete(f"cast:editor-media-upload:{superuser.pk}")
        enabled = api_client.post(
            url,
            {
                "title": "Diarization",
                "transcript_diarization_mode": Audio.TranscriptDiarizationMode.ENABLED,
                "mp3": mp3_audio,
            },
            format="multipart",
        )
        assert enabled.status_code == 201, enabled.content
        assert enabled.json()["transcript_diarization_mode"] == "enabled"
        assert Audio.objects.get(pk=enabled.json()["id"]).transcript_diarization_mode == "enabled"

    def test_audio_upload_validates_diarization_mode_before_requiring_a_file(self, api_client, superuser):
        api_client.force_authenticate(user=superuser)
        url = reverse("cast:api:editor_media_audios")
        audio_count = Audio.objects.count()

        # The documented feature probe: a supported mode is never reported at its field path.
        probe = api_client.post(url, {"transcript_diarization_mode": "enabled"}, format="multipart")
        assert probe.status_code == 400
        assert "transcript_diarization_mode" not in probe.json()["errors"]
        assert probe.json()["errors"]["non_field_errors"][0]["code"] == "required"

        # Simulate expiry before testing another independent upload outcome.
        cache.delete(f"cast:editor-media-upload:{superuser.pk}")
        invalid = api_client.post(url, {"transcript_diarization_mode": "sometimes"}, format="multipart")
        assert invalid.status_code == 400
        assert invalid.json()["errors"]["transcript_diarization_mode"][0]["code"] == "invalid_choice"
        assert Audio.objects.count() == audio_count

    def test_audio_upload_rejects_multiple_files_and_form_errors(self, api_client, superuser, m4a_audio, mp3_audio):
        api_client.force_authenticate(user=superuser)
        url = reverse("cast:api:editor_media_audios")

        missing = api_client.post(url, {"title": "Missing audio"}, format="multipart")
        assert missing.status_code == 400
        assert missing.json()["errors"]["non_field_errors"][0]["code"] == "required"

        # Simulate expiry before testing another independent upload outcome.
        cache.delete(f"cast:editor-media-upload:{superuser.pk}")
        too_many = api_client.post(url, {"m4a": m4a_audio, "mp3": mp3_audio}, format="multipart")
        assert too_many.status_code == 400
        assert too_many.json()["errors"]["non_field_errors"][0]["code"] == "too_many_files"

        invalid_upload = SimpleUploadedFile("bad.txt", b"ID3-not-really-enough", content_type="audio/mpeg")
        # Simulate expiry before testing another independent upload outcome.
        cache.delete(f"cast:editor-media-upload:{superuser.pk}")
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
        # Simulate expiry before testing another independent upload outcome.
        cache.delete(f"cast:editor-media-upload:{superuser.pk}")
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
        mocker.patch("cast.media_ingest.cleanup_new_media_object", return_value=False)
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
        budget = mocker.patch("cast.media_ingest.media_probe_budget", wraps=media_probe.media_probe_budget)
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
        mocker.patch("cast.media_ingest.cleanup_new_media_object", return_value=False)
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

    def test_upload_lock_does_not_translate_callback_contention(self, superuser):
        def callback():
            raise media_ingest.MediaUploadInProgress

        with pytest.raises(media_ingest.MediaUploadInProgress):
            editor_media._with_upload_lock(superuser, callback)

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
        video = Video.objects.get(id=data["id"])
        assert re.fullmatch(r"cast_videos/.+-[0-9a-f]{12}\.mp4", video.original.name)

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

    def test_video_ingest_cleanup_failure_uses_editor_error(self, api_client, superuser, minimal_mp4, mocker):
        mocker.patch(
            "cast.api.editor.media.ingest_upload",
            side_effect=media_ingest.MediaIngestCleanupFailed("cleanup failed"),
        )
        api_client.force_authenticate(user=superuser)

        response = api_client.post(
            reverse("cast:api:editor_media_videos"),
            {"title": "Failed cleanup", "original": minimal_mp4},
            format="multipart",
        )

        assert response.status_code == 500
        assert response.json() == {"code": "cleanup_failed", "detail": "Upload cleanup failed."}

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
        # Simulate expiry before testing another independent upload outcome.
        cache.delete(f"cast:editor-media-upload:{superuser.pk}")
        denied = api_client.post(url, {"title": "Denied video", "original": first_upload}, format="multipart")
        assert denied.status_code == 403
        assert denied.json()["code"] == "post_save_permission_denied"

        mocker.patch("cast.api.editor.media._cleanup_media_object", return_value=False)
        # Simulate expiry before testing another independent upload outcome.
        cache.delete(f"cast:editor-media-upload:{superuser.pk}")
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


@pytest.fixture(params=["test.png", "long" * 23 + ".png"])
def image_upload_storage(db, mocker, image_1px, request):
    """Overwrite-capable, in-memory storage with an unrelated existing image."""
    Collection.get_first_root_node() or Collection.add_root(instance=Collection(name="Synthetic root"))
    image_model = editor_media.get_image_model()
    storage = InMemoryStorage()
    mocker.patch.object(image_model._meta.get_field("file"), "storage", storage)
    mocker.patch.object(storage, "get_available_name", side_effect=lambda name, max_length=None: name)
    original_bytes = image_1px.read() + b"existing image bytes"
    image_1px.seek(0)
    image_1px.name = request.param
    old_name = image_model().get_upload_to(request.param)
    old_name = storage.save(old_name, ContentFile(original_bytes))
    existing = image_model.objects.create(
        title="Existing image", file=old_name, width=1, height=1, collection=Collection.get_first_root_node()
    )
    return storage, existing, original_bytes


@pytest.fixture
def image_insert_failure(mocker):
    """Inject after FileField pre_save, independently of Django's insert internals."""

    def install(failure):
        fault = mocker.Mock(side_effect=failure)
        table = connection.ops.quote_name(editor_media.get_image_model()._meta.db_table)

        def fail_insert(execute, sql, params, many, context):
            if sql.startswith(f"INSERT INTO {table} "):
                fault()
            return execute(sql, params, many, context)

        return connection.execute_wrapper(fail_insert), fault

    return install


@pytest.mark.django_db
@pytest.mark.parametrize("stage", ["insert", "m2m", "storage"])
def test_image_upload_save_failure_compensates_only_new_files(
    api_client, superuser, image_1px, image_upload_storage, image_insert_failure, mocker, stage
):
    storage, existing, original_bytes = image_upload_storage
    image_model = type(existing)
    failure = IntegrityError("synthetic registration failure")
    tag_count = Tag.objects.count()
    insert_context = nullcontext()
    if stage == "insert":
        insert_context, fault = image_insert_failure(failure)
    elif stage == "m2m":
        form_class = editor_media.get_image_form(image_model)
        save_m2m = form_class._save_m2m

        def fail_after_tags(form):
            save_m2m(form)
            assert form.instance.tags.filter(name="synthetic").exists()
            raise failure

        fault = mocker.patch.object(form_class, "_save_m2m", autospec=True, side_effect=fail_after_tags)
        mocker.patch.object(editor_media, "get_image_form", return_value=form_class)
    else:
        fault = mocker.patch.object(storage, "save", side_effect=failure)
    writes = mocker.spy(storage, "_save")
    deletes = mocker.spy(storage, "delete")
    api_client.force_authenticate(user=superuser)
    with insert_context, pytest.raises(IntegrityError) as exc:
        api_client.post(
            reverse("cast:api:editor_media_images"),
            {"title": "Failed upload", "file": image_1px, "tags": "synthetic"},
            format="multipart",
        )
    assert exc.value is failure
    fault.assert_called_once()
    assert writes.call_count == (0 if stage == "storage" else 1)
    if stage != "storage":
        new_name = writes.call_args.args[0]
        assert new_name != existing.file.name
        deletes.assert_any_call(new_name)
        assert not storage.exists(new_name)
    assert image_model.objects.count() == 1
    assert Tag.objects.count() == tag_count
    existing.refresh_from_db()
    assert existing.title == "Existing image"
    assert storage.open(existing.file.name).read() == original_bytes
    assert not existing.tags.exists()


@pytest.mark.django_db
def test_image_upload_cleanup_failure_preserves_cause_and_logs(
    api_client, superuser, image_1px, image_upload_storage, image_insert_failure, mocker, caplog
):
    storage, existing, original_bytes = image_upload_storage
    failure = IntegrityError("synthetic insert failure")
    insert_context, fault = image_insert_failure(failure)
    writes = mocker.spy(storage, "_save")
    mocker.patch.object(storage, "delete", side_effect=OSError("synthetic cleanup failure"))
    api_client.force_authenticate(user=superuser)
    ingest = mocker.spy(editor_media, "ingest_upload")
    with insert_context:
        response = api_client.post(
            reverse("cast:api:editor_media_images"),
            {"title": "Failed cleanup", "file": image_1px},
            format="multipart",
        )
    assert response.status_code == 500
    assert response.json() == {"code": "cleanup_failed", "detail": "Upload cleanup failed."}
    assert isinstance(ingest.spy_exception, media_ingest.MediaIngestCleanupFailed)
    assert ingest.spy_exception.__cause__ is failure
    fault.assert_called_once()
    assert writes.call_count == 1
    assert storage.exists(writes.call_args.args[0])
    assert storage.open(existing.file.name).read() == original_bytes
    assert type(existing).objects.count() == 1
    assert "Media ingest cleanup failed" in caplog.text


@pytest.mark.django_db
def test_image_upload_success_uses_fresh_name_and_saves_tags(api_client, superuser, image_1px, image_upload_storage):
    storage, existing, original_bytes = image_upload_storage
    api_client.force_authenticate(user=superuser)
    response = api_client.post(
        reverse("cast:api:editor_media_images"),
        {"title": "New image", "file": image_1px, "tags": "synthetic"},
        format="multipart",
    )
    assert response.status_code == 201, response.content
    data = response.json()
    uploaded = type(existing).objects.get(pk=data["id"])
    assert uploaded.uploaded_by_user == superuser
    assert uploaded.collection == existing.collection
    assert uploaded.file.name != existing.file.name
    assert storage.exists(uploaded.file.name)
    assert data["tags"] == ["synthetic"]
    assert data["width"] == data["height"] == 1
    assert storage.open(existing.file.name).read() == original_bytes


@pytest.mark.django_db
def test_upload_lease_blocks_retries_until_expiry(api_client, superuser, mocker, settings):
    import time

    settings.CAST_EDITOR_MEDIA_UPLOAD_LOCK_SECONDS = 5
    api_client.force_authenticate(user=superuser)
    url = reverse("cast:api:editor_media_audios")
    assert api_client.post(url, {}, format="multipart").status_code == 400
    assert api_client.post(url, {}, format="multipart").status_code == 429
    mocker.patch("django.core.cache.backends.base.time.time", return_value=time.time() + 6)
    assert api_client.post(url, {}, format="multipart").status_code == 400


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("revocation", ["choose", "add", "inactive", "deleted"])
def test_image_publication_rechecks_committed_authority(
    api_client, image_1px, image_upload_storage, monkeypatch, revocation
):
    from concurrent.futures import ThreadPoolExecutor

    from django.contrib.auth import get_user_model
    from django.db import close_old_connections

    storage, existing, original_bytes = image_upload_storage
    user = UserFactory(is_staff=True)
    grant_wagtail_admin_access(user)
    collection = Collection.get_first_root_node()
    for action in ("add", "choose"):
        grant_collection_permission(user, collection, app_label="wagtailimages", codename=f"{action}_image")
    original_ingest = editor_media.ingest_upload

    def revoke():
        close_old_connections()
        try:
            if revocation == "inactive":
                get_user_model().objects.filter(pk=user.pk).update(is_active=False)
            elif revocation == "deleted":
                get_user_model().objects.filter(pk=user.pk).delete()
            else:
                GroupCollectionPermission.objects.filter(
                    group__user=user, permission__codename=f"{revocation}_image"
                ).delete()
        finally:
            close_old_connections()

    def ingest_then_revoke(*args, **kwargs):
        image = original_ingest(*args, **kwargs)
        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(revoke).result(timeout=10)
        return image

    monkeypatch.setattr(editor_media, "ingest_upload", ingest_then_revoke)
    api_client.force_authenticate(user=user)
    response = api_client.post(
        reverse("cast:api:editor_media_images"),
        {"title": "Revoked", "file": image_1px, "collection": collection.pk},
        format="multipart",
    )
    assert response.status_code == 403, response.content
    assert response.json()["code"] == "post_save_permission_denied"
    assert not editor_media.get_image_model().objects.filter(title="Revoked").exists()
    assert storage.open(existing.file.name).read() == original_bytes
    assert storage.listdir("original_images")[1] == [existing.file.name.split("/")[-1]]


@pytest.mark.django_db
def test_image_permission_refusal_reports_cleanup_failure(
    api_client, superuser, image_1px, image_upload_storage, mocker
):
    storage, existing, original_bytes = image_upload_storage
    mocker.patch.object(
        editor_media, "_usable_image_collections", side_effect=[Collection.objects.all(), Collection.objects.none()]
    )
    cleanup = mocker.patch.object(editor_media, "_cleanup_media_object", return_value=False)
    api_client.force_authenticate(user=superuser)
    response = api_client.post(
        reverse("cast:api:editor_media_images"),
        {"title": "Recovery image", "file": image_1px, "collection": existing.collection_id},
        format="multipart",
    )
    assert response.status_code == 500
    assert response.json()["code"] == "cleanup_failed"
    image = editor_media.get_image_model().objects.get(title="Recovery image")
    cleanup.assert_called_once_with(image, ("file",))
    assert storage.exists(image.file.name)
    assert storage.open(existing.file.name).read() == original_bytes
