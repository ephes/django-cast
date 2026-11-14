"""Synthetic persisted files and transaction ownership regressions."""

import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from django.core.files.base import ContentFile
from django.db import close_old_connections, connection, transaction
from wagtail.models import Collection

from cast.file_replacement import FileFieldReplacementGuard, StagedFileReplacementGroup
from cast.media_ingest import IngestPolicy, ingest_upload
from cast.models import Audio
from tests.factories import UserFactory


@pytest.fixture
def synthetic_audio():
    audio = Audio(
        user=UserFactory(),
        collection=Collection.get_first_root_node() or Collection.add_root(name="Synthetic"),
        title="Original",
    )
    audio.m4a.save("synthetic-old.m4a", ContentFile(b"old synthetic bytes"), save=False)
    audio.save(duration=False, cache_file_sizes=False)
    return audio


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("commit", [False, True])
def test_staged_files_follow_outer_transaction(synthetic_audio, commit):
    audio = synthetic_audio
    old_name = audio.m4a.name
    storage = audio.m4a.storage
    group = StagedFileReplacementGroup()
    try:
        with transaction.atomic():
            replacement = group.stage(audio.m4a, "synthetic-new.m4a", b"new synthetic bytes")
            group.save_model(audio, duration=False, cache_file_sizes=False)
            assert storage.exists(old_name)
            if not commit:
                raise RuntimeError("outer transaction failed")
    except RuntimeError:
        group.rollback()
    audio.refresh_from_db()
    assert audio.m4a.name == (replacement.new_name if commit else old_name)
    assert storage.exists(replacement.new_name) is commit
    assert storage.exists(old_name) is not commit


@pytest.mark.django_db(transaction=True)
def test_replacement_refuses_a_stale_loaded_row(synthetic_audio):
    original = synthetic_audio
    stale = Audio.objects.get(pk=original.pk)
    original.title = "Newer title"
    original.save(duration=False, cache_file_sizes=False)
    with transaction.atomic(), pytest.raises(ValueError, match="changed"):
        FileFieldReplacementGuard.track(stale, ("m4a",), using="default")
    original.refresh_from_db()
    assert original.title == "Newer title"


@pytest.mark.django_db(transaction=True)
@pytest.mark.skipif(connection.vendor != "postgresql", reason="Requires independent row-lock transactions")
def test_concurrent_ingest_has_one_winner_and_no_losing_files(synthetic_audio, monkeypatch):
    audio = synthetic_audio
    copies = [Audio.objects.get(pk=audio.pk) for _ in range(2)]
    entered = threading.Event()
    second_started = threading.Event()
    second_boundary = threading.Event()
    release = threading.Event()
    original_track = FileFieldReplacementGuard.track
    old_name = audio.m4a.name
    storage = audio.m4a.storage
    before = set(storage.listdir("cast_audio")[1])

    def track(instance, fields, *, using):
        guard = original_track(instance, fields, using=using)
        if instance is copies[1]:
            second_boundary.set()
        return guard

    monkeypatch.setattr(FileFieldReplacementGuard, "track", track)

    def save(index):
        instance = copies[index]
        close_old_connections()
        try:
            if index:
                second_started.set()

            def save_form():
                if index == 0:
                    entered.set()
                    assert release.wait(10)
                instance.title = f"Editor {index}"
                instance.m4a.save(f"synthetic-{index}.m4a", ContentFile(b"synthetic replacement"), save=False)
                instance.save(duration=False, cache_file_sizes=False)
                return instance

            def observe_lock(execute, sql, params, many, context):
                if index and sql.startswith('UPDATE "cast_audio" SET "id"'):
                    second_boundary.set()
                return execute(sql, params, many, context)

            with connection.execute_wrapper(observe_lock):
                return ingest_upload(
                    SimpleNamespace(instance=instance, save=save_form), policy=IngestPolicy(None, ("m4a",))
                )
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(save, 0)
        try:
            assert entered.wait(10)
            second = pool.submit(save, 1)
            assert second_started.wait(10)
            # Observe either the attempted row lock or the unsafe old snapshot.
            # This controls the interleaving without depending on thread speed.
            assert second_boundary.wait(10)
        finally:
            release.set()
        winner = first.result(timeout=20)
        with pytest.raises(ValueError, match="changed"):
            second.result(timeout=20)
    audio.refresh_from_db()
    assert audio.title == "Editor 0"
    assert audio.m4a.name == winner.m4a.name
    assert not storage.exists(old_name)
    assert set(storage.listdir("cast_audio")[1]) == (before - {old_name.rsplit("/", 1)[-1]}) | {
        winner.m4a.name.rsplit("/", 1)[-1]
    }


