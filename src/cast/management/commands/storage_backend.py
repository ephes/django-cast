import getpass
import hashlib
import logging
import math
import os
import re
import stat
import tempfile
from collections.abc import Callable, Generator, Iterator
from contextlib import ExitStack, contextmanager, suppress
from dataclasses import dataclass, field
from io import BufferedReader, RawIOBase
from pathlib import Path
from time import monotonic
from typing import Any
from uuid import uuid4

from django.core.files import File, locks
from django.core.files.storage import InvalidStorageError, Storage, storages
from django.core.management.base import CommandError

from ...utils import StorageInventoryError, storage_walk_paths

logger = logging.getLogger(__name__)

CONTENT_CHUNK_SIZE = 1024 * 1024
MAX_MEDIA_READ_BYTES = 16 * 1024**3
MAX_MEDIA_READ_SECONDS = 300
# Large objects on remote storage get more time: the per-read deadline never
# assumes a link faster than this.
MIN_MEDIA_READ_BYTES_PER_SECOND = 4 * 1024**2


class MediaReadBudgetExceeded(RuntimeError):
    """A storage stream exceeded the allotted bytes or time."""


@dataclass
class MediaReadBudget:
    """Bytes and time for one full read of one object."""

    remaining: int = field(default_factory=lambda: MAX_MEDIA_READ_BYTES)
    deadline: float = field(default_factory=lambda: monotonic() + MAX_MEDIA_READ_SECONDS)
    expected_size: int | None = None

    @staticmethod
    def object_allowance(storage: Storage, path: str) -> tuple[int | None, int]:
        """The reported object size (if usable) and the seconds a full read may take."""
        try:
            size = storage.size(path)
        except Exception:  # An unknown size keeps the base deadline.
            size = None
        expected_size = size if type(size) is int and size >= 0 else None
        # Beyond the byte ceiling more time cannot help: such a read is refused anyway.
        scaled = min(expected_size or 0, MAX_MEDIA_READ_BYTES)
        seconds = max(MAX_MEDIA_READ_SECONDS, math.ceil(scaled / MIN_MEDIA_READ_BYTES_PER_SECOND))
        return expected_size, seconds

    @classmethod
    def for_object(cls, storage: Storage, path: str) -> "MediaReadBudget":
        """A fresh budget whose deadline scales with the reported object size."""
        expected_size, seconds = cls.object_allowance(storage, path)
        return cls(deadline=monotonic() + seconds, expected_size=expected_size)

    def check_time(self) -> None:
        if monotonic() >= self.deadline:
            raise MediaReadBudgetExceeded("media read exceeded time budget")

    def consume(self, size: int) -> None:
        self.check_time()
        self.remaining -= size
        if self.remaining < 0:
            raise MediaReadBudgetExceeded("media read exceeded byte budget")

    def read_chunk(self, stream: File, size: int = CONTENT_CHUNK_SIZE) -> bytes:
        self.consume(0)  # A backend retry cannot read past an exhausted budget.
        chunk: bytes = stream.read(min(size, CONTENT_CHUNK_SIZE, self.remaining + 1))
        self.consume(len(chunk))
        return chunk


@dataclass
class MediaSaveReadBudget(MediaReadBudget):
    """Bytes and read time for one stream consumed by ``Storage.save()``.

    Only time spent opening and inside the stream's own reads is charged. A
    backend uploading between reads (multipart transfers, spooled uploads) is
    not limited by this budget, so slow uplinks do not fail large transfers.
    """

    seconds: float = MAX_MEDIA_READ_SECONDS
    spent: float = 0.0

    @classmethod
    def for_object(cls, storage: Storage, path: str) -> "MediaSaveReadBudget":
        expected_size, seconds = cls.object_allowance(storage, path)
        return cls(seconds=seconds, expected_size=expected_size)

    def check_time(self) -> None:
        if self.spent >= self.seconds:
            raise MediaReadBudgetExceeded("media read exceeded time budget")

    @contextmanager
    def charged(self) -> Iterator[None]:
        started = monotonic()
        try:
            yield
        finally:
            self.spent += monotonic() - started

    def read_chunk(self, stream: File, size: int = CONTENT_CHUNK_SIZE) -> bytes:
        self.consume(0)  # A backend retry cannot read past an exhausted budget.
        with self.charged():
            chunk: bytes = stream.read(min(size, CONTENT_CHUNK_SIZE, self.remaining + 1))
        self.consume(len(chunk))
        return chunk


