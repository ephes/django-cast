from collections.abc import Iterator
from contextlib import contextmanager
from io import BytesIO
from io import StringIO

import django
import pytest

try:
    from django.core.files.storage import storages
except ImportError:
    pass
from django.core.management import CommandError, call_command

try:
    from cast.management.commands.media_backup import Command as MediaBackupCommand
except ImportError:
    pass


def get_comparable_django_version():
    django_version = "".join(django.get_version().split(".")[:2])
    try:
        return int(django_version)
    except ValueError:
        # pre-release probably
        return int(django_version.split("a")[0])


pytestmark = pytest.mark.skipif(
    get_comparable_django_version() < 42,
    reason="Django version >= 4.2 is required",
)


def test_media_backup_without_storages(settings):
    settings.STORAGES = {}
    with pytest.raises(CommandError) as err:
        call_command("media_backup")
    assert str(err.value) == "production or backup storage not configured"


def test_media_backup_with_wrong_django_version(mocker):
    mocker.patch("cast.management.commands.storage_backend.DJANGO_VERSION_VALID", False)
    with pytest.raises(CommandError) as err:
        call_command("media_backup")
    assert str(err.value) == "Django version >= 4.2 is required"


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


class StubLocalStorage:
    def __init__(self, files: dict[str, bytes]) -> None:
        self._files = files

    def exists(self, path: str) -> bool:
        return path in self._files

    @contextmanager
    def open(self, name: str, _mode: str) -> Iterator[BytesIO]:
        yield BytesIO(self._files[name])


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

    assert production.deleted == ["foo.jpg"]
    assert production.saved == ["foo.jpg"]
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

    assert production.deleted == []
    assert production.saved == ["foo.jpg"]


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

    call_command("media_replace", "foo.jpg", yes=True, stdout=output, stderr=error_output)

    assert "error replacing foo.jpg: boom" in error_output.getvalue()
    assert "planned=1 replaced=0 skipped=0 errors=1" in output.getvalue()


def test_media_replace_logs_data_loss_risk_when_existing_file_delete_then_save_fails(mocker):
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
    mocker.patch.object(production, "save", side_effect=RuntimeError("boom"))

    call_command("media_replace", "foo.jpg", yes=True, stdout=output, stderr=error_output)

    assert production.deleted == ["foo.jpg"]
    assert "error replacing foo.jpg: boom" in error_output.getvalue()
    assert "may have been deleted before save failed" in error_output.getvalue()


def test_media_replace_warns_when_storage_returns_different_saved_name(mocker):
    output = StringIO()
    error_output = StringIO()
    production = StubProductionStorage()
    local = StubLocalStorage({"foo.jpg": b"new"})
    mocker.patch(
        "cast.management.commands.media_replace.get_production_and_backup_storage",
        return_value=(production, object()),
    )
    mocker.patch("cast.management.commands.media_replace.FileSystemStorage", return_value=local)
    mocker.patch.object(production, "save", return_value="foo_1.jpg")

    call_command("media_replace", "foo.jpg", yes=True, stdout=output, stderr=error_output)

    assert "warning: foo.jpg saved as foo_1.jpg" in error_output.getvalue()


@pytest.mark.slow
def test_styleguide_prefetch_command(settings, db):
    settings.CAST_STYLEGUIDE_REMOTE_MEDIA = False
    call_command("styleguide_prefetch", theme="plain")


@pytest.mark.slow
def test_styleguide_prefetch_command_default_theme(settings, db):
    settings.CAST_STYLEGUIDE_REMOTE_MEDIA = False
    call_command("styleguide_prefetch")


@pytest.mark.slow
def test_styleguide_prefetch_command_invalid_theme(settings, db):
    settings.CAST_STYLEGUIDE_REMOTE_MEDIA = False
    with pytest.raises(CommandError):
        call_command("styleguide_prefetch", theme="not-a-theme")


@pytest.mark.slow
def test_styleguide_prefetch_command_with_renditions(settings, db):
    settings.CAST_STYLEGUIDE_REMOTE_MEDIA = False
    settings.CAST_STYLEGUIDE_GENERATE_RENDITIONS = False
    call_command("styleguide_prefetch", theme="plain", with_renditions=True)
    assert settings.CAST_STYLEGUIDE_GENERATE_RENDITIONS is True
