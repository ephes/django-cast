try:
    from django.core.files.storage import InvalidStorageError, storages

    DJANGO_VERSION_VALID = True
except ImportError:
    DJANGO_VERSION_VALID = False
from django.core.management.base import BaseCommand

from ...utils import storage_walk_paths


class Command(BaseCommand):
    help = (
        "backup media files from production to backup storage "
        "(requires Django >= 4.2 and production and backup storage configured)"
    )

    def handle(self, *args, **options):
        if not DJANGO_VERSION_VALID:
            # make sure we run at least Django 4.2
            print("Django version >= 4.2 is required")
            return
        try:
            production_storage, backup_storage = storages["production"], storages["backup"]
        except InvalidStorageError:
            print("production or backup storage not configured")
            return
        for num, path in enumerate(storage_walk_paths(production_storage)):
            if not backup_storage.exists(path):
                with production_storage.open(path, "rb") as in_f:
                    backup_storage.save(path, in_f)
            if num % 100 == 0:
                print(".", end="", flush=True)
