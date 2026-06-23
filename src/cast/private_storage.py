from pathlib import Path
from functools import lru_cache

from django.conf import settings
from django.core.files.storage import FileSystemStorage, InvalidStorageError, storages

PRIVATE_MEDIA_STORAGE_ALIAS = "cast_private_media"


class PrivateFileSystemStorage(FileSystemStorage):
    def url(self, name: str) -> str:
        raise ValueError("This private file is not accessible via a URL.")


def get_private_media_root() -> str:
    configured_root = getattr(settings, "CAST_PRIVATE_MEDIA_ROOT", "")
    if configured_root:
        return str(configured_root)
    media_root = Path(getattr(settings, "MEDIA_ROOT", "."))
    return str(media_root.parent / "cast-private-media")


@lru_cache
def get_private_filesystem_storage(location: str) -> PrivateFileSystemStorage:
    return PrivateFileSystemStorage(location=location)


def get_private_media_storage():
    try:
        return storages[PRIVATE_MEDIA_STORAGE_ALIAS]
    except InvalidStorageError:
        return get_private_filesystem_storage(get_private_media_root())