class BudgetedMediaStream(RawIOBase):
    """Supply buffered upload reads without exposing the underlying file handle."""

    def __init__(self, stream: File, budget: MediaSaveReadBudget) -> None:
        super().__init__()
        self.stream = stream
        self.budget = budget

    def readable(self) -> bool:
        return True

    # Lazy backends may download on the first access of any kind, so positioning is charged too.
    def seekable(self) -> bool:
        with self.budget.charged():
            return self.stream.seekable()

    def seek(self, offset: int, whence: int = os.SEEK_SET) -> int:
        self.budget.check_time()
        with self.budget.charged():
            return self.stream.seek(offset, whence)

    def tell(self) -> int:
        with self.budget.charged():
            return self.stream.tell()

    def readinto(self, buffer: Any) -> int:
        view = memoryview(buffer).cast("B")
        chunk = self.budget.read_chunk(self.stream, len(view))
        view[: len(chunk)] = chunk
        return len(chunk)


@contextmanager
def open_media_for_save(storage: Storage, path: str) -> Iterator[File]:
    budget = MediaSaveReadBudget.for_object(storage, path)
    with ExitStack() as stack:
        with budget.charged():
            stream = stack.enter_context(storage.open(path, "rb"))
        with BufferedReader(BudgetedMediaStream(stream, budget), buffer_size=CONTENT_CHUNK_SIZE) as bounded:
            yield File(bounded, name=path)


@dataclass
class SyncResult:
    copied: int = 0
    refreshed: int = 0
    unchanged: int = 0
    errors: int = 0

    def summary(self) -> str:
        return f"copied={self.copied} refreshed={self.refreshed} unchanged={self.unchanged} errors={self.errors}"


def temporary_refresh_path(path: str) -> str:
    return f"{path}.django-cast-refresh-{uuid4().hex}.tmp"


def is_media_staging_key(path: str) -> bool:
    return re.search(r"\.django-cast-(?:refresh|replace)-[0-9a-f]{32}(?:_[A-Za-z0-9]+)?\.tmp\Z", path) is not None


# Remote object handles of opened storage files: S3 (``obj``) and Google Cloud (``blob``).
REMOTE_OBJECT_ATTRIBUTES = ("obj", "blob")


def is_transparently_decoded(stream: Any) -> bool:
    """Whether an opened stream decodes a stored content encoding (e.g. gzip on S3 or Google Cloud)."""
    for attribute in REMOTE_OBJECT_ATTRIBUTES:
        encoding = getattr(getattr(stream, attribute, None), "content_encoding", None)
        if isinstance(encoding, str) and encoding.strip().lower() not in ("", "identity"):
            return True
    return False


def bounded_media_chunks(storage: Storage, path: str, budget: MediaReadBudget) -> Generator[bytes, None, None]:
    budget.check_time()
    with storage.open(path, "rb") as in_f:
        if budget.expected_size is not None and is_transparently_decoded(in_f):
            budget.expected_size = None  # The reported size is the encoded length, not the decoded bytes.
        while True:
            chunk = budget.read_chunk(in_f)
            if not chunk:
                return
            yield chunk


def content_digest(storage: Storage, path: str, *, budget: MediaReadBudget | None = None) -> bytes:
    budget = budget or MediaReadBudget.for_object(storage, path)
    digest = hashlib.sha256()
    initial_remaining = budget.remaining
    for chunk in bounded_media_chunks(storage, path, budget):
        digest.update(chunk)
    count = initial_remaining - budget.remaining
    if budget.expected_size is not None and count != budget.expected_size:
        raise RuntimeError(f"media extent mismatch for {path}: read {count} bytes, expected {budget.expected_size}")
    return digest.digest()


def sizes_differ(source_storage: Storage, target_storage: Storage, path: str) -> bool:
    """
    Cheap proof that two objects differ. Equal sizes prove nothing, and a
    backend that cannot report a size is no evidence either way.
    """
    try:
        return source_storage.size(path) != target_storage.size(path)
    except NotImplementedError:
        return False


def content_differs(source_storage: Storage, target_storage: Storage, path: str) -> bool:
    if sizes_differ(source_storage, target_storage, path):
        return True
    # Each full read gets its own byte/time budget.
    return content_digest(source_storage, path) != content_digest(target_storage, path)


def remove_staged_copies(storage: Storage, staged_names: set[str]) -> None:
    failures = []
    for staged_name in sorted(staged_names):
        try:
            if storage.exists(staged_name):
                storage.delete(staged_name)
        except Exception as exc:
            failures.append(f"could not remove staged copy {staged_name}: {exc}")
    if failures:
        raise RuntimeError("; ".join(failures))


