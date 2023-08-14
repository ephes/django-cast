from collections.abc import Iterator
from contextlib import contextmanager
from io import BytesIO

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
    return int("".join(django.get_version().split(".")[:2]))


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
