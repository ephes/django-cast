from django.core.management.base import BaseCommand
from django.core.files.storage import default_storage
from django.core.files.storage import get_storage_class

from blogs.utils import storage_walk_paths


class Command(BaseCommand):
    help = "restoremedia files from local media root to s3"

    def handle(self, *args, **options):
        s3 = get_storage_class("storages.backends.s3boto3.S3Boto3Storage")()
        for path in storage_walk_paths(default_storage):
            if not s3.exists(path):
                print(path)
                with default_storage.open(path, "rb") as in_f:
                    s3.save(path, in_f)
