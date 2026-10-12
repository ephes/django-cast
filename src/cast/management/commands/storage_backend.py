import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from uuid import uuid4

from django.core.files.storage import InvalidStorageError, Storage, storages
from django.core.management.base import CommandError

from ...utils import storage_walk_paths

CONTENT_CHUNK_SIZE = 1024 * 1024


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


def content_digest(storage: Storage, path: str) -> bytes:
    digest = hashlib.sha256()
    with storage.open(path, "rb") as in_f:
        while chunk := in_f.read(CONTENT_CHUNK_SIZE):
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
    return content_digest(source_storage, path) != content_digest(target_storage, path)


def remove_staged_copies(storage: Storage, staged_names: set[str]) -> None:
    for staged_name in sorted(staged_names):
        try:
            if storage.exists(staged_name):
                storage.delete(staged_name)
        except Exception as exc:
            raise RuntimeError(f"could not remove staged copy {staged_name}: {exc}") from exc


def refresh_existing_file(source_storage: Storage, target_storage: Storage, path: str) -> None:
    """
    Overwrite ``path`` in the target with the bytes from the source.

    The new bytes are first staged under a temporary key in the target, so a
    source that cannot be read completely or a target that cannot be written
    never touches the existing object. The existing object is only written
    from the complete staged copy, and never deleted first: a target backend
    that refuses to overwrite keeps its previous bytes and the refresh fails.
    Whether a failing final write leaves the previous bytes intact is up to
    the backend.
    """
    requested_stage = temporary_refresh_path(path)
    # A save that fails half way can leave a partial object under the key it
    # was asked for without ever returning a name, so that key is cleaned up
    # too. A leftover would be restored into production by media_restore.
    staged_names = {requested_stage}
    try:
        with source_storage.open(path, "rb") as in_f:
            staged_name = target_storage.save(requested_stage, in_f)
        staged_names.add(staged_name)
        if not target_storage.exists(staged_name):
            raise RuntimeError(f"staged copy {staged_name} was not saved")
        with target_storage.open(staged_name, "rb") as staged_f:
            saved_name = target_storage.save(path, staged_f)
        if saved_name != path:
            # The backend kept the existing object and stored the new bytes
            # under a generated name. Remove that stray copy, keep the old one.
            if target_storage.exists(saved_name):
                target_storage.delete(saved_name)
            raise RuntimeError(
                f"storage saved the refreshed copy as {saved_name} instead of overwriting {path}; "
                "the existing copy was kept (the target storage must overwrite existing names)"
            )
    finally:
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
    content and the target copy is overwritten when it differs. In that mode a
    path that cannot be checked, copied, compared or refreshed is reported and
    counted as an error, and the remaining paths are still processed. Without
    it the first failure propagates, as it always did.
    """
    result = SyncResult()
    for num, path in enumerate(storage_walk_paths(source_storage)):
        if refresh_changed:
            try:
                if not target_storage.exists(path):
                    with source_storage.open(path, "rb") as in_f:
                        target_storage.save(path, in_f)
                    result.copied += 1
                elif content_differs(source_storage, target_storage, path):
                    refresh_existing_file(source_storage, target_storage, path)
                    result.refreshed += 1
                else:
                    result.unchanged += 1
            except Exception as exc:
                result.errors += 1
                if report_error is not None:
                    report_error(f"error backing up {path}: {exc}")
        elif not target_storage.exists(path):
            with source_storage.open(path, "rb") as in_f:
                target_storage.save(path, in_f)
            result.copied += 1
        if num % 100 == 0:  # pragma: no cover
            print(".", end="", flush=True)
    return result


def get_production_and_backup_storage() -> tuple[Storage, Storage]:
    try:
        production_storage, backup_storage = storages["production"], storages["backup"]
        return production_storage, backup_storage
    except InvalidStorageError:
        raise CommandError("production or backup storage not configured")
