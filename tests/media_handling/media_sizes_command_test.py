"""Read-only media reports against synthetic storage, without external services."""

from pathlib import Path

import pytest
from django.core.files.storage import Storage
from django.core.management import call_command

from cast.management.commands import media_sizes

MIB = 2**20


@pytest.mark.parametrize(
    "paths,expected",
    [
        ({}, ["video usage: 0.0", "image usage: 0.0", "misc  usage: 0.0", "total usage: 0.0"]),
        (
            {
                "film.MOV": MIB,
                "clip.Mp4": MIB // 2,
                "cover.JPG": MIB,
                "detail.JpEg": MIB // 2,
                "icon.PNG": MIB // 2,
                "notes.txt": MIB // 4,
                "other.webp": MIB // 4,
            },
            ["video usage: 1.5", "image usage: 2.0", "misc  usage: 0.5", "total usage: 4.0"],
        ),
    ],
)
def test_show_usage_reports_exact_categories(paths, expected, capsys):
    media_sizes.Command.show_usage(paths)
    assert capsys.readouterr().out.splitlines() == expected


@pytest.fixture
def synthetic_storage(mocker):
    production = mocker.create_autospec(Storage, instance=True)
    backup = mocker.create_autospec(Storage, instance=True)
    nested = str(Path("nested"))
    paths = {str(Path(nested) / "clip.MP4"): MIB, "cover.JPEG": MIB // 2, "notes.bin": MIB // 4}
    tree = {"": (["nested"], ["cover.JPEG", "notes.bin"]), nested: ([], ["clip.MP4"])}
    production.listdir.side_effect = tree.__getitem__
    production.size.side_effect = paths.__getitem__
    backup.listdir.side_effect = AssertionError("Backup must not be traversed")
    backup.size.side_effect = AssertionError("Backup must not be sized")
    resolver = mocker.patch.object(media_sizes, "get_production_and_backup_storage", return_value=(production, backup))
    return production, backup, resolver, paths


def assert_read_only(production, backup):
    for store in (production, backup):
        store.open.assert_not_called()
        store.save.assert_not_called()
        store.delete.assert_not_called()
    backup.listdir.assert_not_called()
    backup.size.assert_not_called()


def test_nested_storage_sizes_are_read_exactly_once(synthetic_storage, capsys):
    production, backup, resolver, paths = synthetic_storage
    assert media_sizes.Command.get_paths_with_sizes_for(production) == paths
    assert sorted(call.args[0] for call in production.size.call_args_list) == sorted(paths)
    assert [call.args[0] for call in production.listdir.call_args_list] == ["", str(Path("nested"))]
    assert set(capsys.readouterr().out.splitlines()) == {f"{path} {size / MIB}" for path, size in paths.items()}
    resolver.assert_not_called()
    assert_read_only(production, backup)


@pytest.mark.parametrize("empty", [False, True])
def test_command_reports_only_production(synthetic_storage, capsys, empty):
    production, backup, resolver, paths = synthetic_storage
    if empty:
        production.listdir.side_effect = None
        production.listdir.return_value = ([], [])
    call_command("media_sizes")
    resolver.assert_called_once_with()
    expected = (
        ["video usage: 0.0", "image usage: 0.0", "misc  usage: 0.0", "total usage: 0.0"]
        if empty
        else ["video usage: 1.0", "image usage: 0.5", "misc  usage: 0.25", "total usage: 1.75"]
    )
    assert capsys.readouterr().out.splitlines()[-4:] == expected
    assert production.size.call_count == (0 if empty else len(paths))
    assert_read_only(production, backup)


@pytest.mark.parametrize("failure", ["listdir", "size"])
def test_command_propagates_storage_errors(synthetic_storage, failure):
    production, backup, resolver, _paths = synthetic_storage
    getattr(production, failure).side_effect = OSError("synthetic storage unavailable")
    with pytest.raises(OSError, match="synthetic storage unavailable"):
        call_command("media_sizes")
    resolver.assert_called_once_with()
    assert_read_only(production, backup)
