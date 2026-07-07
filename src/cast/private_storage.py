from functools import lru_cache
from pathlib import Path

from django.conf import settings
from django.core.files.storage import FileSystemStorage, InvalidStorageError, Storage, default_storage, storages

from cast import appsettings

PRIVATE_MEDIA_STORAGE_ALIAS = "cast_private_media"
TRANSCRIPT_STORAGE_ALIAS = "cast_public_transcripts"


class PrivateFileSystemStorage(FileSystemStorage):
    def url(self, name: str | None) -> str:
        raise ValueError("This private file is not accessible via a URL.")


def get_private_media_root() -> str:
    configured_root = appsettings.CAST_PRIVATE_MEDIA_ROOT
    if configured_root:
        return str(configured_root)
    media_root = Path(getattr(settings, "MEDIA_ROOT", "."))
    return str(media_root.parent / "cast-private-media")


@lru_cache
def get_private_filesystem_storage(location: str) -> PrivateFileSystemStorage:
    return PrivateFileSystemStorage(location=location)


def get_private_media_storage() -> Storage:
    try:
        return storages[PRIVATE_MEDIA_STORAGE_ALIAS]
    except InvalidStorageError:
        return get_private_filesystem_storage(get_private_media_root())


def get_transcript_storage() -> Storage:
    """Return storage for public transcript artifacts.

    Podlove, WebVTT, and DOTe transcript files are publishable artifacts. Prefer
    an explicit transcript storage alias, keep compatibility with deployments
    that already configured the former private-media alias for these files, and
    otherwise preserve the original default-storage behavior.
    """
    try:
        return storages[TRANSCRIPT_STORAGE_ALIAS]
    except InvalidStorageError:
        pass
    try:
        return storages[PRIVATE_MEDIA_STORAGE_ALIAS]
    except InvalidStorageError:
        return default_storage
