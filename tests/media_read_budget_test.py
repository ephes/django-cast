"""Content comparison is bounded across source and target streams."""

from contextlib import contextmanager
from io import BytesIO

import pytest

from cast.management.commands import storage_backend as media
from tests.management_command_test import StubOverwriteStorage


def limits(mocker, *, size=6, seconds=10):
    mocker.patch.object(media, "MAX_MEDIA_READ_BYTES", size, create=True)
    mocker.patch.object(media, "MAX_MEDIA_READ_SECONDS", seconds, create=True)


@pytest.mark.parametrize("target_bytes", [b"abc", b"xyz"])
def test_comparison_accepts_exact_combined_boundary(mocker, target_bytes):
    limits(mocker)
    source = StubOverwriteStorage({"media": b"abc"})
    target = StubOverwriteStorage({"media": target_bytes})
    assert media.content_differs(source, target, "media") == (target_bytes != b"abc")


def test_comparison_charges_both_streams_and_closes_on_refusal(mocker):
    limits(mocker, size=5)
    opened = []

    class StreamStorage(StubOverwriteStorage):
        @contextmanager
        def open(self, name, mode):
            with BytesIO(self._files[name]) as file:
                opened.append(file)
                yield file

    source, target = StreamStorage({"media": b"abc"}), StreamStorage({"media": b"xyz"})
    with pytest.raises(RuntimeError, match="byte budget"):
        media.content_differs(source, target, "media")
    assert len(opened) == 2
    assert all(file.closed for file in opened)


def test_growing_stream_has_bounded_reads_and_no_save(mocker):
    limits(mocker, size=7)
    reads = []
    closed = []

    class GrowingStorage(StubOverwriteStorage):
        @contextmanager
        def open(self, name, mode):
            class Stream:
                def read(self, size):
                    reads.append(size)
                    assert len(reads) < 10  # also catches the unsafe implementation
                    return b"x" * size

            try:
                yield Stream()
            finally:
                closed.append(True)

    source = GrowingStorage({"media": b"old"})
    target = StubOverwriteStorage({"media": b"old"})
    result = media.sync_media_files(source, target, refresh_changed=True)
    assert result.errors == 1
    assert sum(reads) <= 8
    assert closed == [True]
    assert target.saved == []
    assert target._files == {"media": b"old"}


def test_slow_read_refuses_before_refresh_save_and_closes(mocker):
    limits(mocker)
    now, closed = [0.0], []
    mocker.patch.object(media, "monotonic", side_effect=lambda: now[0], create=True)

    class SlowStorage(StubOverwriteStorage):
        @contextmanager
        def open(self, name, mode):
            class Stream(BytesIO):
                def read(self, size):
                    now[0] += 11
                    return super().read(size)

            with Stream(self._files[name]) as stream:
                try:
                    yield stream
                finally:
                    closed.append(True)

    source, target = SlowStorage({"media": b"abc"}), StubOverwriteStorage({"media": b"xyz"})
    result = media.sync_media_files(source, target, refresh_changed=True)
    assert result.errors == 1
    assert target.saved == []
    assert closed == [True]


def test_deadline_is_shared_by_source_and_target(mocker):
    limits(mocker)
    now = [0.0]
    mocker.patch.object(media, "monotonic", side_effect=lambda: now[0], create=True)

    class DelayedStorage(StubOverwriteStorage):
        @contextmanager
        def open(self, name, mode):
            now[0] += 6
            with super().open(name, mode) as stream:
                yield stream

    with pytest.raises(RuntimeError, match="time budget"):
        media.content_differs(DelayedStorage({"media": b"abc"}), DelayedStorage({"media": b"xyz"}), "media")
