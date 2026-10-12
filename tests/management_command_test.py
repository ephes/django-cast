import sqlite3
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from io import BytesIO, StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from django.core.exceptions import ObjectDoesNotExist
from django.core.files.base import ContentFile
from django.core.files.storage import storages
from django.core.management import CommandError, call_command
from django.db import OperationalError, connection, transaction
from django.utils import timezone

from cast.devdata import create_transcript
from cast.management.commands.media_backup import Command as MediaBackupCommand
from cast.management.commands.media_stale import Command as MediaStaleCommand, reference_lock_statements
from cast.models import Contributor, File
from cast.models.contributors import ContributorVoiceReference
from cast.voxhelm import TranscriptGenerationResult, VoxhelmError

from .factories import BlogFactory
from .multisite_helpers import create_site_root


def test_media_backup_without_storages(settings):
    settings.STORAGES = {}
    with pytest.raises(CommandError) as err:
        call_command("media_backup")
    assert str(err.value) == "production or backup storage not configured"


def _stub_styleguide_prefetch(mocker, *, default_theme="plain", available_themes=None):
    if available_themes is None:
        available_themes = [("plain", "Plain")]

    mocker.patch(
        "cast.management.commands.styleguide_prefetch.get_template_base_dir_choices",
        return_value=available_themes,
    )
    styleguide_data = object()
    build_styleguide_data = mocker.patch(
        "cast.management.commands.styleguide_prefetch._build_styleguide_data",
        return_value=styleguide_data,
    )
    render_styleguide_context = mocker.patch("cast.management.commands.styleguide_prefetch._styleguide_context")
    default_theme_mock = mocker.patch(
        "cast.management.commands.styleguide_prefetch._styleguide_default_theme",
        return_value=default_theme,
    )
    return styleguide_data, build_styleguide_data, render_styleguide_context, default_theme_mock


class StubStorage:
    def __init__(self) -> None:
        self._files: dict[str, BytesIO] = {}
        self._added: set[str] = set()

    def exists(self, path: str) -> bool:
        return path in self._files

    def was_added_by_backup(self, name: str) -> bool:
        return name in self._added

    def was_not_added_by_backup(self, name: str) -> bool:
        return name not in self._added

    def save(self, name: str, content: BytesIO) -> None:
        self.save_without_adding(name, content)
        self._added.add(name)

    def save_without_adding(self, name: str, content: BytesIO) -> None:
        self._files[name] = content

    def listdir(self, _path: str) -> tuple[list, dict[str, BytesIO]]:
        return [], self._files

    @contextmanager
    def open(self, name: str, _mode: str) -> Iterator[BytesIO]:
        try:
            yield self._files[name]
        finally:
            pass


class StubProductionStorage:
    def __init__(self) -> None:
        self._files: dict[str, bytes] = {}
        self.deleted: list[str] = []
        self.saved: list[str] = []

    def exists(self, path: str) -> bool:
        return path in self._files

    def delete(self, path: str) -> None:
        self.deleted.append(path)
        self._files.pop(path, None)

    def save(self, path: str, content: BytesIO) -> str:
        self.saved.append(path)
        self._files[path] = content.read()
        return path

    def add(self, path: str, content: bytes) -> None:
        self._files[path] = content

    @contextmanager
    def open(self, name: str, _mode: str) -> Iterator[BytesIO]:
        yield BytesIO(self._files[name])


class StubLocalStorage:
    def __init__(self, files: dict[str, bytes]) -> None:
        self._files = files

    def exists(self, path: str) -> bool:
        return path in self._files

    @contextmanager
    def open(self, name: str, _mode: str) -> Iterator[BytesIO]:
        yield BytesIO(self._files[name])


class StubWalkStorage:
    """
    Storage stub for ``media_stale``. Files are old unless ``modified`` says
    otherwise; the hooks let a test interleave an upload with the command.
    """

    def __init__(self, files: dict[str, bytes], modified: dict[str, object] | None = None) -> None:
        self._files = files
        self.modified: dict[str, object] = dict(modified or {})
        self.deleted: list[str] = []
        self.before_listing: Callable[[], None] | None = None
        self.before_modified_time: Callable[[str], None] | None = None

    def listdir(self, _path: str) -> tuple[list[str], list[str]]:
        if self.before_listing is not None:
            self.before_listing()
        return [], list(self._files.keys())

    def size(self, path: str) -> int:
        return len(self._files[path])

    def get_modified_time(self, path: str) -> object:
        if self.before_modified_time is not None:
            self.before_modified_time(path)
        modified = self.modified.get(path, timezone.now() - timedelta(days=30))
        if isinstance(modified, Exception):
            raise modified
        return modified

    def delete(self, path: str) -> None:
        self.deleted.append(path)


@pytest.fixture
def stub_storages(settings):
    storage_stub = {"BACKEND": "tests.management_command_test.StubStorage"}
    settings.STORAGES = {"production": storage_stub, "backup": storage_stub}
    return storages


def test_media_backup_new_file_in_production(stub_storages):
    production, backup = stub_storages["production"], stub_storages["backup"]

    # given there's a new file added to production
    production.save_without_adding("foobar.jpg", BytesIO(b"foobar"))  # type: ignore

    # when we run the backup command
    call_command("media_backup")

    # then the file should have been added by the backup command
    assert backup.was_added_by_backup("foobar.jpg")  # type: ignore


def test_media_backup_existing_file_in_backup(stub_storages):
    production, backup = stub_storages["production"], stub_storages["backup"]

    # given there's a file in the backup
    production.save_without_adding("foobar.jpg", BytesIO(b"foobar"))  # type: ignore
    backup.save_without_adding("foobar.jpg", BytesIO(b"foobar"))  # type: ignore

    # when we run the backup method
    MediaBackupCommand().backup_media_files(production, backup)

    # then the file should not have been added by the backup command
    assert backup.was_not_added_by_backup("foobar.jpg")  # type: ignore


class StubOverwriteStorage:
    """In-memory storage that overwrites existing names, like object storage does."""

    def __init__(self, files: dict[str, bytes] | None = None) -> None:
        self._files: dict[str, bytes] = dict(files or {})
        self.saved: list[str] = []
        self.deleted: list[str] = []
        self.opened: list[str] = []

    def exists(self, path: str) -> bool:
        return path in self._files

    def size(self, path: str) -> int:
        return len(self._files[path])

    def listdir(self, _path: str) -> tuple[list[str], list[str]]:
        return [], list(self._files)

    def save(self, name: str, content: BytesIO) -> str:
        self.saved.append(name)
        self._files[name] = content.read()
        return name

    def delete(self, path: str) -> None:
        self.deleted.append(path)
        self._files.pop(path, None)

    @contextmanager
    def open(self, name: str, _mode: str) -> Iterator[BytesIO]:
        self.opened.append(name)
        yield BytesIO(self._files[name])

    def staged(self) -> list[str]:
        return [name for name in self._files if ".django-cast-refresh-" in name]


def patch_backup_storages(mocker, production, backup):
    mocker.patch(
        "cast.management.commands.media_backup.get_production_and_backup_storage",
        return_value=(production, backup),
    )


def test_media_backup_default_keeps_changed_backup_copy(mocker):
    # the default mode stays a cheap copy of missing paths
    production = StubOverwriteStorage({"video.mp4": b"new!", "added.mp4": b"added"})
    backup = StubOverwriteStorage({"video.mp4": b"old!"})
    patch_backup_storages(mocker, production, backup)
    output = StringIO()

    call_command("media_backup", stdout=output)

    assert backup._files == {"video.mp4": b"old!", "added.mp4": b"added"}
    assert "refreshed=" not in output.getvalue()


def test_media_backup_refresh_changed_replaces_equal_length_changed_copy(mocker):
    # same path, same length, different bytes: size alone would call them identical
    production = StubOverwriteStorage({"video.mp4": b"new!", "same.mp4": b"same", "added.mp4": b"added"})
    backup = StubOverwriteStorage({"video.mp4": b"old!", "same.mp4": b"same"})
    patch_backup_storages(mocker, production, backup)
    output = StringIO()

    call_command("media_backup", refresh_changed=True, stdout=output)

    assert backup._files == {"video.mp4": b"new!", "same.mp4": b"same", "added.mp4": b"added"}
    # the unchanged object was compared but never rewritten
    assert "same.mp4" not in backup.saved
    assert backup.staged() == []
    assert "copied=1 refreshed=1 unchanged=1 errors=0" in output.getvalue()