@pytest.mark.django_db(transaction=True)
def test_explicit_scope_cleans_a_silent_outer_rollback(synthetic_audio):
    audio = synthetic_audio
    old_name = audio.m4a.name
    group = StagedFileReplacementGroup()
    with group.rollback_scope(), transaction.atomic():
        replacement = group.stage(audio.m4a, "silent.m4a", b"synthetic new bytes")
        group.save_model(audio, duration=False, cache_file_sizes=False)
        transaction.set_rollback(True)
    audio.refresh_from_db()
    assert audio.m4a.name == old_name
    assert audio.m4a.storage.exists(old_name)
    assert not audio.m4a.storage.exists(replacement.new_name)


@pytest.mark.django_db(transaction=True)
def test_staged_conflict_cleans_losing_files(synthetic_audio):
    audio = synthetic_audio
    group = StagedFileReplacementGroup()
    replacement = group.stage(audio.m4a, "loser.m4a", b"losing synthetic bytes")
    # A separately published file generation invalidates this staged edit even
    # if a bulk writer deliberately preserved the modified timestamp.
    Audio.objects.filter(pk=audio.pk).update(m4a="cast_audio/newer.m4a")
    with pytest.raises(ValueError, match="changed"):
        group.save_model(audio, duration=False, cache_file_sizes=False)
    assert not audio.m4a.storage.exists(replacement.new_name)
    audio.refresh_from_db()
    assert audio.m4a.name == "cast_audio/newer.m4a"


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("transport", ["api", "admin"])
def test_replacement_transport_reports_concurrent_edit(
    synthetic_audio, transport, api_client, admin_client, pg_editor_actors, monkeypatch
):
    from django.urls import reverse

    from cast.api.editor import media as editor_media
    from cast.views import media as admin_media

    admin_user, _blog = pg_editor_actors
    audio = synthetic_audio
    target = editor_media if transport == "api" else admin_media
    original_ingest = target.ingest_upload

    def competing_save(form, **kwargs):
        newer = Audio.objects.get(pk=audio.pk)
        newer.title = "Concurrent edit"
        newer.save(duration=False, cache_file_sizes=False)
        return original_ingest(form, **kwargs)

    monkeypatch.setattr(target, "ingest_upload", competing_save)
    if transport == "api":
        api_client.force_authenticate(user=admin_user)
        response = api_client.patch(
            reverse("cast:api:editor_media_audio_detail", args=[audio.pk]), {"title": "Stale title"}, format="json"
        )
        assert response.status_code == 409
        assert response.json()["code"] == "media_changed"
    else:
        response = admin_client.post(reverse("castaudio:edit", args=[audio.pk]), {"title": "Stale title"})
        assert response.status_code == 200
        assert "changed" in str(response.context["form"].non_field_errors())
    audio.refresh_from_db()
    assert audio.title == "Concurrent edit"


@pytest.mark.django_db(transaction=True)
def test_nested_scope_is_refused_before_staging(synthetic_audio):
    audio = synthetic_audio
    old_name = audio.m4a.name
    group = StagedFileReplacementGroup()
    with transaction.atomic():
        with pytest.raises(RuntimeError, match="durable"):
            with group.rollback_scope():
                pytest.fail("nested ownership was accepted")
    assert group.replacements == []
    assert audio.m4a.name == old_name


