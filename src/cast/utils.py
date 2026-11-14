import posixpath
from collections.abc import Iterable

from django.core.files.storage import Storage

MAX_STORAGE_DEPTH = 64
MAX_STORAGE_DIRECTORIES = 10_000
MAX_STORAGE_FILES = 1_000_000


class StorageInventoryError(ValueError):
    """The backend cannot supply a safe, complete, bounded inventory."""


def validate_storage_component(name: str) -> None:
    if not isinstance(name, str) or name in {"", ".", ".."} or any(c in name for c in ("/", "\\", ":", "\x00")):
        raise StorageInventoryError(f"storage inventory refused unsafe listing component {name!r}")


def storage_walk_paths(storage: Storage, cur_dir: str = "") -> Iterable[str]:
    """Walk portable keys iteratively; refuse unsafe or incomplete inventories."""
    if cur_dir:
        for component in cur_dir.split("/"):
            validate_storage_component(component)
    pending = [(cur_dir, 0)]
    seen_directories = {cur_dir}
    file_count = 0
    while pending:
        directory, depth = pending.pop()
        dirs, files = storage.listdir(directory)
        children = []
        for name in dirs:
            validate_storage_component(name)
            child = posixpath.join(directory, name)
            if child in seen_directories:
                raise StorageInventoryError(f"storage inventory repeated directory {child!r}")
            if depth >= MAX_STORAGE_DEPTH or len(seen_directories) >= MAX_STORAGE_DIRECTORIES:
                raise StorageInventoryError("storage inventory exceeded directory/depth limit")
            seen_directories.add(child)
            children.append((child, depth + 1))
        paths = []
        for name in files:
            validate_storage_component(name)
            file_count += 1
            if file_count > MAX_STORAGE_FILES:
                raise StorageInventoryError("storage inventory exceeded file limit")
            paths.append(posixpath.join(directory, name))
        # Validate the entire listing before exposing any of its paths to a writer.
        yield from paths
        pending.extend(reversed(children))
