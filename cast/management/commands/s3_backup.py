from django.core.management.base import BaseCommand
from django.core.files.storage import default_storage
from django.core.files.storage import get_storage_class

from ...utils import storage_walk_paths


class Command(BaseCommand):
    help = "backup media files from s3 to local media root"

    def handle(self, *args, **options):
        s3 = get_storage_class("storages.backends.s3boto3.S3Boto3Storage")()
        for path in storage_walk_paths(s3):
            if not default_storage.exists(path):
                print(path)
                with s3.open(path, "rb") as in_f:
                    default_storage.save(path, in_f)
