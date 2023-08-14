from collections.abc import Generator
from contextlib import contextmanager
from io import BytesIO

import pytest
from django.core.files.storage import storages
from django.core.management import call_command
from django.core.management.base import CommandError


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
        self._files: dict[str, str] = {}

    def exists(self, path: str) -> bool:
        return path in self._files

    def save(self, name: str, content: str) -> None:
        self._files[name] = content

    def listdir(self, _path: str) -> tuple[list, dict[str, str]]:
        return [], self._files

    @contextmanager
    def open(self, name: str, _mode: str) -> Generator[str, None, None]:
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
    production.save("foobar.jpg", BytesIO(b"foobar"))

    # when we run the backup command
    call_command("media_backup")

    # then the file should be added to the backup
    assert backup.exists("foobar.jpg")
