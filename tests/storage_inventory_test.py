"""Untrusted storage listings stay inside a finite portable inventory."""

from io import StringIO

import pytest
from django.core.management import CommandError, call_command

from cast.utils import storage_walk_paths
from tests.management_command_test import StubOverwriteStorage


@pytest.mark.parametrize(
    "name", ["..", ".", "", "../escape", "/absolute", "a/b", r"a\b", r"C:\escape", "C:escape", "a\x00b"]
)
@pytest.mark.parametrize("kind", ["directory", "file"])
def test_listing_refuses_unsafe_components_before_copy(mocker, name, kind):
    source, target = StubOverwriteStorage(), StubOverwriteStorage()
    listing = ([name], ["healthy"]) if kind == "directory" else ([], ["healthy", name])
    listing_mock = mocker.patch.object(source, "listdir", return_value=listing)
    open_mock = mocker.patch.object(source, "open")
    save_mock = mocker.patch.object(target, "save")
    mocker.patch(
        "cast.management.commands.media_backup.get_production_and_backup_storage", return_value=(source, target)
    )
    errors = StringIO()
    with pytest.raises(CommandError, match="could not be backed up"):
        call_command("media_backup", stdout=StringIO(), stderr=errors)
    assert "inventory" in errors.getvalue()
    listing_mock.assert_called_once_with("")
    open_mock.assert_not_called()
    save_mock.assert_not_called()


def test_unicode_hierarchy_and_requested_prefix(mocker):
    source = StubOverwriteStorage()
    mocker.patch.object(source, "listdir", side_effect=[(["日本語"], ["é.jpg"]), ([], ["音声.mp3"])])
    assert set(storage_walk_paths(source, "album")) == {"album/é.jpg", "album/日本語/音声.mp3"}


@pytest.mark.parametrize("prefix", ["../outside", "/absolute", r"a\b", "a//b"])
def test_invalid_start_prefix_does_not_list(mocker, prefix):
    storage = StubOverwriteStorage()
    listing = mocker.patch.object(storage, "listdir")
    with pytest.raises(ValueError):
        list(storage_walk_paths(storage, prefix))
    listing.assert_not_called()


@pytest.mark.parametrize("mode", ["depth", "directories", "files", "repeat"])
def test_inventory_work_has_finite_limits(mocker, mode):
    from cast import utils

    storage = StubOverwriteStorage()
    mocker.patch.object(utils, "MAX_STORAGE_DEPTH", 3, create=True)
    mocker.patch.object(utils, "MAX_STORAGE_DIRECTORIES", 4, create=True)
    mocker.patch.object(utils, "MAX_STORAGE_FILES", 3, create=True)
    listings = {
        "depth": lambda path: (["next"], []),
        "directories": lambda path: (["a", "b", "c", "d"], []),
        "files": lambda path: ([], ["a", "b", "c", "d"]),
        "repeat": lambda path: (["same", "same"], []),
    }
    listing = mocker.patch.object(storage, "listdir", side_effect=listings[mode])
    with pytest.raises(ValueError, match="inventory"):
        list(storage_walk_paths(storage))
    assert listing.call_count <= 4


def test_inventory_failure_retains_completed_paths_and_reports_incomplete(mocker):
    source = StubOverwriteStorage({"healthy": b"ok"})
    target = StubOverwriteStorage()
    mocker.patch.object(source, "listdir", side_effect=[(["bad"], ["healthy"]), ([".."], [])])
    mocker.patch(
        "cast.management.commands.media_restore.get_production_and_backup_storage", return_value=(target, source)
    )
    output = StringIO()
    with pytest.raises(CommandError):
        call_command("media_restore", stdout=output, stderr=StringIO())
    assert target._files == {"healthy": b"ok"}
    assert "copied=1 refreshed=0 unchanged=0 errors=1" in output.getvalue()
