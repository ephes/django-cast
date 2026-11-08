from collections.abc import Callable
from typing import Any

from django.core.files.storage import Storage
from django.core.management.base import BaseCommand, CommandError

from .storage_backend import SyncResult, get_production_and_backup_storage, sync_media_files


class Command(BaseCommand):
    help = (
        "restore media files from backup storage backend to production storage backend "
        "(requires production and backup storage backends configured)"
    )

    @staticmethod
    def restore_media_files(
        production_storage: Storage,
        backup_storage: Storage,
        *,
        report_error: Callable[[str], None] | None = None,
    ) -> SyncResult:
        return sync_media_files(backup_storage, production_storage, report_error=report_error)

    def handle(self, *args: Any, **options: Any) -> None:
        result = self.restore_media_files(*get_production_and_backup_storage(), report_error=self.stderr.write)
        self.stdout.write("")
        self.stdout.write(result.summary())
        if result.errors:
            raise CommandError(f"{result.errors} path(s) could not be restored; see the errors above.")