def publication_identity() -> str:
    getuid = getattr(os, "getuid", None)
    if getuid is not None:
        return f"uid-{getuid()}"
    try:
        return hashlib.sha256(getpass.getuser().encode()).hexdigest()
    except OSError:  # pragma: no cover - only without a POSIX uid and a login name
        return "default"


def publication_lock_path() -> Path:
    """The lock file inside an owner-only directory in the temp directory.

    A shared, world-writable temp directory lets another local user pre-create a
    predictable name (unreadable, or a symlink); the private directory and a
    no-follow open refuse both instead of locking a file someone else chose.
    """
    directory = Path(tempfile.gettempdir()) / f"django-cast-media-sync-{publication_identity()}"
    try:
        directory.mkdir(mode=0o700)
    except FileExistsError:
        pass
    info = directory.lstat()
    if (
        not stat.S_ISDIR(info.st_mode)
        or (hasattr(os, "getuid") and info.st_uid != os.getuid())
        or (os.name != "nt" and info.st_mode & 0o077)
    ):
        raise RuntimeError(f"media publication lock directory {directory} is not private to this user")
    return directory / "publication.lock"


@contextmanager
def media_publication_lock() -> Iterator[None]:
    """Fence cooperating media publishers sharing this host/user/temp directory."""
    lock_path = publication_lock_path()
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    # Never unlink: waiters must keep referring to the same lock inode.
    with os.fdopen(os.open(lock_path, flags, 0o600), "r+b") as lock_file:
        if not locks.lock(lock_file, locks.LOCK_EX | locks.LOCK_NB):
            raise RuntimeError(
                "media publication conflict: another sync owns the local publication lock or locking is unsupported"
            )
        try:
            yield
        finally:
            locks.unlock(lock_file)


def refresh_existing_file(
    source_storage: Storage,
    target_storage: Storage,
    path: str,
    *,
    report_error: Callable[[str], None] | None = None,
) -> None:
    with media_publication_lock():
        publish_staged_file(source_storage, target_storage, path, missing=False, report_error=report_error)


def copy_missing_file(
    source_storage: Storage,
    target_storage: Storage,
    path: str,
    *,
    report_error: Callable[[str], None] | None = None,
) -> None:
    with media_publication_lock():
        publish_staged_file(source_storage, target_storage, path, missing=True, report_error=report_error)


