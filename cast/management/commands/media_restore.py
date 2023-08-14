from django.core.management.base import BaseCommand

from .storage_backend import get_production_and_backup_storage, sync_media_files


class Command(BaseCommand):
    help = (
        "restore media files from backup storage backend to production storage backend "
        "(requires Django >= 4.2 and production and backup storage configured)"
    )

    @staticmethod
    def restore_media_files(production_storage, backup_storage):
        sync_media_files(backup_storage, production_storage)

    def handle(self, *args, **options):
        self.restore_media_files(*get_production_and_backup_storage())