def test_media_backup_refresh_changed_skips_content_read_when_sizes_differ(mocker):
    production = StubOverwriteStorage({"video.mp4": b"longer than before"})
    backup = StubOverwriteStorage({"video.mp4": b"short"})
    patch_backup_storages(mocker, production, backup)

    call_command("media_backup", refresh_changed=True, stdout=StringIO())

    assert backup._files == {"video.mp4": b"longer than before"}
    # the backup copy was only read back from its staged key, never hashed
    assert "video.mp4" not in backup.opened


def test_media_backup_refresh_changed_compares_content_without_size_support(mocker):
    production = StubOverwriteStorage({"video.mp4": b"new!", "same.mp4": b"same"})
    backup = StubOverwriteStorage({"video.mp4": b"old!", "same.mp4": b"same"})
    mocker.patch.object(backup, "size", side_effect=NotImplementedError)
    patch_backup_storages(mocker, production, backup)
    output = StringIO()

    call_command("media_backup", refresh_changed=True, stdout=output)

    assert backup._files == {"video.mp4": b"new!", "same.mp4": b"same"}
    assert "copied=0 refreshed=1 unchanged=1 errors=0" in output.getvalue()


def test_media_backup_refresh_keeps_backup_copy_when_production_read_fails(mocker):
    production = StubOverwriteStorage({"bad.mp4": b"new bad", "good.mp4": b"new good"})
    backup = StubOverwriteStorage({"bad.mp4": b"old", "good.mp4": b"old"})
    patch_backup_storages(mocker, production, backup)
    original_save = backup.save

    def fail_while_staging_bad(name, content):
        if name.startswith("bad.mp4.django-cast-refresh-"):
            content.read(3)
            raise RuntimeError("connection reset")
        return original_save(name, content)

    mocker.patch.object(backup, "save", side_effect=fail_while_staging_bad)
    output = StringIO()
    error_output = StringIO()

    with pytest.raises(CommandError, match=r"1 path\(s\) could not be backed up") as err:
        call_command("media_backup", refresh_changed=True, stdout=output, stderr=error_output)

    assert err.value.returncode == 1
    # the previous backup bytes survive, and the later path was still refreshed
    assert backup._files == {"bad.mp4": b"old", "good.mp4": b"new good"}
    assert "error backing up bad.mp4: connection reset" in error_output.getvalue()
    assert "copied=0 refreshed=1 unchanged=0 errors=1" in output.getvalue()


def test_media_backup_refresh_removes_partial_staged_copy_when_staging_fails(mocker):
    # like FileSystemStorage: the object exists under the requested key before save() raises
    production = StubOverwriteStorage({"video.mp4": b"new!"})
    backup = StubOverwriteStorage({"video.mp4": b"old!"})
    patch_backup_storages(mocker, production, backup)

    def write_partial_object_then_fail(name, content):
        backup._files[name] = content.read(2)
        raise RuntimeError("connection reset")

    mocker.patch.object(backup, "save", side_effect=write_partial_object_then_fail)
    error_output = StringIO()

    with pytest.raises(CommandError):
        call_command("media_backup", refresh_changed=True, stdout=StringIO(), stderr=error_output)

    # no partial .tmp object is left for media_restore to copy into production
    assert backup._files == {"video.mp4": b"old!"}
    assert "error backing up video.mp4: connection reset" in error_output.getvalue()


def test_media_backup_refresh_counts_failed_existence_check_and_continues(mocker):
    production = StubOverwriteStorage({"bad.mp4": b"new bad", "good.mp4": b"new good", "added.mp4": b"added"})
    backup = StubOverwriteStorage({"bad.mp4": b"old", "good.mp4": b"old"})
    patch_backup_storages(mocker, production, backup)
    original_exists = backup.exists

    def fail_for_bad(path):
        if path == "bad.mp4":
            raise RuntimeError("service unavailable")
        return original_exists(path)

    mocker.patch.object(backup, "exists", side_effect=fail_for_bad)
    output = StringIO()
    error_output = StringIO()

    with pytest.raises(CommandError, match=r"1 path\(s\) could not be backed up"):
        call_command("media_backup", refresh_changed=True, stdout=output, stderr=error_output)

    assert backup._files == {"bad.mp4": b"old", "good.mp4": b"new good", "added.mp4": b"added"}
    assert "error backing up bad.mp4: service unavailable" in error_output.getvalue()
    assert "copied=1 refreshed=1 unchanged=0 errors=1" in output.getvalue()


def test_media_backup_default_mode_still_stops_at_the_first_failure(mocker):
    production = StubOverwriteStorage({"bad.mp4": b"bad", "later.mp4": b"later"})
    backup = StubOverwriteStorage()
    patch_backup_storages(mocker, production, backup)
    mocker.patch.object(backup, "exists", side_effect=RuntimeError("service unavailable"))

    with pytest.raises(RuntimeError, match="service unavailable"):
        call_command("media_backup", stdout=StringIO())

    assert backup._files == {}


def test_media_backup_refresh_keeps_backup_copy_when_staged_copy_is_missing(mocker):
    production = StubOverwriteStorage({"video.mp4": b"new!"})
    backup = StubOverwriteStorage({"video.mp4": b"old!"})
    patch_backup_storages(mocker, production, backup)
    mocker.patch.object(backup, "save", return_value="missing-stage.tmp")
    error_output = StringIO()

    with pytest.raises(CommandError):
        call_command("media_backup", refresh_changed=True, stdout=StringIO(), stderr=error_output)

    assert backup._files == {"video.mp4": b"old!"}
    assert "error backing up video.mp4: staged copy missing-stage.tmp was not saved" in error_output.getvalue()


@pytest.mark.parametrize("generated_copy_exists", [True, False])
def test_media_backup_refresh_keeps_backup_copy_when_storage_does_not_overwrite(mocker, generated_copy_exists):
    production = StubOverwriteStorage({"video.mp4": b"new!"})
    backup = StubOverwriteStorage({"video.mp4": b"old!"})
    patch_backup_storages(mocker, production, backup)
    original_save = backup.save

    def save_under_generated_name(name, content):
        if name == "video.mp4":
            if generated_copy_exists:
                return original_save("video_1.mp4", content)
            return "video_1.mp4"
        return original_save(name, content)

    mocker.patch.object(backup, "save", side_effect=save_under_generated_name)
    error_output = StringIO()

    with pytest.raises(CommandError):
        call_command("media_backup", refresh_changed=True, stdout=StringIO(), stderr=error_output)

    # neither the stray generated copy nor the staged copy is left behind
    assert backup._files == {"video.mp4": b"old!"}
    assert "saved the refreshed copy as video_1.mp4 instead of overwriting video.mp4" in error_output.getvalue()


def test_media_backup_refresh_reports_staged_copy_that_cannot_be_removed(mocker):
    production = StubOverwriteStorage({"video.mp4": b"new!"})
    backup = StubOverwriteStorage({"video.mp4": b"old!"})
    patch_backup_storages(mocker, production, backup)
    mocker.patch.object(backup, "delete", side_effect=RuntimeError("denied"))
    error_output = StringIO()

    with pytest.raises(CommandError):
        call_command("media_backup", refresh_changed=True, stdout=StringIO(), stderr=error_output)

    assert backup._files["video.mp4"] == b"new!"
    assert "error backing up video.mp4: could not remove staged copy video.mp4.django-cast-refresh-" in (
        error_output.getvalue()
    )


def test_sync_media_files_counts_refresh_errors_without_reporter():
    from cast.management.commands.storage_backend import sync_media_files

    production = StubOverwriteStorage({"video.mp4": b"new!"})
    backup = StubOverwriteStorage({"video.mp4": b"old!"})
    backup.save = Mock(side_effect=RuntimeError("boom"))  # type: ignore[method-assign]

    result = sync_media_files(production, backup, refresh_changed=True)  # type: ignore[arg-type]

    assert result.errors == 1
    assert backup._files == {"video.mp4": b"old!"}


def test_media_restore_never_overwrites_production(mocker):
    production = StubOverwriteStorage({"video.mp4": b"new!"})
    backup = StubOverwriteStorage({"video.mp4": b"old!", "lost.mp4": b"lost"})
    mocker.patch(
        "cast.management.commands.media_restore.get_production_and_backup_storage",
        return_value=(production, backup),
    )

    call_command("media_restore")

    assert production._files == {"video.mp4": b"new!", "lost.mp4": b"lost"}


