"""Synthetic storage publication and cleanup failures retain owned boundaries."""

from io import StringIO

import pytest
from django.core.management import CommandError, call_command

from cast.management.commands.storage_backend import refresh_existing_file, remove_staged_copies
from tests.management_command_test import StubOverwriteStorage


@pytest.mark.parametrize("mode", ["backup", "refresh", "restore"])
@pytest.mark.parametrize("saved_alternate", [True, False])
def test_missing_copy_requires_exact_name_and_keeps_concurrent_writer(mocker, mode, saved_alternate):
    source = StubOverwriteStorage({"media.jpg": b"source"})
    target = StubOverwriteStorage({"unrelated.jpg": b"unrelated"})
    original_save = target.save

    def renamed_save(name, content):
        if name != "media.jpg":
            return original_save(name, content)
        target._files[name] = b"concurrent writer"
        if saved_alternate:
            return original_save("media_other.jpg", content)
        return "media_other.jpg"

    mocker.patch.object(target, "save", side_effect=renamed_save)
    command = "media_restore" if mode == "restore" else "media_backup"
    storages = (target, source) if mode == "restore" else (source, target)
    mocker.patch(f"cast.management.commands.{command}.get_production_and_backup_storage", return_value=storages)
    output, errors = StringIO(), StringIO()
    options = {"refresh_changed": True} if mode == "refresh" else {}
    with pytest.raises(CommandError):
        call_command(command, stdout=output, stderr=errors, **options)
    assert target._files == {"media.jpg": b"concurrent writer", "unrelated.jpg": b"unrelated"}
    assert [name for name in target.deleted if ".django-cast-refresh-" not in name] == (
        ["media_other.jpg"] if saved_alternate else []
    )
    assert len(target.deleted) == 1 + int(saved_alternate)
    assert "copied=0 refreshed=0 unchanged=0 errors=1" in output.getvalue()
    assert "media_other.jpg" in errors.getvalue()


@pytest.mark.parametrize("both_fail", [False, True])
def test_staging_cleanup_attempts_all_keys_and_reports_all_failures(mocker, both_fail):
    storage = StubOverwriteStorage({"a.tmp": b"a", "b.tmp": b"b"})
    original_delete = storage.delete
    attempted = []

    def delete(name):
        attempted.append(name)
        if name == "a.tmp" or both_fail:
            raise OSError("denied")
        original_delete(name)

    mocker.patch.object(storage, "delete", side_effect=delete)
    with pytest.raises(RuntimeError) as error:
        remove_staged_copies(storage, {"a.tmp", "b.tmp"})
    assert attempted == ["a.tmp", "b.tmp"]
    assert "a.tmp" in str(error.value)
    assert ("b.tmp" in str(error.value)) == both_fail
    assert storage._files == ({"a.tmp": b"a", "b.tmp": b"b"} if both_fail else {"a.tmp": b"a"})


@pytest.mark.parametrize("through_command", [False, True])
def test_refresh_preserves_publication_error_and_logs_cleanup_leftover(mocker, caplog, through_command):
    source = StubOverwriteStorage({"media.jpg": b"new"})
    target = StubOverwriteStorage({"media.jpg": b"original"})
    requested, returned = "a-stage.tmp", "b-stage.tmp"
    mocker.patch("cast.management.commands.storage_backend.temporary_refresh_path", return_value=requested)
    original_delete = target.delete
    attempted = []

    def save(name, content):
        if name == requested:
            target._files[requested] = b"partial"
            target._files[returned] = content.read()
            return returned
        raise OSError("primary publication failure")

    def delete(name):
        attempted.append(name)
        if name == requested:
            raise OSError("cleanup denied")
        original_delete(name)

    mocker.patch.object(target, "save", side_effect=save)
    mocker.patch.object(target, "delete", side_effect=delete)
    if through_command:
        mocker.patch(
            "cast.management.commands.media_backup.get_production_and_backup_storage", return_value=(source, target)
        )
        errors = StringIO()
        with pytest.raises(CommandError):
            call_command("media_backup", refresh_changed=True, stdout=StringIO(), stderr=errors)
        assert "primary publication failure" in errors.getvalue()
        assert requested in errors.getvalue()
        assert "cleanup denied" in errors.getvalue()
    else:
        with pytest.raises(OSError, match="primary publication failure") as error:
            refresh_existing_file(source, target, "media.jpg")
        assert requested in error.value.__notes__[0]
    assert attempted == [requested, returned]
    assert target._files == {"media.jpg": b"original", requested: b"partial"}
    assert requested in caplog.text
    assert "cleanup denied" in caplog.text


