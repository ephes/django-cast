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
    def __init__(self):
        self._files = []

    def exists(self, path):
        return path in self._files

    def save(self, name, _content):
        self._files.append(name)

    @staticmethod
    def open(name, _mode):
        class StubFile:
            def __init__(self, file_name):
                self.name = file_name

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

        return StubFile(name)

    def listdir(self, _path):
        return [], self._files


@pytest.fixture
def stub_storages(settings):
    storage_stub = {"BACKEND": "tests.management_command_test.StubStorage"}
    settings.STORAGES = {"production": storage_stub, "backup": storage_stub}
    return storages


def test_media_backup_new_file(capsys, stub_storages):
    production, backup = stub_storages["production"], stub_storages["backup"]

    # given there's a new file added to production
    production.save("foobar.jpg", BytesIO(b"foobar"))

    # when we run the backup command
    call_command("media_backup")

    # then the file should be added to the backup
    assert backup.exists("foobar.jpg")