def test_media_replace_requires_explicit_confirmation(mocker):
    output = StringIO()
    production = StubProductionStorage()
    production.add("foo.jpg", b"old")
    local = StubLocalStorage({"foo.jpg": b"new"})
    mocker.patch(
        "cast.management.commands.media_replace.get_production_and_backup_storage",
        return_value=(production, object()),
    )
    mocker.patch("cast.management.commands.media_replace.FileSystemStorage", return_value=local)

    with pytest.raises(CommandError, match="Use --yes"):
        call_command("media_replace", "foo.jpg", stdout=output)

    assert production.deleted == []
    assert production.saved == []
    assert "No files were changed" in output.getvalue()


def test_media_replace_dry_run_does_not_write(mocker):
    output = StringIO()
    production = StubProductionStorage()
    production.add("foo.jpg", b"old")
    local = StubLocalStorage({"foo.jpg": b"new"})
    mocker.patch(
        "cast.management.commands.media_replace.get_production_and_backup_storage",
        return_value=(production, object()),
    )
    mocker.patch("cast.management.commands.media_replace.FileSystemStorage", return_value=local)

    call_command("media_replace", "foo.jpg", dry_run=True, stdout=output)

    assert production.deleted == []
    assert production.saved == []
    text = output.getvalue()
    assert "DRY RUN" in text
    assert "would replace: foo.jpg" in text
    assert "planned=1 replaced=0 skipped=0 errors=0" in text


def test_media_replace_yes_replaces_and_logs_summary(mocker):
    output = StringIO()
    production = StubProductionStorage()
    production.add("foo.jpg", b"old")
    local = StubLocalStorage({"foo.jpg": b"new"})
    mocker.patch(
        "cast.management.commands.media_replace.get_production_and_backup_storage",
        return_value=(production, object()),
    )
    mocker.patch("cast.management.commands.media_replace.FileSystemStorage", return_value=local)

    call_command("media_replace", "foo.jpg", yes=True, stdout=output)

    assert "foo.jpg" not in production.deleted
    assert production.saved[-1] == "foo.jpg"
    assert production._files["foo.jpg"] == b"new"
    text = output.getvalue()
    assert "replaced: foo.jpg" in text
    assert "planned=1 replaced=1 skipped=0 errors=0" in text


def test_media_replace_summary_includes_skipped(mocker):
    output = StringIO()
    production = StubProductionStorage()
    local = StubLocalStorage({"ok.jpg": b"new"})
    mocker.patch(
        "cast.management.commands.media_replace.get_production_and_backup_storage",
        return_value=(production, object()),
    )
    mocker.patch("cast.management.commands.media_replace.FileSystemStorage", return_value=local)

    call_command("media_replace", "missing.jpg", "ok.jpg", dry_run=True, stdout=output)

    text = output.getvalue()
    assert "skipped (not found locally): missing.jpg" in text
    assert "would replace: ok.jpg" in text
    assert "planned=1 replaced=0 skipped=1 errors=0" in text


def test_media_replace_yes_saves_when_target_is_missing_in_production(mocker):
    output = StringIO()
    production = StubProductionStorage()
    local = StubLocalStorage({"foo.jpg": b"new"})
    mocker.patch(
        "cast.management.commands.media_replace.get_production_and_backup_storage",
        return_value=(production, object()),
    )
    mocker.patch("cast.management.commands.media_replace.FileSystemStorage", return_value=local)

    call_command("media_replace", "foo.jpg", yes=True, stdout=output)

    assert production.saved[-1] == "foo.jpg"
    assert production._files["foo.jpg"] == b"new"


def test_media_replace_without_yes_and_only_missing_paths_does_not_error(mocker):
    output = StringIO()
    production = StubProductionStorage()
    local = StubLocalStorage({})
    mocker.patch(
        "cast.management.commands.media_replace.get_production_and_backup_storage",
        return_value=(production, object()),
    )
    mocker.patch("cast.management.commands.media_replace.FileSystemStorage", return_value=local)

    call_command("media_replace", "missing.jpg", stdout=output)

    text = output.getvalue()
    assert "Use --yes" not in text
    assert "planned=0 replaced=0 skipped=1 errors=0" in text


@pytest.mark.django_db
def test_media_stale_get_models_paths_includes_all_managed_media(audio, video, file_instance):
    transcript = create_transcript(
        audio=audio,
        podlove={"transcripts": []},
        vtt="WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nHello\n",
        dote={"lines": []},
    )
    transcript.speakers.save("test.speakers.json", ContentFile(b'{"segments": []}'), save=True)
    contributor = Contributor.objects.create(display_name="Johannes", slug="johannes-stale")
    voice_reference = ContributorVoiceReference.objects.create(
        contributor=contributor,
        clip=ContentFile(b"RIFF....WAVEfmt ", name="voice.wav"),
    )
    paths = MediaStaleCommand().get_models_paths()

    assert audio.m4a.name in paths
    assert transcript.podlove.name in paths
    assert transcript.vtt.name in paths
    assert transcript.dote.name in paths
    assert transcript.speakers.name in paths
    assert voice_reference.clip.name in paths
    assert video.original.name in paths
    assert file_instance.original.name in paths


@pytest.mark.django_db
def test_media_stale_get_models_paths_includes_images_and_renditions(image):
    rendition = image.get_rendition("fill-1x1")

    paths = MediaStaleCommand().get_models_paths()

    assert image.file.name in paths
    assert rendition.file.name in paths


@pytest.mark.django_db
def test_media_stale_get_models_paths_uses_base_manager_and_normalizes(user, mocker):
    # a default manager that hides rows must not hide their files
    File.objects.create(user=user, original="/cast_files/hidden.pdf")
    hiding_manager = Mock(**{"all.return_value": File.objects.none(), "values_list.return_value": File.objects.none()})
    mocker.patch.object(File._meta, "default_manager", hiding_manager)
    assert File._default_manager is hiding_manager

    paths = MediaStaleCommand().get_models_paths()

    assert "cast_files/hidden.pdf" in paths


def patch_stale_storage(mocker, production):
    mocker.patch(
        "cast.management.commands.media_stale.get_production_and_backup_storage",
        return_value=(production, object()),
    )


@pytest.mark.django_db
def test_media_stale_handle_reports_and_deletes_managed_stale_files(mocker, capsys, user):
    File.objects.create(user=user, original="cast_files/keep.pdf")
    production = StubWalkStorage(
        {
            "cast_files/keep.pdf": b"keep",
            "cast_audio/stale.mp3": b"stale",
            "unrelated/stale.jpg": b"outside",
        }
    )
    patch_stale_storage(mocker, production)

    call_command("media_stale", delete=True)

    assert production.deleted == ["cast_audio/stale.mp3"]
    text = capsys.readouterr().out
    assert "stale production" in text
    assert "cast_audio/stale.mp3" in text
    assert "deleted cast_audio/stale.mp3" in text
    assert "deleted=1 retained=0" in text
    assert "cast_files/keep.pdf" not in text
    assert "unrelated/stale.jpg" not in text


@pytest.mark.django_db
def test_media_stale_matches_storage_paths_with_leading_slash(mocker, user):
    File.objects.create(user=user, original="cast_files/keep.pdf")
    production = StubWalkStorage({"/cast_files/keep.pdf": b"keep"})
    patch_stale_storage(mocker, production)
    # even a snapshot that missed the row must not get the file deleted
    mocker.patch.object(MediaStaleCommand, "get_models_paths", return_value=set())

    call_command("media_stale", delete=True)

    assert production.deleted == []


@pytest.mark.django_db
def test_media_stale_delete_keeps_upload_published_during_scan(mocker, capsys, user):
    """
    The reference snapshot is taken before production storage is listed. An
    upload that is saved and committed in between is in the listing but not in
    the snapshot, and must not be deleted.
    """
    production = StubWalkStorage({"cast_audio/old-orphan.mp3": b"orphan"})
    patch_stale_storage(mocker, production)

    def publish_upload() -> None:
        production._files["cast_files/new.pdf"] = b"new upload"
        production.modified["cast_files/new.pdf"] = timezone.now()
        File.objects.create(user=user, original="cast_files/new.pdf")

    production.before_listing = publish_upload

    call_command("media_stale", delete=True)

    assert production.deleted == ["cast_audio/old-orphan.mp3"]
    text = capsys.readouterr().out
    assert "retained cast_files/new.pdf: referenced by a database row" in text
    assert "deleted=1 retained=1" in text


