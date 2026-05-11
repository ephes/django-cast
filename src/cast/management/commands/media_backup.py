from django.core.management.base import BaseCommand

from .storage_backend import get_production_and_backup_storage, sync_media_files


class Command(BaseCommand):
    help = "backup media files from production to backup storage (requires production and backup storage backends configured)"

    @staticmethod
    def backup_media_files(production_storage, backup_storage):
        sync_media_files(production_storage, backup_storage)

    def handle(self, *args, **options):
        self.backup_media_files(*get_production_and_backup_storage())
