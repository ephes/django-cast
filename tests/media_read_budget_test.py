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


def test_comparison_budgets_each_stream_and_closes_on_refusal(mocker):
    # Each full read has its own byte ceiling: three bytes exceed two.
    limits(mocker, size=2)
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
    assert len(opened) == 1
    assert all(file.closed for file in opened)
    limits(mocker, size=3)
    assert media.content_differs(source, target, "media")
    assert len(opened) == 3 and all(file.closed for file in opened)


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


def test_each_read_has_its_own_deadline(mocker):
    limits(mocker)
    now = [0.0]
    mocker.patch.object(media, "monotonic", side_effect=lambda: now[0], create=True)

    class DelayedStorage(StubOverwriteStorage):
        @contextmanager
        def open(self, name, mode):
            now[0] += 6
            with super().open(name, mode) as stream:
                yield stream

    # Six seconds per open: the second read is not charged with the first one's time.
    assert media.content_differs(DelayedStorage({"media": b"abc"}), DelayedStorage({"media": b"xyz"}), "media")


def test_deadline_scales_with_reported_object_size(mocker):
    limits(mocker, size=1000, seconds=10)
    mocker.patch.object(media, "MIN_MEDIA_READ_BYTES_PER_SECOND", 1, create=True)
    mocker.patch.object(media, "monotonic", return_value=100.0, create=True)
    storage = StubOverwriteStorage({"big": b"x" * 50, "small": b"x"})
    assert media.MediaReadBudget.for_object(storage, "big").deadline == 150.0
    assert media.MediaReadBudget.for_object(storage, "small").deadline == 110.0

    class Unsized(StubOverwriteStorage):
        def size(self, name):
            raise NotImplementedError

    assert media.MediaReadBudget.for_object(Unsized({"x": b""}), "x").deadline == 110.0

    # A size beyond the byte ceiling cannot buy more time than the ceiling needs.
    mocker.patch.object(media, "MAX_MEDIA_READ_BYTES", 60, create=True)

    class Huge(StubOverwriteStorage):
        def size(self, name):
            return 10**18

    assert media.MediaReadBudget.for_object(Huge({"x": b""}), "x").deadline == 160.0


def test_staging_upload_time_is_not_charged_to_verification_reads(mocker):
    limits(mocker, seconds=10)
    now = [0.0]
    mocker.patch.object(media, "monotonic", side_effect=lambda: now[0], create=True)

    class SlowSaveStorage(StubOverwriteStorage):
        def save(self, name, content):
            now[0] += 60  # Far beyond one read deadline.
            return super().save(name, content)

    source = StubOverwriteStorage({"media": b"abc"})
    target = SlowSaveStorage()
    result = media.sync_media_files(source, target)
    assert (result.copied, result.errors) == (1, 0)
    assert target._files["media"] == b"abc"