@pytest.mark.django_db
def test_media_stale_delete_keeps_old_object_referenced_before_deletion(mocker, capsys, user):
    """A reference committed after the report, right before the delete, wins even for an old object."""
    production = StubWalkStorage({"cast_files/a.pdf": b"a", "cast_files/b.pdf": b"b"})
    patch_stale_storage(mocker, production)

    def reference_b_while_a_is_checked(path: str) -> None:
        if path == "cast_files/a.pdf":
            File.objects.create(user=user, original="cast_files/b.pdf")

    production.before_modified_time = reference_b_while_a_is_checked

    call_command("media_stale", delete=True)

    assert production.deleted == ["cast_files/a.pdf"]
    assert "retained cast_files/b.pdf: referenced by a database row" in capsys.readouterr().out


@pytest.mark.django_db
def test_media_stale_delete_keeps_recent_object_of_uncommitted_upload(mocker, capsys):
    """
    An upload in progress has written its file but not committed its row, so
    no database check can see it. Only its age protects it.
    """
    production = StubWalkStorage(
        {"cast_audio/in-progress.mp3": b"new", "cast_audio/old-orphan.mp3": b"old"},
        modified={
            "cast_audio/in-progress.mp3": timezone.now() - timedelta(hours=23),
            "cast_audio/old-orphan.mp3": timezone.now() - timedelta(hours=25),
        },
    )
    patch_stale_storage(mocker, production)

    call_command("media_stale", delete=True)

    assert production.deleted == ["cast_audio/old-orphan.mp3"]
    text = capsys.readouterr().out
    assert "retained cast_audio/in-progress.mp3: modified less than 24 hours ago" in text


@pytest.mark.django_db
def test_media_stale_delete_honors_min_age_hours(mocker):
    production = StubWalkStorage(
        {"cast_audio/a.mp3": b"a", "cast_audio/b.mp3": b"b"},
        modified={
            "cast_audio/a.mp3": timezone.now() - timedelta(hours=3),
            "cast_audio/b.mp3": timezone.now() - timedelta(minutes=90),
        },
    )
    patch_stale_storage(mocker, production)

    call_command("media_stale", delete=True, min_age_hours=2)

    assert production.deleted == ["cast_audio/a.mp3"]


@pytest.mark.parametrize("min_age_hours", [0, 0.5, -1, float("nan")])
def test_media_stale_rejects_min_age_below_minimum(mocker, min_age_hours):
    production = StubWalkStorage({"cast_audio/stale.mp3": b"stale"})
    patch_stale_storage(mocker, production)

    with pytest.raises(CommandError, match="--min-age-hours must be at least 1"):
        call_command("media_stale", delete=True, min_age_hours=min_age_hours)

    assert production.deleted == []


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("modified", "reason"),
    [
        (NotImplementedError(), "modification time unavailable (NotImplementedError)"),
        (FileNotFoundError(), "modification time unavailable (FileNotFoundError)"),
        (None, "modification time unavailable"),
        # a clock that disagrees with storage never makes a file old enough
        (timezone.now() + timedelta(days=2), "modified less than 24 hours ago"),
    ],
)
def test_media_stale_delete_keeps_object_without_provable_age(mocker, capsys, modified, reason):
    production = StubWalkStorage({"cast_audio/stale.mp3": b"stale"}, modified={"cast_audio/stale.mp3": modified})
    patch_stale_storage(mocker, production)
    if modified is None:
        mocker.patch.object(production, "get_modified_time", return_value=None)

    call_command("media_stale", delete=True)

    assert production.deleted == []
    text = capsys.readouterr().out
    assert f"retained cast_audio/stale.mp3: {reason}" in text
    assert "deleted=0 retained=1" in text


@pytest.mark.django_db
def test_media_stale_delete_compares_naive_modification_times(mocker):
    # storage backends return naive local times when USE_TZ is off
    production = StubWalkStorage(
        {"cast_audio/old.mp3": b"old", "cast_audio/new.mp3": b"new"},
        modified={
            "cast_audio/old.mp3": datetime.now() - timedelta(days=2),
            "cast_audio/new.mp3": datetime.now() - timedelta(hours=1),
        },
    )
    patch_stale_storage(mocker, production)

    call_command("media_stale", delete=True)

    assert production.deleted == ["cast_audio/old.mp3"]


def test_media_stale_lock_statements_for_postgresql():
    statements = reference_lock_statements("postgresql", ['"cast_file"', '"wagtailimages_image"'])

    assert statements == [
        ("SET TRANSACTION ISOLATION LEVEL READ COMMITTED", []),
        ("SET LOCAL lock_timeout = '500ms'", []),
        ('LOCK TABLE "cast_file", "wagtailimages_image" IN SHARE MODE', []),
    ]


def test_media_stale_lock_statements_for_sqlite():
    assert reference_lock_statements("sqlite", ['"cast_file"', '"wagtailimages_image"']) == [
        ('DELETE FROM "cast_file" WHERE 1 = 0', [])
    ]


@pytest.mark.django_db
def test_media_stale_locks_every_table_with_a_file_column():
    tables = MediaStaleCommand().get_reference_tables()

    assert list(tables) == ["default"]
    assert {"cast_file", "cast_audio", "cast_video", "wagtailimages_image", "wagtailimages_rendition"} <= set(
        tables["default"]
    )
    assert tables["default"] == sorted(tables["default"])


@pytest.mark.django_db
def test_media_stale_delete_refuses_database_without_supported_lock(mocker, capsys):
    production = StubWalkStorage({"cast_audio/stale.mp3": b"stale"})
    patch_stale_storage(mocker, production)
    mocker.patch.object(connection, "vendor", "mysql")

    with pytest.raises(CommandError, match="cannot hold off writes of file references on the mysql database"):
        call_command("media_stale", delete=True)

    assert production.deleted == []
    # the report alone needs no lock
    call_command("media_stale")
    assert "cast_audio/stale.mp3" in capsys.readouterr().out


@pytest.mark.django_db
def test_media_stale_delete_keeps_object_when_references_cannot_be_locked(mocker, capsys):
    production = StubWalkStorage({"cast_audio/stale.mp3": b"stale"})
    patch_stale_storage(mocker, production)

    @contextmanager
    def lock_times_out(_command: MediaStaleCommand) -> Iterator[None]:
        raise OperationalError("lock timeout")
        yield

    mocker.patch.object(MediaStaleCommand, "reference_writes_blocked", lock_times_out)

    call_command("media_stale", delete=True)

    assert production.deleted == []
    text = capsys.readouterr().out
    assert "retained cast_audio/stale.mp3: file references could not be locked or checked (OperationalError)" in text
    assert "deleted=0 retained=1" in text


def sqlite_reference_lock(database: Path) -> tuple[sqlite3.Connection, sqlite3.Connection]:
    """Two independent connections to one SQLite database with a table to lock."""
    locker = sqlite3.connect(database, timeout=0.2, isolation_level=None)
    writer = sqlite3.connect(database, timeout=0.2, isolation_level=None)
    locker.execute('CREATE TABLE "cast_file" (original TEXT)')
    return locker, writer


def test_media_stale_sqlite_lock_statement_holds_off_other_writers(tmp_path):
    locker, writer = sqlite_reference_lock(tmp_path / "lock.sqlite3")
    try:
        locker.execute("BEGIN")
        for sql, params in reference_lock_statements("sqlite", ['"cast_file"']):
            locker.execute(sql, params)

        # no other connection can write a reference until the transaction ends
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            writer.execute("INSERT INTO \"cast_file\" VALUES ('cast_files/old.pdf')")

        locker.execute("COMMIT")
        writer.execute("INSERT INTO \"cast_file\" VALUES ('cast_files/old.pdf')")
    finally:
        locker.close()
        writer.close()


