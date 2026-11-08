"""Authorization must use the current, locked audio before any form/storage work."""

import subprocess
from concurrent.futures import ThreadPoolExecutor

import pytest
from django.db import close_old_connections, connection, transaction
from django.urls import reverse

from cast.api.editor import media as editor_media
from cast.models import Audio
from tests.api.editor_audio_update_test import oga_upload
from tests.factories import UserFactory


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("separate_connection", [False, True], ids=["interleaved", "postgres"])
@pytest.mark.parametrize("revoked", ["choose", "change"])
@pytest.mark.parametrize("upload", [False, True], ids=["metadata", "file"])
def test_patch_rechecks_locked_audio_permissions(
    pg_editor_actors, scoped_editor_audio, api_client, mocker, separate_connection, revoked, upload
):
    if separate_connection and connection.vendor != "postgresql":
        pytest.skip("PostgreSQL separate-connection admission regression")
    actor, audio, forbidden = scoped_editor_audio
    other_owner = UserFactory()
    original_patch = editor_media.EditorAudioDetailView._patch
    before = Audio.objects.filter(pk=audio.pk).values().get()
    storage = audio.m4a.storage
    files_before = storage.listdir("cast_audio")
    probe = mocker.patch(
        "cast.models.audio.run_media_probe",
        return_value=subprocess.CompletedProcess([], 0, stdout=b"60.000000\n"),
    )
    form = mocker.spy(editor_media, "EditorAudioUpdateForm")
    ingest = mocker.spy(editor_media, "ingest_upload")
    save = mocker.spy(storage, "save")
    delete = mocker.spy(storage, "delete")
    interleaved = []

    def revoke():
        if separate_connection:
            close_old_connections()
        try:
            with transaction.atomic():
                if separate_connection:
                    with connection.cursor() as cursor:
                        cursor.execute("SET LOCAL lock_timeout = '5s'")
                    Audio.objects.select_for_update().get(pk=audio.pk)
                changes = {"collection_id": forbidden.pk} if revoked == "choose" else {"user_id": other_owner.pk}
                assert Audio.objects.filter(pk=audio.pk).update(**changes) == 1
            interleaved.append(True)
        finally:
            if separate_connection:
                close_old_connections()

    def after_initial_permission_check(view, request, stale):
        assert stale.collection_id == before["collection_id"]
        assert stale.user_id == actor.pk
        if separate_connection:
            with ThreadPoolExecutor(max_workers=1) as executor:
                executor.submit(revoke).result(timeout=10)
        else:
            revoke()
        return original_patch(view, request, stale)

    mocker.patch.object(editor_media.EditorAudioDetailView, "_patch", after_initial_permission_check)
    api_client.force_authenticate(user=actor)
    payload = {"title": "Rejected", "tags": "changed", "chaptermarks": "00:00:00 Changed"}
    if upload:
        payload["oga"] = oga_upload()
    response = api_client.patch(
        reverse("cast:api:editor_media_audio_detail", args=[audio.pk]),
        payload,
        format="multipart" if upload else "json",
    )
    assert interleaved == [True]
    expected_status, expected_body = (
        (404, {"code": "not_found", "detail": "Audio not found."})
        if revoked == "choose"
        else (403, {"code": "permission_denied", "detail": "You cannot change this audio."})
    )
    assert response.status_code == expected_status, response.content
    assert response.json() == expected_body
    before["collection_id" if revoked == "choose" else "user_id"] = (
        forbidden.pk if revoked == "choose" else other_owner.pk
    )
    assert Audio.objects.filter(pk=audio.pk).values().get() == before
    assert list(audio.tags.values_list("name", flat=True)) == ["original"]
    assert list(audio.chaptermarks.values_list("title", flat=True)) == ["Original chapter"]
    assert storage.listdir("cast_audio") == files_before
    form.assert_not_called()
    ingest.assert_not_called()
    save.assert_not_called()
    delete.assert_not_called()
    probe.assert_not_called()