@pytest.mark.django_db(transaction=True)
def test_manual_rollback_in_a_later_savepoint_keeps_pending_files(synthetic_audio):
    audio = synthetic_audio
    old_name = audio.m4a.name
    group = StagedFileReplacementGroup()
    with transaction.atomic():
        replacement = group.stage(audio.m4a, "pending.m4a", b"synthetic bytes")
        group.save_model(audio, duration=False, cache_file_sizes=False)
        with transaction.atomic():
            with pytest.raises(RuntimeError, match="Exit the owning transaction"):
                group.rollback()
        assert audio.m4a.storage.exists(replacement.new_name)
    audio.refresh_from_db()
    assert audio.m4a.name == replacement.new_name
    assert audio.m4a.storage.exists(replacement.new_name)
    assert not audio.m4a.storage.exists(old_name)


@pytest.mark.django_db(transaction=True)
def test_scope_uses_one_database_and_cleans_a_rejected_save(synthetic_audio):
    audio = synthetic_audio
    old_name = audio.m4a.name
    group = StagedFileReplacementGroup()
    with pytest.raises(ValueError, match="database"):
        with group.rollback_scope():
            replacement = group.stage(audio.m4a, "wrong-db.m4a", b"synthetic bytes")
            group.save_model(audio, using="migration_other", duration=False, cache_file_sizes=False)
    assert audio.m4a.storage.exists(old_name)
    assert not audio.m4a.storage.exists(replacement.new_name)
    # A canceled owner cannot later retire old files through a stale callback.
    group._commit()
    assert audio.m4a.storage.exists(old_name)


@pytest.mark.django_db(transaction=True)
def test_scope_commits_and_retires_old_file_once(synthetic_audio, mocker):
    audio = synthetic_audio
    old_name = audio.m4a.name
    delete = mocker.spy(audio.m4a.storage, "delete")
    group = StagedFileReplacementGroup()
    with group.rollback_scope():
        replacement = group.stage(audio.m4a, "committed.m4a", b"synthetic bytes")
        group.save_model(audio, duration=False, cache_file_sizes=False)
        assert audio.m4a.storage.exists(old_name)
    group.rollback()
    audio.refresh_from_db()
    assert audio.m4a.name == replacement.new_name
    assert audio.m4a.storage.exists(replacement.new_name)
    delete.assert_called_once_with(old_name)


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("interruption", [KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize("replace", [False, True])
@pytest.mark.parametrize("writes", [1, 2])
def test_interrupted_ingest_compensates_real_files(synthetic_audio, interruption, replace, writes):
    original = synthetic_audio
    old_name = original.m4a.name
    storage = original.m4a.storage
    instance = original if replace else Audio(user=original.user, collection=original.collection, title="New")
    written = []
    error = interruption("synthetic interruption during derivation")

    def save():
        for field in ("m4a", "mp3")[:writes]:
            getattr(instance, field).save(f"interrupt.{field}", ContentFile(b"synthetic new bytes"), save=False)
            written.append(getattr(instance, field).name)
        instance.save(duration=False, cache_file_sizes=False)
        raise error

    with pytest.raises(interruption) as raised:
        ingest_upload(SimpleNamespace(instance=instance, save=save), policy=IngestPolicy(None, ("m4a", "mp3")))
    assert raised.value is error
    assert all(not storage.exists(name) for name in written)
    assert storage.exists(old_name)
    original.refresh_from_db()
    assert original.m4a.name == old_name
    assert Audio.objects.count() == 1


@pytest.mark.django_db(transaction=True)
def test_post_commit_interruption_keeps_committed_files(synthetic_audio):
    audio = synthetic_audio
    written = []

    def stop_after_commit():
        raise KeyboardInterrupt("synthetic callback interruption")

    def save():
        audio.m4a.save("committed-interrupt.m4a", ContentFile(b"committed bytes"), save=False)
        written.append(audio.m4a.name)
        audio.save(duration=False, cache_file_sizes=False)
        transaction.on_commit(stop_after_commit)
        return audio

    with pytest.raises(KeyboardInterrupt):
        ingest_upload(SimpleNamespace(instance=audio, save=save), policy=IngestPolicy(None, ("m4a",)))
    audio.refresh_from_db()
    assert audio.m4a.name == written[0]
    assert audio.m4a.storage.exists(written[0])