def publish_staged_file(
    source_storage: Storage,
    target_storage: Storage,
    path: str,
    *,
    missing: bool,
    report_error: Callable[[str], None] | None,
) -> None:
    """Stage and revalidate under the caller's exclusive publication lock.

    Writers outside this same-host lock require backend conditional operations;
    they must be quiesced. Generic Storage has no compare-and-swap primitive.
    Keep the verified stage if a refresh's final overwrite raises or its
    same-name save cannot be verified. A missing copy keeps no stage. Reserved
    recovery keys are excluded from sync enumeration.
    """
    target_exists = target_storage.exists(path)
    if target_exists == missing:
        raise RuntimeError(f"media publication conflict: target presence changed for {path}")
    # Verification and each transfer have independent, size-scaled read budgets.
    target_before = content_digest(target_storage, path) if target_exists else None
    source_before = content_digest(source_storage, path)
    requested_stage = temporary_refresh_path(path)
    if target_storage.exists(requested_stage):
        raise RuntimeError(f"media publication conflict: staging key already exists {requested_stage}")
    staged_names = {requested_stage}
    recovery_name = None
    try:
        with open_media_for_save(source_storage, path) as in_f:
            staged_name = target_storage.save(requested_stage, in_f)
        staged_names.add(staged_name)
        if not target_storage.exists(staged_name):
            raise RuntimeError(f"staged copy {staged_name} was not saved")
        if not is_media_staging_key(staged_name):
            raise RuntimeError(f"storage returned non-reserved staging key {staged_name}")
        if content_digest(target_storage, staged_name) != source_before:
            raise RuntimeError(f"staged copy {staged_name} failed content verification")
        if content_digest(source_storage, path) != source_before:
            raise RuntimeError(f"media publication conflict: source changed while staging {path}")
        current_exists = target_storage.exists(path)
        if current_exists != target_exists or (
            current_exists and content_digest(target_storage, path) != target_before
        ):
            raise RuntimeError(f"media publication conflict: target changed while staging {path}")
        with open_media_for_save(target_storage, staged_name) as staged_f:
            try:
                saved_name = target_storage.save(path, staged_f)
            except BaseException:
                if missing:
                    # Absence was revalidated while holding the writer lock:
                    # a failed final save can only have created our own key.
                    staged_names.add(path)
                else:
                    # The failed overwrite may have left partial bytes over the
                    # previous target: keep the verified stage as the recovery
                    # copy. A renamed save never touched the target and needs none.
                    recovery_name = staged_name
                raise
            if saved_name == path:
                if missing:
                    # The source is intact, so an ordinary retry repairs an
                    # unverified copy: drop its final key and the stage.
                    staged_names.add(path)
                else:
                    recovery_name = staged_name
        if saved_name != path:
            if missing:
                message = (
                    f"storage saved copy as {saved_name} instead of requested {path}; "
                    "nothing was published at the requested path"
                )
            else:
                message = (
                    f"storage saved copy as {saved_name} instead of requested {path}; "
                    "the existing copy was kept (the target storage must overwrite existing names)"
                )
            try:
                if target_storage.exists(saved_name):
                    target_storage.delete(saved_name)
            except Exception as cleanup_error:
                raise RuntimeError(
                    f"{message}; could not remove generated copy {saved_name}: {cleanup_error}"
                ) from cleanup_error
            raise RuntimeError(message)
        if content_digest(target_storage, path) != source_before:
            raise RuntimeError(f"published copy {path} failed content verification")
        staged_names.discard(path)
    except BaseException as primary_error:
        warnings = []
        if recovery_name is not None:
            staged_names.discard(recovery_name)
            message = f"complete recovery copy retained at {recovery_name}; inspect before retry or manual deletion"
            primary_error.add_note(message)
            warnings.append(message)
        try:
            remove_staged_copies(target_storage, staged_names)
        except RuntimeError as cleanup_error:
            primary_error.add_note(str(cleanup_error))
            warnings.append(f"warning: refresh staging cleanup failed: {cleanup_error}")
        for message in warnings:
            report_sync_message(message, report_error, always_log=True)
        raise
    else:
        try:
            remove_staged_copies(target_storage, staged_names)
        except RuntimeError as cleanup_error:
            report_sync_message(
                f"warning: sync published {path}, but staging cleanup failed: {cleanup_error}", report_error
            )


def report_sync_message(message: str, report_error: Callable[[str], None] | None, *, always_log: bool = False) -> None:
    if report_error is not None:
        with suppress(Exception):
            report_error(message)
            if not always_log:
                return
    with suppress(Exception):
        logger.warning(message)


def sync_media_files(
    source_storage: Storage,
    target_storage: Storage,
    *,
    refresh_changed: bool = False,
    report_error: Callable[[str], None] | None = None,
) -> SyncResult:
    """
    Copy every path that is missing in the target.

    With ``refresh_changed`` paths that exist on both sides are compared by
    content and the target copy is overwritten when it differs. In every mode,
    a path that cannot be checked, copied, compared or refreshed is reported and
    counted as an error, and the remaining paths are still processed.
    """
    result = SyncResult()
    try:
        for num, path in enumerate(storage_walk_paths(source_storage)):
            if is_media_staging_key(path):
                message = f"skipped reserved media staging key {path}; inspect and remove manually"
                report_sync_message(message, report_error)
                continue
            try:
                # Even an unchanged decision must not observe another writer's
                # in-flight partial final key outside the publication fence.
                with media_publication_lock():
                    missing = not target_storage.exists(path)
                    if missing or (refresh_changed and content_differs(source_storage, target_storage, path)):
                        publish_staged_file(
                            source_storage, target_storage, path, missing=missing, report_error=report_error
                        )
                        if missing:
                            result.copied += 1
                        else:
                            result.refreshed += 1
                    else:
                        result.unchanged += 1
            except Exception as exc:
                result.errors += 1
                message = f"error syncing {path}: {exc}"
                report_sync_message(message, report_error)
            if num % 100 == 0:  # pragma: no cover
                print(".", end="", flush=True)
    except StorageInventoryError as exc:
        result.errors += 1
        message = f"incomplete storage inventory: {exc}"
        report_sync_message(message, report_error)
    return result


def get_production_and_backup_storage() -> tuple[Storage, Storage]:
    try:
        production_storage, backup_storage = storages["production"], storages["backup"]
        return production_storage, backup_storage
    except InvalidStorageError:
        raise CommandError("production or backup storage not configured")