@pytest.mark.parametrize("mode", ["backup", "refresh", "restore"])
def test_nested_storage_keys_are_compared_with_portable_separators(mocker, mode):
    import ntpath
    from contextlib import contextmanager
    from types import SimpleNamespace

    from cast import utils

    # Simulate native Windows joins in the old walker without changing the host OS.
    mocker.patch.object(utils, "os", SimpleNamespace(path=ntpath), create=True)

    class PortableStorage(StubOverwriteStorage):
        def exists(self, name):
            return super().exists(name.replace("\\", "/"))

        def save(self, name, content):
            return super().save(name.replace("\\", "/"), content)

        def listdir(self, path):
            return (["album"], []) if not path else ([], ["photo.jpg"])

        @contextmanager
        def open(self, name, mode):
            with super().open(name.replace("\\", "/"), mode) as file:
                yield file

    source = PortableStorage({"album/photo.jpg": b"source"})
    target = PortableStorage()
    command = "media_restore" if mode == "restore" else "media_backup"
    pair = (target, source) if mode == "restore" else (source, target)
    mocker.patch(f"cast.management.commands.{command}.get_production_and_backup_storage", return_value=pair)
    options = {"refresh_changed": True} if mode == "refresh" else {}
    call_command(command, stdout=StringIO(), **options)
    assert target._files == {"album/photo.jpg": b"source"}
    assert len(target.deleted) == 1
    assert ".django-cast-refresh-" in target.deleted[0]


@pytest.mark.parametrize("failure", ["exists", "delete"])
def test_renamed_copy_reports_leftover_when_cleanup_fails(mocker, failure):
    from cast.management.commands.storage_backend import copy_missing_file

    source = StubOverwriteStorage({"media.jpg": b"source"})
    target = StubOverwriteStorage()
    original_save = target.save
    mocker.patch.object(
        target,
        "save",
        side_effect=lambda name, content: original_save("alternate.jpg" if name == "media.jpg" else name, content),
    )
    original_operation = getattr(target, failure)

    def fail_on_alternate(name):
        if name == "alternate.jpg":
            raise OSError("cleanup denied")
        return original_operation(name)

    mocker.patch.object(target, failure, side_effect=fail_on_alternate)
    with pytest.raises(RuntimeError, match="alternate.jpg.*requested media.jpg.*cleanup denied"):
        copy_missing_file(source, target, "media.jpg")
    assert target._files == {"alternate.jpg": b"source"}


def test_inventory_refuses_literal_backslash_keys():
    from cast.management.commands.storage_backend import sync_media_files

    source = StubOverwriteStorage({"album\\photo.jpg": b"literal", "album/photo.jpg": b"slash"})
    target = StubOverwriteStorage()
    result = sync_media_files(source, target)
    assert target._files == {}
    assert result.copied == 0
    assert result.errors == 1


@pytest.mark.parametrize("failure", ["exists", "delete"])
def test_refresh_reports_generated_alternate_when_cleanup_fails(mocker, failure):
    source = StubOverwriteStorage({"media.jpg": b"new"})
    target = StubOverwriteStorage({"media.jpg": b"old"})
    original_save, original_operation = target.save, getattr(target, failure)

    def save(name, content):
        return original_save("alternate.jpg" if name == "media.jpg" else name, content)

    def fail_on_alternate(name):
        if name == "alternate.jpg":
            raise OSError("cleanup denied")
        return original_operation(name)

    mocker.patch.object(target, "save", side_effect=save)
    mocker.patch.object(target, failure, side_effect=fail_on_alternate)
    with pytest.raises(RuntimeError, match="alternate.jpg.*media.jpg.*cleanup denied"):
        refresh_existing_file(source, target, "media.jpg")
    assert target._files == {"media.jpg": b"old", "alternate.jpg": b"new"}


def test_renamed_missing_copy_reports_that_nothing_was_published():
    from cast.management.commands.storage_backend import sync_media_files
    from tests.management_command_test import StubOverwriteStorage

    class RenamingStorage(StubOverwriteStorage):
        def save(self, name, content):
            if ".django-cast-refresh-" in name:
                return super().save(name, content)
            return super().save(name + "_renamed", content)

    errors = []
    target = RenamingStorage()
    result = sync_media_files(StubOverwriteStorage({"media.jpg": b"abc"}), target, report_error=errors.append)
    assert result.errors == 1
    assert "nothing was published at the requested path" in errors[0]
    assert "was removed" not in errors[0]
    assert "media.jpg" not in target._files and "media.jpg_renamed" not in target._files

    class StuckRenamingStorage(RenamingStorage):
        def delete(self, path):
            if path.endswith("_renamed"):
                raise OSError("synthetic delete refusal")
            super().delete(path)

    errors.clear()
    stuck = StuckRenamingStorage()
    result = sync_media_files(StubOverwriteStorage({"media.jpg": b"abc"}), stuck, report_error=errors.append)
    assert result.errors == 1
    assert "could not remove generated copy media.jpg_renamed" in errors[0]
    assert "synthetic delete refusal" in errors[0]
    assert "was removed" not in errors[0]
