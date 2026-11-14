"""Owned staging, same-host writers, and delayed source reads."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from cast.management.commands.storage_backend import copy_missing_file, refresh_existing_file
from tests.management_command_test import StubOverwriteStorage


def test_missing_copy_stages_before_a_partial_save_and_retry_recovers(mocker):
    source, target = StubOverwriteStorage({"media": b"complete source"}), StubOverwriteStorage()
    original_save = target.save
    attempted = []

    def fail(name, content):
        attempted.append(name)
        target._files[name] = content.read(2)
        raise OSError("write interrupted")

    mocker.patch.object(target, "save", side_effect=fail)
    with pytest.raises(OSError, match="write interrupted"):
        copy_missing_file(source, target, "media")
    assert attempted[0] != "media"
    assert target._files == {}
    mocker.patch.object(target, "save", side_effect=original_save)
    copy_missing_file(source, target, "media")
    assert target._files == source._files


def test_missing_final_write_failure_is_cleaned_for_retry(mocker):
    source, target = StubOverwriteStorage({"media": b"complete source"}), StubOverwriteStorage()
    original_save = target.save

    def save(name, content):
        if name == "media":
            target._files[name] = content.read(2)
            raise OSError("final interrupted")
        return original_save(name, content)

    mocker.patch.object(target, "save", side_effect=save)
    with pytest.raises(OSError, match="final interrupted"):
        copy_missing_file(source, target, "media")
    assert target._files == {}
    mocker.patch.object(target, "save", side_effect=original_save)
    copy_missing_file(source, target, "media")
    assert target._files == source._files


def test_missing_copy_keeps_competitor_published_during_staging(mocker):
    source, target = StubOverwriteStorage({"media": b"source"}), StubOverwriteStorage()
    original_save = target.save

    def save(name, content):
        if name != "media":
            target._files["media"] = b"complete competitor"
        return original_save(name, content)

    mocker.patch.object(target, "save", side_effect=save)
    with pytest.raises(RuntimeError, match="conflict"):
        copy_missing_file(source, target, "media")
    assert target._files == {"media": b"complete competitor"}


@pytest.mark.parametrize("change", ["source", "target"])
def test_refresh_rechecks_generations_after_slow_staging(mocker, change):
    source, target = StubOverwriteStorage({"media": b"generation A"}), StubOverwriteStorage({"media": b"old target"})
    original_save = target.save

    def save(name, content):
        result = original_save(name, content)
        if name != "media":
            (source if change == "source" else target)._files["media"] = b"generation B"
        return result

    mocker.patch.object(target, "save", side_effect=save)
    with pytest.raises(RuntimeError, match="conflict"):
        refresh_existing_file(source, target, "media")
    assert target._files == {"media": b"generation B" if change == "target" else b"old target"}


def test_parallel_refresh_refuses_busy_writer_and_stale_source(mocker):
    source, target = StubOverwriteStorage({"media": b"generation A"}), StubOverwriteStorage({"media": b"old"})
    original_save = target.save
    staging, resume = Event(), Event()

    def save(name, content):
        result = original_save(name, content)
        if name != "media":
            staging.set()
            assert resume.wait(5)
        return result

    mocker.patch.object(target, "save", side_effect=save)
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(refresh_existing_file, source, target, "media")
        try:
            assert staging.wait(5)
            source._files["media"] = b"generation B"
            with pytest.raises(RuntimeError, match="conflict"):
                refresh_existing_file(source, target, "media")
        finally:
            resume.set()
        with pytest.raises(RuntimeError, match="conflict"):
            first.result(5)
    mocker.patch.object(target, "save", side_effect=original_save)
    refresh_existing_file(source, target, "media")
    assert target._files == {"media": b"generation B"}


@pytest.mark.parametrize("missing", [False, True])
def test_changed_target_presence_refuses_before_staging(missing):
    source = StubOverwriteStorage({"media": b"source"})
    target = StubOverwriteStorage({"media": b"competitor"} if missing else {})
    operation = copy_missing_file if missing else refresh_existing_file
    with pytest.raises(RuntimeError, match="conflict"):
        operation(source, target, "media")
    assert target.saved == []
    assert target.deleted == []


def test_staging_collision_keeps_preexisting_object(mocker):
    source = StubOverwriteStorage({"media": b"source"})
    target = StubOverwriteStorage({"collision.tmp": b"unrelated"})
    mocker.patch("cast.management.commands.storage_backend.temporary_refresh_path", return_value="collision.tmp")
    with pytest.raises(RuntimeError, match="staging key already exists"):
        copy_missing_file(source, target, "media")
    assert target._files == {"collision.tmp": b"unrelated"}
    assert target.deleted == []


def test_publication_lock_fences_an_independent_process():
    import subprocess
    import sys

    from cast.management.commands.storage_backend import media_publication_lock

    script = "from cast.management.commands.storage_backend import media_publication_lock\nwith media_publication_lock():\n    print('acquired')\n"
    with media_publication_lock():
        refused = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=10)
        assert refused.returncode != 0
        assert "publication conflict" in refused.stderr
    accepted = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=10)
    assert accepted.returncode == 0, accepted.stderr
    assert accepted.stdout.strip() == "acquired"


def test_default_sync_cannot_call_an_active_partial_write_unchanged():
    from cast.management.commands.storage_backend import media_publication_lock, sync_media_files

    source, target = StubOverwriteStorage({"media": b"complete"}), StubOverwriteStorage({"media": b"part"})
    with media_publication_lock():
        result = sync_media_files(source, target)
    assert result.errors == 1
    assert result.unchanged == result.copied == result.refreshed == 0
    assert target._files == {"media": b"part"}


def test_publication_lock_refuses_a_shared_or_foreign_directory(tmp_path, monkeypatch):
    import os

    from cast.management.commands import storage_backend as media

    monkeypatch.setattr(media.tempfile, "gettempdir", lambda: str(tmp_path))
    directory = tmp_path / f"django-cast-media-sync-{media.publication_identity()}"
    directory.mkdir(mode=0o777)
    os.chmod(directory, 0o777)
    with pytest.raises(RuntimeError, match="not private"):
        with media.media_publication_lock():
            pass
    os.chmod(directory, 0o700)
    with media.media_publication_lock():
        pass
    assert (directory / "publication.lock").exists()


def test_publication_lock_does_not_follow_a_planted_symlink(tmp_path, monkeypatch):
    import os

    from cast.management.commands import storage_backend as media

    monkeypatch.setattr(media.tempfile, "gettempdir", lambda: str(tmp_path))
    directory = tmp_path / f"django-cast-media-sync-{media.publication_identity()}"
    directory.mkdir(mode=0o700)
    victim = tmp_path / "victim"
    victim.write_bytes(b"keep")
    (directory / "publication.lock").symlink_to(victim)
    with pytest.raises(OSError):
        with media.media_publication_lock():
            pass
    assert victim.read_bytes() == b"keep"
    assert os.path.islink(directory / "publication.lock")


def test_publication_identity_without_a_posix_uid_uses_the_login_name(monkeypatch):
    import hashlib

    from cast.management.commands import storage_backend as media

    monkeypatch.delattr(media.os, "getuid")
    monkeypatch.setattr(media.getpass, "getuser", lambda: "synthetic")
    assert media.publication_identity() == hashlib.sha256(b"synthetic").hexdigest()
