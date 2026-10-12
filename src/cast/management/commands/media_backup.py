from argparse import ArgumentParser
from typing import Any

from django.core.files.storage import Storage
from django.core.management.base import BaseCommand, CommandError

from .storage_backend import SyncResult, get_production_and_backup_storage, sync_media_files


class Command(BaseCommand):
    help = "backup media files from production to backup storage (requires production and backup storage backends configured)"

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument(
            "--refresh-changed",
            action="store_true",
            default=False,
            help=(
                "Also compare files that already exist in the backup by content and overwrite backup copies "
                "that differ from production (reads every such file from both storages)."
            ),
        )

    def backup_media_files(
        self, production_storage: Storage, backup_storage: Storage, *, refresh_changed: bool = False
    ) -> SyncResult:
        return sync_media_files(
            production_storage,
            backup_storage,
            refresh_changed=refresh_changed,
            report_error=self.stderr.write,
        )

    def handle(self, *args: Any, **options: Any) -> None:
        refresh_changed = options["refresh_changed"]
        result = self.backup_media_files(*get_production_and_backup_storage(), refresh_changed=refresh_changed)
        if not refresh_changed:
            return
        self.stdout.write("")
        self.stdout.write(result.summary())
        if result.errors:
            raise CommandError(f"{result.errors} path(s) could not be backed up; see the errors above.")
