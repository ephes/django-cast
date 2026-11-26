"""Content comparison is bounded across source and target streams."""

from contextlib import contextmanager
from io import BytesIO

import pytest
from django.core.files import File
from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage

from cast.management.commands import storage_backend as media
from tests.management_command_helpers import StubOverwriteStorage


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
            saved = super().save(name, content)
            now[0] += 60  # Upload completion may outlast the read deadline.
            return saved

    source = StubOverwriteStorage({"media": b"abc"})
    target = SlowSaveStorage()
    result = media.sync_media_files(source, target)
    assert (result.copied, result.errors) == (1, 0)
    assert target._files["media"] == b"abc"


@pytest.mark.parametrize("reported_size", [4, 10, None])
def test_refresh_requires_complete_reported_source_extent(reported_size):
    class SourceStorage(StubOverwriteStorage):
        def size(self, name):
            if reported_size is None:
                raise NotImplementedError
            return reported_size

    path = "media"
    source = SourceStorage({path: b"abcdef"})
    target = StubOverwriteStorage({path: b"old"})
    errors = []
    result = media.sync_media_files(source, target, refresh_changed=True, report_error=errors.append)

    if reported_size is None:
        assert (result.refreshed, result.errors) == (1, 0)
        assert target._files == {path: b"abcdef"}
    else:
        assert (result.refreshed, result.errors) == (0, 1)
        assert target._files == {path: b"old"}
        assert target.saved == []
        assert f"read 6 bytes, expected {reported_size}" in errors[0]


@pytest.mark.parametrize("encoding", ["gzip", "identity", None])
def test_extent_check_skips_streams_decoded_from_their_stored_encoding(encoding):
    class Obj:
        content_encoding = encoding

    class EncodedStorage(StubOverwriteStorage):
        # Like S3 with gzip: size() is the stored (encoded) length, open() yields decoded bytes.
        def size(self, name):
            return super().size(name) + 20

        @contextmanager
        def open(self, name, mode):
            with super().open(name, mode) as stream:
                stream.obj = Obj()
                yield stream

    path = "image.svg"
    source = StubOverwriteStorage({path: b"<svg>new</svg>"})
    target = EncodedStorage({path: b"<svg>old</svg>"})
    errors = []
    result = media.sync_media_files(source, target, refresh_changed=True, report_error=errors.append)

    if encoding == "gzip":
        assert (result.refreshed, result.errors) == (1, 0)
        assert target._files[path] == b"<svg>new</svg>"
    else:
        assert (result.refreshed, result.errors) == (0, 1)
        assert any("media extent mismatch" in message for message in errors)
        assert target._files[path] == b"<svg>old</svg>"


def test_matching_final_digest_cannot_hide_truncated_final_extent(mocker):
    path = "media"
    source = StubOverwriteStorage({path: b"new"})
    target = StubOverwriteStorage({path: b"old"})
    original_size = target.size

    def size(name):
        count = original_size(name)
        return count + 1 if name == path and path in target.saved else count

    mocker.patch.object(target, "size", side_effect=size)
    errors = []
    result = media.sync_media_files(source, target, refresh_changed=True, report_error=errors.append)

    assert (result.refreshed, result.errors) == (0, 1)
    (key,) = target.staged()
    assert target._files[key] == b"new"
    assert any("read 3 bytes, expected 4" in message for message in errors)


@pytest.mark.parametrize("grows", ["source", "stage"])
@pytest.mark.parametrize("transfer", ["read", "chunks"])
def test_sync_caps_actual_save_reads(mocker, grows, transfer):
    limits(mocker)
    path = "media"
    transfers = []

    class TransferStorage(StubOverwriteStorage):
        @contextmanager
        def open(self, name, mode):
            growing = grows == "source" and self is source or grows == "stage" and media.is_media_staging_key(name)
            second_read = self.opened.count(name) == 1
            with super().open(name, mode) as stream:
                if growing and second_read:

                    class GrowingStream(BytesIO):
                        def read(self, size=-1):
                            chunk = super().read(size)
                            transfers.append(len(chunk))
                            return chunk

                    with GrowingStream(stream.getvalue() + b"x" * 20) as expanded:
                        yield File(expanded)
                else:
                    yield File(stream)

        def save(self, name, content):
            if transfer == "read":
                return super().save(name, content)
            with ContentFile(b"".join(content.chunks(chunk_size=2))) as assembled:
                return super().save(name, assembled)

    source = TransferStorage({path: b"new"})
    target = TransferStorage({path: b"old!"})
    errors = []
    result = media.sync_media_files(source, target, refresh_changed=True, report_error=errors.append)

    assert (result.copied, result.refreshed, result.errors) == (0, 0, 1)
    assert sum(transfers) == 7
    assert any("byte budget" in message for message in errors)
    assert target._files[path] == b"old!"
    if grows == "stage":
        (key,) = target.staged()
        assert target._files[key] == b"new"
        assert any(key in message for message in errors)
    else:
        assert target.staged() == []


def test_sync_streams_to_local_and_seekable_object_storage(tmp_path):
    class ObjectStorage(StubOverwriteStorage):
        def save(self, name, content):
            # Seek/tell size probing and sized reads, as used by S3 transfer managers.
            content.seek(0, 2)
            size = content.tell()
            content.seek(0)
            assert content.readable() and content.seekable()
            chunks = []
            while chunk := content.read(2):
                chunks.append(chunk)
            data = b"".join(chunks)
            assert len(data) == size
            return super().save(name, BytesIO(data))

    path = "media"
    local = FileSystemStorage(location=tmp_path)
    remote = ObjectStorage({path: b"synthetic media"})
    assert media.sync_media_files(remote, local).copied == 1
    restored = ObjectStorage()
    assert media.sync_media_files(local, restored).copied == 1
    assert restored._files == remote._files


def test_save_stream_refuses_when_its_reads_exceed_the_deadline(mocker):
    limits(mocker)
    now = [0.0]
    mocker.patch.object(media, "monotonic", side_effect=lambda: now[0], create=True)

    class SlowStream(BytesIO):
        def read(self, size=-1):
            now[0] += 11
            return super().read(size)

    class SlowReadStorage(StubOverwriteStorage):
        @contextmanager
        def open(self, name, mode):
            with super().open(name, mode) as stream:
                yield File(SlowStream(stream.read()))

    with media.open_media_for_save(SlowReadStorage({"media": b"abc"}), "media") as stream:
        with pytest.raises(media.MediaReadBudgetExceeded, match="time budget"):
            stream.read()


def test_backend_upload_time_between_save_reads_is_not_charged(mocker):
    limits(mocker, size=64)
    now = [0.0]
    mocker.patch.object(media, "monotonic", side_effect=lambda: now[0], create=True)

    class SlowUplinkStorage(StubOverwriteStorage):
        def save(self, name, content):
            parts = []
            while part := content.read(4):
                parts.append(part)
                now[0] += 11  # Uploading each part takes longer than the whole read allowance.
            return super().save(name, ContentFile(b"".join(parts)))

    data = b"synthetic media bytes"
    target = SlowUplinkStorage({"media": b"old"})
    result = media.sync_media_files(StubOverwriteStorage({"media": data}), target, refresh_changed=True)
    assert (result.refreshed, result.errors) == (1, 0)
    assert target._files["media"] == data
    assert target.staged() == []
