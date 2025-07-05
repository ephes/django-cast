from django.core.files.storage import FileSystemStorage
from django.core.management.base import BaseCommand

from .storage_backend import get_production_and_backup_storage


class Command(BaseCommand):
    help = (
        "replace paths on production storage backend with local versions - useful for compressed videos for example"
        "(requires Django >= 4.2 and production and backup storage configured)"
    )

    def add_arguments(self, parser):
        parser.add_argument("paths", nargs="+", type=str)

    def handle(self, *args, **options):
        production, _ = get_production_and_backup_storage()
        fs_storage = FileSystemStorage()
        for path in options["paths"]:
            if fs_storage.exists(path):
                if production.exists(path):
                    production.delete(path)
                with fs_storage.open(path, "rb") as in_f:
                    production.save(path, in_f)