def test_media_stale_sqlite_lock_statement_fails_while_a_write_is_in_flight(tmp_path):
    locker, writer = sqlite_reference_lock(tmp_path / "lock.sqlite3")
    try:
        writer.execute("BEGIN")
        writer.execute("INSERT INTO \"cast_file\" VALUES ('cast_files/old.pdf')")

        # an uncommitted reference is invisible, so the lock must not be granted
        locker.execute("BEGIN")
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            for sql, params in reference_lock_statements("sqlite", ['"cast_file"']):
                locker.execute(sql, params)
    finally:
        locker.close()
        writer.close()


POSTGRESQL_ONLY = pytest.mark.skipif(connection.vendor != "postgresql", reason="PostgreSQL table-lock semantics")


def write_file_reference_from_another_connection(user_pk: int, path: str, outcome: list[str]) -> None:
    """Try to commit a row that references ``path``, like a concurrent request would."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SET lock_timeout = '300ms'")
        File.objects.create(user_id=user_pk, original=path)
        outcome.append("committed")
    except OperationalError:
        outcome.append("blocked")
    finally:
        connection.close()


@pytest.mark.django_db(transaction=True)
@POSTGRESQL_ONLY
def test_media_stale_delete_holds_off_reference_writes_between_check_and_delete(mocker, user):
    """
    The window that a second reference query cannot close: a row that starts
    to reference an old object after the last check and before the delete.
    While the command decides about a path, no such row can be committed.
    """
    path = "cast_files/old.pdf"
    production = StubWalkStorage({path: b"old"})
    patch_stale_storage(mocker, production)
    outcome: list[str] = []

    def publish_reference_during_age_lookup(_path: str) -> None:
        # the reference check for this path has already passed
        writer = threading.Thread(target=write_file_reference_from_another_connection, args=(user.pk, path, outcome))
        writer.start()
        writer.join(timeout=10)
        assert not writer.is_alive()

    production.before_modified_time = publish_reference_during_age_lookup

    call_command("media_stale", delete=True)

    assert outcome == ["blocked"]
    assert production.deleted == [path]
    assert not File.objects.filter(original=path).exists()


@pytest.mark.django_db(transaction=True)
@POSTGRESQL_ONLY
@pytest.mark.parametrize("isolation_level", ["READ COMMITTED", "REPEATABLE READ", "SERIALIZABLE"])
def test_media_stale_delete_sees_reference_committed_while_waiting_for_the_lock(mocker, capsys, user, isolation_level):
    """
    The lock is granted when the writer commits. The reference check that
    follows must read that commit, also on a connection whose transactions
    would otherwise keep the snapshot they started with.
    """
    path = "cast_files/old.pdf"
    production = StubWalkStorage({path: b"old"})
    patch_stale_storage(mocker, production)
    written = threading.Event()
    errors: list[BaseException] = []

    def commit_reference_after_a_moment() -> None:
        try:
            with transaction.atomic():
                File.objects.create(user_id=user.pk, original=path)
                written.set()
                # shorter than the command's lock timeout, long enough for it to start waiting
                time.sleep(0.25)
        except BaseException as exc:  # pragma: no cover - reported by the assertion below
            errors.append(exc)
        finally:
            connection.close()

    # the report's snapshot is taken before the writer exists
    mocker.patch.object(MediaStaleCommand, "get_models_paths", return_value=set())
    with connection.cursor() as cursor:
        cursor.execute(f"SET SESSION CHARACTERISTICS AS TRANSACTION ISOLATION LEVEL {isolation_level}")
    writer = threading.Thread(target=commit_reference_after_a_moment)
    writer.start()
    try:
        assert written.wait(timeout=10)

        call_command("media_stale", delete=True)
    finally:
        writer.join(timeout=10)
        # the session default must not outlive the test
        connection.close()

    assert errors == []
    assert production.deleted == []
    assert f"retained {path}: referenced by a database row" in capsys.readouterr().out
    assert File.objects.filter(original=path).exists()


@pytest.mark.django_db(transaction=True)
@POSTGRESQL_ONLY
def test_media_stale_delete_keeps_object_while_a_reference_write_is_in_flight(mocker, capsys, user):
    """A transaction that wrote a reference but has not committed it yet keeps the object."""
    path = "cast_files/old.pdf"
    production = StubWalkStorage({path: b"old"})
    patch_stale_storage(mocker, production)
    written, release = threading.Event(), threading.Event()
    errors: list[BaseException] = []

    def hold_uncommitted_reference() -> None:
        try:
            with transaction.atomic():
                File.objects.create(user_id=user.pk, original=path)
                written.set()
                release.wait(timeout=30)
        except BaseException as exc:  # pragma: no cover - reported by the assertion below
            errors.append(exc)
        finally:
            connection.close()

    writer = threading.Thread(target=hold_uncommitted_reference)
    writer.start()
    try:
        assert written.wait(timeout=10)

        call_command("media_stale", delete=True)
    finally:
        release.set()
        writer.join(timeout=10)

    assert errors == []
    assert production.deleted == []
    assert f"retained {path}: file references could not be locked or checked (OperationalError)" in (
        capsys.readouterr().out
    )
    # the writer committed afterwards: the row references an object that still exists
    assert File.objects.filter(original=path).exists()


@pytest.mark.django_db
def test_media_stale_handle_without_delete_keeps_stale_files(mocker, capsys):
    production = StubWalkStorage({"cast_audio/stale.mp3": b"stale"})
    patch_stale_storage(mocker, production)

    call_command("media_stale")

    assert production.deleted == []
    text = capsys.readouterr().out
    assert "cast_audio/stale.mp3" in text
    assert "deleted=" not in text


@pytest.mark.django_db
def test_media_stale_handle_ignores_unmanaged_files(mocker, capsys):
    production = StubWalkStorage({"unrelated/stale.jpg": b"stale"})
    patch_stale_storage(mocker, production)

    call_command("media_stale", delete=True)

    assert production.deleted == []
    assert "unrelated/stale.jpg" not in capsys.readouterr().out


def test_media_stale_parser_registers_delete_flag():
    parser = MediaStaleCommand().create_parser("manage.py", "media_stale")
    option_strings = {option for action in parser._actions for option in action.option_strings}
    assert "--delete" in option_strings
    assert "--min-age-hours" in option_strings


@pytest.mark.django_db
def test_sync_renditions_rejects_ambiguous_blog_slug(user):
    _site1, site1_root = create_site_root(
        owner=user, hostname="sync-site1.local", slug="sync-site1-root", title="Sync Site 1"
    )
    _site2, site2_root = create_site_root(
        owner=user, hostname="sync-site2.local", slug="sync-site2-root", title="Sync Site 2"
    )
    BlogFactory(owner=user, title="Blog 1", slug="shared-sync-blog", parent=site1_root)
    BlogFactory(owner=user, title="Blog 2", slug="shared-sync-blog", parent=site2_root)

    with pytest.raises(CommandError, match="Multiple blogs found"):
        call_command("sync_renditions", blog_slug="shared-sync-blog")


@pytest.mark.django_db
def test_sync_renditions_rejects_missing_blog_slug():
    with pytest.raises(CommandError, match="No blog found"):
        call_command("sync_renditions", blog_slug="missing-blog")


@pytest.mark.django_db
def test_sync_renditions_with_post_slug_deletes_obsolete_and_builds_missing(mocker, post, image):
    filter_qs = mocker.patch("cast.management.commands.sync_renditions.Rendition.objects.filter")
    filter_qs.return_value.delete.return_value = None
    get_missing = mocker.patch(
        "cast.management.commands.sync_renditions.get_obsolete_and_missing_rendition_strings",
        return_value=([123], {image.id: ["fill-1x1"]}),
    )
    mocker.patch("cast.management.commands.sync_renditions.track", side_effect=lambda items, description=None: items)
    image_get = mocker.patch("cast.management.commands.sync_renditions.Image.objects.get", return_value=image)
    get_renditions = mocker.patch.object(image, "get_renditions")

    call_command("sync_renditions", post_slug=post.slug)

    get_missing.assert_called_once()
    filter_qs.assert_called_once_with(id__in=[123])
    image_get.assert_called_once_with(id=image.id)
    get_renditions.assert_called_once_with("fill-1x1")


@pytest.mark.django_db
def test_sync_renditions_with_unique_blog_slug_syncs_descendants(mocker, blog, post, image):
    filter_qs = mocker.patch("cast.management.commands.sync_renditions.Rendition.objects.filter")
    filter_qs.return_value.delete.return_value = None
    mocker.patch(
        "cast.management.commands.sync_renditions.get_obsolete_and_missing_rendition_strings",
        return_value=([321], {image.id: ["fill-2x2"]}),
    )
    mocker.patch("cast.management.commands.sync_renditions.track", side_effect=lambda items, description=None: items)
    mocker.patch("cast.management.commands.sync_renditions.Image.objects.get", return_value=image)
    get_renditions = mocker.patch.object(image, "get_renditions")

    call_command("sync_renditions", blog_slug=blog.slug)

    filter_qs.assert_called_once_with(id__in=[321])
    get_renditions.assert_called_once_with("fill-2x2")


@pytest.mark.django_db
def test_sync_renditions_without_filters_uses_all_posts(mocker):
    mocked_queryset = mocker.Mock()
    mocked_queryset.prefetch_related.return_value = mocked_queryset
    all_posts = mocker.patch("cast.management.commands.sync_renditions.Post.objects.all", return_value=mocked_queryset)
    mocker.patch("cast.management.commands.sync_renditions.Post.get_all_images_from_queryset", return_value=iter(()))
    mocker.patch(
        "cast.management.commands.sync_renditions.get_obsolete_and_missing_rendition_strings",
        return_value=([], {}),
    )
    mocker.patch("cast.management.commands.sync_renditions.Rendition.objects.filter")
    mocker.patch("cast.management.commands.sync_renditions.track", side_effect=lambda items, description=None: items)

    call_command("sync_renditions")

    all_posts.assert_called_once_with()


def test_media_replace_dry_run_with_yes_warns_and_does_not_write(mocker):
    output = StringIO()
    error_output = StringIO()
    production = StubProductionStorage()
    production.add("foo.jpg", b"old")
    local = StubLocalStorage({"foo.jpg": b"new"})
    mocker.patch(
        "cast.management.commands.media_replace.get_production_and_backup_storage",
        return_value=(production, object()),
    )
    mocker.patch("cast.management.commands.media_replace.FileSystemStorage", return_value=local)

    call_command("media_replace", "foo.jpg", dry_run=True, yes=True, stdout=output, stderr=error_output)

    assert production.deleted == []
    assert production.saved == []
    assert "--yes is ignored in dry-run mode" in error_output.getvalue()


def test_media_replace_dry_run_with_yes_warns_once_for_multiple_files(mocker):
    output = StringIO()
    error_output = StringIO()
    production = StubProductionStorage()
    production.add("foo.jpg", b"old")
    production.add("bar.jpg", b"old")
    local = StubLocalStorage({"foo.jpg": b"new", "bar.jpg": b"new"})
    mocker.patch(
        "cast.management.commands.media_replace.get_production_and_backup_storage",
        return_value=(production, object()),
    )
    mocker.patch("cast.management.commands.media_replace.FileSystemStorage", return_value=local)

    call_command(
        "media_replace",
        "foo.jpg",
        "bar.jpg",
        dry_run=True,
        yes=True,
        stdout=output,
        stderr=error_output,
    )

    assert error_output.getvalue().count("--yes is ignored in dry-run mode") == 1


def test_media_replace_logs_error_and_summary_when_save_fails(mocker):
    output = StringIO()
    error_output = StringIO()
    production = StubProductionStorage()
    local = StubLocalStorage({"foo.jpg": b"new"})
    mocker.patch(
        "cast.management.commands.media_replace.get_production_and_backup_storage",
        return_value=(production, object()),
    )
    mocker.patch("cast.management.commands.media_replace.FileSystemStorage", return_value=local)
    mocker.patch.object(production, "save", side_effect=RuntimeError("boom"))

    with pytest.raises(CommandError, match=r"1 of 1 replacement\(s\) failed"):
        call_command("media_replace", "foo.jpg", yes=True, stdout=output, stderr=error_output)

    assert "error replacing foo.jpg: boom" in error_output.getvalue()
    assert "planned=1 replaced=0 skipped=0 errors=1" in output.getvalue()


def test_media_replace_continues_after_failure_and_exits_nonzero(mocker):
    output = StringIO()
    error_output = StringIO()
    production = StubProductionStorage()
    production.add("bad.jpg", b"old bad")
    production.add("good.jpg", b"old good")
    local = StubLocalStorage({"bad.jpg": b"new bad", "good.jpg": b"new good"})
    mocker.patch(
        "cast.management.commands.media_replace.get_production_and_backup_storage",
        return_value=(production, object()),
    )
    mocker.patch("cast.management.commands.media_replace.FileSystemStorage", return_value=local)
    original_save = production.save

    def fail_final_save_of_bad(path, content):
        if path == "bad.jpg":
            raise RuntimeError("boom")
        return original_save(path, content)

    mocker.patch.object(production, "save", side_effect=fail_final_save_of_bad)

    with pytest.raises(CommandError, match=r"1 of 2 replacement\(s\) failed") as err:
        call_command("media_replace", "bad.jpg", "good.jpg", yes=True, stdout=output, stderr=error_output)

    # the failure is reported through the exit status, not swallowed
    assert err.value.returncode == 1
    # the independent replacement after the failure was still attempted and succeeded
    assert production._files == {"bad.jpg": b"old bad", "good.jpg": b"new good"}
    # both staged objects were cleaned up
    assert len(production.deleted) == 2
    assert all(".django-cast-replace-" in path for path in production.deleted)
    assert "error replacing bad.jpg: boom" in error_output.getvalue()
    assert "replaced: good.jpg" in output.getvalue()
    assert "planned=2 replaced=1 skipped=0 errors=1" in output.getvalue()


def test_media_replace_errors_when_staged_replacement_is_missing(mocker):
    output = StringIO()
    error_output = StringIO()
    production = StubProductionStorage()
    local = StubLocalStorage({"foo.jpg": b"new"})
    mocker.patch(
        "cast.management.commands.media_replace.get_production_and_backup_storage",
        return_value=(production, object()),
    )
    mocker.patch("cast.management.commands.media_replace.FileSystemStorage", return_value=local)
    mocker.patch.object(production, "save", return_value="missing-stage.tmp")

    with pytest.raises(CommandError, match=r"1 of 1 replacement\(s\) failed"):
        call_command("media_replace", "foo.jpg", yes=True, stdout=output, stderr=error_output)

    assert "error replacing foo.jpg: staged replacement missing-stage.tmp was not saved" in error_output.getvalue()
    assert "planned=1 replaced=0 skipped=0 errors=1" in output.getvalue()


def test_media_replace_keeps_existing_file_when_final_save_fails(mocker):
    output = StringIO()
    error_output = StringIO()
    production = StubProductionStorage()
    production.add("foo.jpg", b"old")
    local = StubLocalStorage({"foo.jpg": b"new"})
    mocker.patch(
        "cast.management.commands.media_replace.get_production_and_backup_storage",
        return_value=(production, object()),
    )
    mocker.patch("cast.management.commands.media_replace.FileSystemStorage", return_value=local)
    original_save = production.save

    def fail_final_save(path, content):
        if path == "foo.jpg":
            raise RuntimeError("boom")
        return original_save(path, content)

    mocker.patch.object(production, "save", side_effect=fail_final_save)

    with pytest.raises(CommandError, match=r"1 of 1 replacement\(s\) failed"):
        call_command("media_replace", "foo.jpg", yes=True, stdout=output, stderr=error_output)

    assert production._files["foo.jpg"] == b"old"
    assert "foo.jpg" not in production.deleted
    assert "error replacing foo.jpg: boom" in error_output.getvalue()


def test_media_replace_errors_when_existing_target_would_be_saved_under_different_name(mocker):
    output = StringIO()
    error_output = StringIO()
    production = StubProductionStorage()
    production.add("foo.jpg", b"old")
    local = StubLocalStorage({"foo.jpg": b"new"})
    mocker.patch(
        "cast.management.commands.media_replace.get_production_and_backup_storage",
        return_value=(production, object()),
    )
    mocker.patch("cast.management.commands.media_replace.FileSystemStorage", return_value=local)
    original_save = production.save

    def save_with_generated_name(path, content):
        if path == "foo.jpg":
            return original_save("foo_1.jpg", content)
        return original_save(path, content)

    mocker.patch.object(production, "save", side_effect=save_with_generated_name)

    with pytest.raises(CommandError, match=r"1 of 1 replacement\(s\) failed"):
        call_command("media_replace", "foo.jpg", yes=True, stdout=output, stderr=error_output)

    assert production._files["foo.jpg"] == b"old"
    assert "foo_1.jpg" not in production._files
    assert "storage saved replacement as foo_1.jpg; original foo.jpg was not replaced" in error_output.getvalue()
    assert "planned=1 replaced=0 skipped=0 errors=1" in output.getvalue()


def test_media_replace_warns_when_generated_replacement_cleanup_fails(mocker):
    output = StringIO()
    error_output = StringIO()
    production = StubProductionStorage()
    production.add("foo.jpg", b"old")
    local = StubLocalStorage({"foo.jpg": b"new"})
    mocker.patch(
        "cast.management.commands.media_replace.get_production_and_backup_storage",
        return_value=(production, object()),
    )
    mocker.patch("cast.management.commands.media_replace.FileSystemStorage", return_value=local)
    original_save = production.save
    original_delete = production.delete

    def save_with_generated_name(path, content):
        if path == "foo.jpg":
            return original_save("foo_1.jpg", content)
        return original_save(path, content)

    def fail_generated_delete(path):
        if path == "foo_1.jpg":
            raise RuntimeError("cleanup failed")
        original_delete(path)

    mocker.patch.object(production, "save", side_effect=save_with_generated_name)
    mocker.patch.object(production, "delete", side_effect=fail_generated_delete)

    with pytest.raises(CommandError, match=r"1 of 1 replacement\(s\) failed"):
        call_command("media_replace", "foo.jpg", yes=True, stdout=output, stderr=error_output)

    assert production._files["foo.jpg"] == b"old"
    assert "foo_1.jpg" in production._files
    assert "warning: could not remove generated replacement foo_1.jpg: cleanup failed" in error_output.getvalue()
    assert "storage saved replacement as foo_1.jpg; original foo.jpg was not replaced" in error_output.getvalue()
    assert "planned=1 replaced=0 skipped=0 errors=1" in output.getvalue()


def test_media_replace_errors_when_existing_target_generated_name_is_missing(mocker):
    output = StringIO()
    error_output = StringIO()
    production = StubProductionStorage()
    production.add("foo.jpg", b"old")
    local = StubLocalStorage({"foo.jpg": b"new"})
    mocker.patch(
        "cast.management.commands.media_replace.get_production_and_backup_storage",
        return_value=(production, object()),
    )
    mocker.patch("cast.management.commands.media_replace.FileSystemStorage", return_value=local)
    original_save = production.save

    def save_with_missing_generated_name(path, content):
        if path == "foo.jpg":
            return "foo_1.jpg"
        return original_save(path, content)

    mocker.patch.object(production, "save", side_effect=save_with_missing_generated_name)

    with pytest.raises(CommandError, match=r"1 of 1 replacement\(s\) failed"):
        call_command("media_replace", "foo.jpg", yes=True, stdout=output, stderr=error_output)

    assert production._files["foo.jpg"] == b"old"
    assert "storage saved replacement as foo_1.jpg; original foo.jpg was not replaced" in error_output.getvalue()
    assert "planned=1 replaced=0 skipped=0 errors=1" in output.getvalue()


def test_media_replace_warns_when_missing_target_is_saved_under_different_name(mocker):
    output = StringIO()
    error_output = StringIO()
    production = StubProductionStorage()
    local = StubLocalStorage({"foo.jpg": b"new"})
    mocker.patch(
        "cast.management.commands.media_replace.get_production_and_backup_storage",
        return_value=(production, object()),
    )
    mocker.patch("cast.management.commands.media_replace.FileSystemStorage", return_value=local)
    original_save = production.save

    def save_with_generated_name(path, content):
        if path == "foo.jpg":
            return original_save("foo_1.jpg", content)
        return original_save(path, content)

    mocker.patch.object(production, "save", side_effect=save_with_generated_name)

    call_command("media_replace", "foo.jpg", yes=True, stdout=output, stderr=error_output)

    assert "warning: foo.jpg saved as foo_1.jpg" in error_output.getvalue()
    assert "planned=1 replaced=1 skipped=0 errors=0" in output.getvalue()


def test_media_replace_warns_when_staged_replacement_cleanup_fails(mocker):
    output = StringIO()
    error_output = StringIO()
    production = StubProductionStorage()
    local = StubLocalStorage({"foo.jpg": b"new"})
    mocker.patch(
        "cast.management.commands.media_replace.get_production_and_backup_storage",
        return_value=(production, object()),
    )
    mocker.patch("cast.management.commands.media_replace.FileSystemStorage", return_value=local)
    original_delete = production.delete

    def fail_staged_delete(path):
        if ".django-cast-replace-" in path:
            raise RuntimeError("cleanup failed")
        original_delete(path)

    mocker.patch.object(production, "delete", side_effect=fail_staged_delete)

    call_command("media_replace", "foo.jpg", yes=True, stdout=output, stderr=error_output)

    assert "replaced: foo.jpg" in output.getvalue()
    assert "warning: could not remove staged replacement" in error_output.getvalue()
    assert "cleanup failed" in error_output.getvalue()


def test_recalc_video_posters_continues_after_error_and_reports_summary(mocker):
    output = StringIO()
    error_output = StringIO()
    first = Mock(pk=1)
    first.create_poster.side_effect = RuntimeError("boom")
    second = Mock(pk=2)
    videos = [first, second]
    manager = mocker.Mock()
    manager.all.return_value.order_by.return_value = videos
    mocker.patch("cast.management.commands.recalc_video_posters.Video.objects", manager)
    mocker.patch("cast.management.commands.recalc_video_posters.track", side_effect=lambda iterable, **_: iterable)

    call_command("recalc_video_posters", stdout=output, stderr=error_output)

    first.create_poster.assert_called_once_with()
    first.save.assert_not_called()
    second.create_poster.assert_called_once_with()
    second.save.assert_called_once_with(poster=False)
    assert "error recalculating poster for video 1: boom" in error_output.getvalue()
    assert "processed=2 errors=1" in output.getvalue()


def test_recalc_video_posters_reports_zero_processed(mocker):
    output = StringIO()
    manager = mocker.Mock()
    manager.all.return_value.order_by.return_value = []
    mocker.patch("cast.management.commands.recalc_video_posters.Video.objects", manager)
    mocker.patch("cast.management.commands.recalc_video_posters.track", side_effect=lambda iterable, **_: iterable)

    call_command("recalc_video_posters", stdout=output)

    assert "processed=0 errors=0" in output.getvalue()


def test_styleguide_prefetch_command(settings, mocker):
    styleguide_data, build_styleguide_data, render_styleguide_context, _default_theme = _stub_styleguide_prefetch(
        mocker
    )

    call_command("styleguide_prefetch", theme="plain")
    request = build_styleguide_data.call_args.args[0]
    assert request.path == "/cast/styleguide/"
    render_styleguide_context.assert_called_once_with(styleguide_data, request, "plain")


def test_styleguide_prefetch_command_default_theme(settings, mocker):
    styleguide_data, build_styleguide_data, render_styleguide_context, default_theme = _stub_styleguide_prefetch(
        mocker
    )

    call_command("styleguide_prefetch")
    request = build_styleguide_data.call_args.args[0]
    default_theme.assert_called_once_with()
    render_styleguide_context.assert_called_once_with(styleguide_data, request, "plain")


def test_styleguide_prefetch_command_invalid_theme(settings, mocker):
    mocker.patch(
        "cast.management.commands.styleguide_prefetch.get_template_base_dir_choices",
        return_value=[("plain", "Plain")],
    )
    with pytest.raises(CommandError):
        call_command("styleguide_prefetch", theme="not-a-theme")


def test_styleguide_prefetch_command_with_renditions(settings, mocker):
    settings.CAST_STYLEGUIDE_GENERATE_RENDITIONS = False
    styleguide_data, build_styleguide_data, render_styleguide_context, _default_theme = _stub_styleguide_prefetch(
        mocker
    )

    call_command("styleguide_prefetch", theme="plain", with_renditions=True)
    request = build_styleguide_data.call_args.args[0]
    render_styleguide_context.assert_called_once_with(styleguide_data, request, "plain")
    assert settings.CAST_STYLEGUIDE_GENERATE_RENDITIONS is True


def test_generate_transcripts_requires_targets():
    with pytest.raises(CommandError, match="Provide at least one --episode-id or --audio-id"):
        call_command("generate_transcripts")


def test_generate_transcripts_get_existing_transcript_handles_missing_relation():
    class MissingTranscriptAudio:
        @property
        def transcript(self):
            raise ObjectDoesNotExist

    from cast.management.commands.generate_transcripts import Command

    assert Command._get_existing_transcript(audio=MissingTranscriptAudio()) is None


def test_generate_transcripts_rejects_unknown_episode_id(mocker):
    queryset = mocker.Mock()
    queryset.select_related.return_value = queryset
    queryset.order_by.return_value = []
    mocker.patch("cast.management.commands.generate_transcripts.Episode.objects.filter", return_value=queryset)

    with pytest.raises(CommandError, match="Unknown episode id"):
        call_command("generate_transcripts", "--episode-id", "7")


@pytest.mark.django_db
def test_generate_transcripts_rejects_unknown_audio_id():
    with pytest.raises(CommandError, match="Unknown audio id"):
        call_command("generate_transcripts", "--audio-id", "999999")


@pytest.mark.django_db
def test_generate_transcripts_rejects_episode_without_audio(mocker):
    queryset = mocker.Mock()
    queryset.select_related.return_value = queryset
    queryset.order_by.return_value = [SimpleNamespace(pk=1, podcast_audio_id=None)]
    mocker.patch("cast.management.commands.generate_transcripts.Episode.objects.filter", return_value=queryset)

    with pytest.raises(CommandError, match="has no podcast audio"):
        call_command("generate_transcripts", "--episode-id", "1")


@pytest.mark.django_db
def test_generate_transcripts_skips_complete_transcript(mocker, audio):
    create_transcript(
        audio=audio,
        podlove={"transcripts": [{"text": "existing"}]},
        vtt="WEBVTT\n\n00:00:00.000 --> 00:00:00.500\nexisting\n",
        dote={
            "lines": [
                {
                    "startTime": "00:00:00,000",
                    "endTime": "00:00:00,500",
                    "speakerDesignation": "",
                    "text": "existing",
                }
            ]
        },
    )
    service_cls = mocker.patch("cast.management.commands.generate_transcripts.VoxhelmTranscriptService")
    output = StringIO()

    call_command("generate_transcripts", "--audio-id", str(audio.pk), stdout=output)

    assert "skipped audio=" in output.getvalue()
    assert "processed=1 created=0 updated=0 skipped=1 errors=0" in output.getvalue()
    service_cls.return_value.generate_for_audio.assert_not_called()


@pytest.mark.django_db
def test_generate_transcripts_does_not_skip_empty_transcript(mocker, audio):
    transcript = create_transcript(
        audio=audio,
        podlove={"transcripts": []},
        vtt="WEBVTT\n\n",
        dote={"lines": []},
    )
    service = mocker.Mock()
    service.generate_for_audio.return_value = TranscriptGenerationResult(
        transcript=transcript,
        created=False,
        job_id="job-789",
        source_url="https://media.example.com/episode.m4a",
    )
    mocker.patch(
        "cast.management.commands.generate_transcripts.VoxhelmTranscriptService",
        return_value=service,
    )
    output = StringIO()

    call_command("generate_transcripts", "--audio-id", str(audio.pk), stdout=output)

    assert "skipped audio=" not in output.getvalue()
    assert "updated audio=" in output.getvalue()
    service.generate_for_audio.assert_called_once_with(audio, task_ref=f"cast-audio-{audio.pk}", episode=None)


@pytest.mark.django_db
def test_generate_transcripts_calls_service_for_episode(mocker, audio):
    transcript = create_transcript(audio=audio)
    queryset = mocker.Mock()
    queryset.select_related.return_value = queryset
    episode = SimpleNamespace(pk=7, podcast_audio_id=audio.pk, podcast_audio=audio)
    queryset.order_by.return_value = [episode]
    mocker.patch("cast.management.commands.generate_transcripts.Episode.objects.filter", return_value=queryset)
    service = mocker.Mock()
    service.generate_for_audio.return_value = TranscriptGenerationResult(
        transcript=transcript,
        created=True,
        job_id="job-123",
        source_url="https://media.example.com/episode.m4a",
    )
    service_cls = mocker.patch(
        "cast.management.commands.generate_transcripts.VoxhelmTranscriptService",
        return_value=service,
    )
    output = StringIO()

    call_command("generate_transcripts", "--episode-id", "7", stdout=output)

    assert "created audio=" in output.getvalue()
    assert "job=job-123" in output.getvalue()
    assert "processed=1 created=1 updated=0 skipped=0 errors=0" in output.getvalue()
    service_cls.assert_called_once_with()
    service.generate_for_audio.assert_called_once()
    called_audio = service.generate_for_audio.call_args.args[0]
    assert called_audio.pk == audio.pk
    assert service.generate_for_audio.call_args.kwargs["episode"] == episode


@pytest.mark.django_db
def test_generate_transcripts_force_updates_and_uses_unique_task_ref(mocker, audio):
    transcript = create_transcript(audio=audio)
    service = mocker.Mock()
    service.generate_for_audio.return_value = TranscriptGenerationResult(
        transcript=transcript,
        created=False,
        job_id="job-456",
        source_url="https://media.example.com/episode.m4a",
    )
    mocker.patch(
        "cast.management.commands.generate_transcripts.VoxhelmTranscriptService",
        return_value=service,
    )
    output = StringIO()

    call_command("generate_transcripts", "--audio-id", str(audio.pk), "--force", stdout=output)

    assert "updated audio=" in output.getvalue()
    task_ref = service.generate_for_audio.call_args.kwargs["task_ref"]
    assert task_ref.startswith(f"cast-audio-{audio.pk}-")


@pytest.mark.django_db
def test_generate_transcripts_reports_errors_and_raises(mocker, audio):
    service = mocker.Mock()
    service.generate_for_audio.side_effect = VoxhelmError("backend exploded")
    mocker.patch(
        "cast.management.commands.generate_transcripts.VoxhelmTranscriptService",
        return_value=service,
    )
    output = StringIO()
    error_output = StringIO()

    with pytest.raises(CommandError, match="1 transcript generations failed"):
        call_command("generate_transcripts", "--audio-id", str(audio.pk), stdout=output, stderr=error_output)

    assert "error audio=" in error_output.getvalue()
    assert "processed=1 created=0 updated=0 skipped=0 errors=1" in output.getvalue()


def test_generate_transcripts_resolve_targets_skips_duplicates_and_unsaved(mocker):
    from cast.management.commands.generate_transcripts import Command

    shared_audio = SimpleNamespace(pk=5)
    episode_queryset = mocker.Mock()
    episode_queryset.select_related.return_value = episode_queryset
    episode_queryset.order_by.return_value = [SimpleNamespace(pk=1, podcast_audio_id=5, podcast_audio=shared_audio)]
    direct_queryset = mocker.Mock()
    direct_queryset.select_related.return_value = direct_queryset
    direct_queryset.order_by.return_value = [shared_audio, SimpleNamespace(pk=None)]
    mocker.patch("cast.management.commands.generate_transcripts.Episode.objects.filter", return_value=episode_queryset)
    mocker.patch("cast.management.commands.generate_transcripts.Audio.objects.filter", return_value=direct_queryset)

    targets = Command()._resolve_targets(episode_ids=[1], audio_ids=[5])

    assert [target.audio for target in targets] == [shared_audio]
    assert targets[0].episode.pk == 1


def test_generate_transcripts_resolve_targets_skips_unsaved_episode_audio(mocker):
    from cast.management.commands.generate_transcripts import Command

    episode_queryset = mocker.Mock()
    episode_queryset.select_related.return_value = episode_queryset
    episode_queryset.order_by.return_value = [
        SimpleNamespace(pk=1, podcast_audio_id=7, podcast_audio=SimpleNamespace(pk=None))
    ]
    direct_queryset = mocker.Mock()
    direct_queryset.select_related.return_value = direct_queryset
    direct_queryset.order_by.return_value = []
    mocker.patch("cast.management.commands.generate_transcripts.Episode.objects.filter", return_value=episode_queryset)
    mocker.patch("cast.management.commands.generate_transcripts.Audio.objects.filter", return_value=direct_queryset)

    assert Command()._resolve_targets(episode_ids=[1], audio_ids=[]) == []
