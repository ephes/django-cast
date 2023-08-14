from django.core.files.storage import InvalidStorageError, Storage

try:
    from django.core.files.storage import storages  # noqa F401

    DJANGO_VERSION_VALID = True
except ImportError:  # pragma: no cover
    DJANGO_VERSION_VALID = False

from django.core.management.base import CommandError

from ...utils import storage_walk_paths


def sync_media_files(source_storage, target_storage):
    for num, path in enumerate(storage_walk_paths(source_storage)):
        if not target_storage.exists(path):
            with source_storage.open(path, "rb") as in_f:
                target_storage.save(path, in_f)
        if num % 100 == 0:  # pragma: no cover
            print(".", end="", flush=True)


def get_production_and_backup_storage() -> tuple[Storage, Storage]:
    if not DJANGO_VERSION_VALID:
        # make sure we run at least Django 4.2
        raise CommandError("Django version >= 4.2 is required")
    else:
        try:
            production_storage, backup_storage = storages["production"], storages["backup"]
            return production_storage, backup_storage
        except InvalidStorageError:
            raise CommandError("production or backup storage not configured")
