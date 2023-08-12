from io import BytesIO

import pytest
from django.core.files.storage import storages
from django.core.management import call_command


def test_media_backup_without_storages(capsys, settings):
    settings.STORAGES = {}
    call_command("media_backup")
    captured = capsys.readouterr()
    assert captured.out == "production or backup storage not configured\n"


def test_media_backup_without_django_version(capsys, settings, mocker):
    settings.STORAGES = {}
    mocker.patch("cast.management.commands.media_backup.DJANGO_VERSION_VALID", False)
    call_command("media_backup")
    captured = capsys.readouterr()
    assert captured.out == "Django version >= 4.2 is required\n"


class StubStorage:
    _files: list[str] = []
    _exists: list[str] = []

    def exists(self, path):
        return path in self._exists

    def save(self, name, _content):
        print("save called: ", name, _content)
        self._exists.append(name)

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

    def listdir(self, path):
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
