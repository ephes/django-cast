from django.core.management.base import BaseCommand

from ...utils import storage_walk_paths
from .storage_backend import get_production_and_backup_storage


class Command(BaseCommand):
    help = (
        "backup media files from production to backup storage "
        "(requires Django >= 4.2 and production and backup storage configured)"
    )

    @staticmethod
    def backup_media_files(production_storage, backup_storage):
        for num, path in enumerate(storage_walk_paths(production_storage)):
            if not backup_storage.exists(path):
                with production_storage.open(path, "rb") as in_f:
                    backup_storage.save(path, in_f)
            if num % 100 == 0:  # pragma: no cover
                print(".", end="", flush=True)

    def handle(self, *args, **options):
        self.backup_media_files(*get_production_and_backup_storage())
