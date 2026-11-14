import getpass
import hashlib
import logging
import math
import os
import re
import stat
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from time import monotonic
from uuid import uuid4

from django.core.files import locks
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


@dataclass
class MediaReadBudget:
    """Bytes and time for one full read of one object."""

    remaining: int = field(default_factory=lambda: MAX_MEDIA_READ_BYTES)
    deadline: float = field(default_factory=lambda: monotonic() + MAX_MEDIA_READ_SECONDS)

    @classmethod
    def for_object(cls, storage: Storage, path: str) -> "MediaReadBudget":
        """A fresh budget whose deadline scales with the reported object size."""
        try:
            size = storage.size(path)
        except Exception:  # Advisory only: an unknown size keeps the base deadline.
            size = 0
        # Beyond the byte ceiling more time cannot help: such a read is refused anyway.
        scaled = min(max(size, 0), MAX_MEDIA_READ_BYTES)
        seconds = max(MAX_MEDIA_READ_SECONDS, math.ceil(scaled / MIN_MEDIA_READ_BYTES_PER_SECOND))
        return cls(deadline=monotonic() + seconds)

    def check_time(self) -> None:
        if monotonic() >= self.deadline:
            raise RuntimeError("media comparison exceeded time budget")

    def consume(self, size: int) -> None:
        self.check_time()
        self.remaining -= size
        if self.remaining < 0:
            raise RuntimeError("media comparison exceeded byte budget")


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


def content_digest(storage: Storage, path: str, *, budget: MediaReadBudget | None = None) -> bytes:
    budget = budget or MediaReadBudget.for_object(storage, path)
    digest = hashlib.sha256()
    budget.check_time()
    with storage.open(path, "rb") as in_f:
        while True:
            budget.check_time()
            chunk = in_f.read(min(CONTENT_CHUNK_SIZE, budget.remaining + 1))
            budget.consume(len(chunk))
            if not chunk:
                break
            digest.update(chunk)
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
    """
    target_exists = target_storage.exists(path)
    if target_exists == missing:
        raise RuntimeError(f"media publication conflict: target presence changed for {path}")
    # Every full read gets its own size-scaled budget; backend save I/O is not
    # charged to any of them.
    target_before = content_digest(target_storage, path) if target_exists else None
    source_before = content_digest(source_storage, path)
    requested_stage = temporary_refresh_path(path)
    if target_storage.exists(requested_stage):
        raise RuntimeError(f"media publication conflict: staging key already exists {requested_stage}")
    staged_names = {requested_stage}
    try:
        with source_storage.open(path, "rb") as in_f:
            staged_name = target_storage.save(requested_stage, in_f)
        staged_names.add(staged_name)
        if not target_storage.exists(staged_name):
            raise RuntimeError(f"staged copy {staged_name} was not saved")
        if (
            content_digest(target_storage, staged_name) != source_before
            or content_digest(source_storage, path) != source_before
        ):
            raise RuntimeError(f"media publication conflict: source changed while staging {path}")
        current_exists = target_storage.exists(path)
        if current_exists != target_exists or (
            current_exists and content_digest(target_storage, path) != target_before
        ):
            raise RuntimeError(f"media publication conflict: target changed while staging {path}")
        with target_storage.open(staged_name, "rb") as staged_f:
            try:
                saved_name = target_storage.save(path, staged_f)
            except BaseException:
                if missing:
                    # Absence was revalidated while holding the writer lock:
                    # a failed final save can only have created our own key.
                    staged_names.add(path)
                raise
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
    except BaseException as primary_error:
        try:
            remove_staged_copies(target_storage, staged_names)
        except RuntimeError as cleanup_error:
            primary_error.add_note(str(cleanup_error))
            logger.warning("Refresh staging cleanup failed: %s", cleanup_error)
            if report_error is not None:
                report_error(f"warning: refresh staging cleanup failed: {cleanup_error}")
        raise
    else:
        remove_staged_copies(target_storage, staged_names)


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
            if re.search(r"\.django-cast-refresh-[0-9a-f]{32}\.tmp\Z", path):
                message = f"skipped reserved refresh staging key {path}; inspect and remove manually"
                if report_error is not None:
                    report_error(message)
                else:
                    logger.warning(message)
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
                if report_error is not None:
                    report_error(message)
                else:
                    logger.warning(message)
            if num % 100 == 0:  # pragma: no cover
                print(".", end="", flush=True)
    except StorageInventoryError as exc:
        result.errors += 1
        message = f"incomplete storage inventory: {exc}"
        if report_error is not None:
            report_error(message)
        else:
            logger.warning(message)
    return result


def get_production_and_backup_storage() -> tuple[Storage, Storage]:
    try:
        production_storage, backup_storage = storages["production"], storages["backup"]
        return production_storage, backup_storage
    except InvalidStorageError:
        raise CommandError("production or backup storage not configured")
