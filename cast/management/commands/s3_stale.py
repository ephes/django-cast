from django.core.management.base import BaseCommand
from django.core.files.storage import default_storage
from django.core.files.storage import get_storage_class

from ...models import File
from ...models import Image
from ...models import Video

from ...utils import storage_walk_paths


class Command(BaseCommand):
    help = (
        "show media files which are in the filesystem (s3, locale), "
        "but not in database and optionally delete them"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--delete",
            action="store_true",
            dest="delete",
            default=False,
            help="Delete stale files instead of only showing them",
        )

    def get_paths(self, storage):
        paths = {}
        for path in storage_walk_paths(storage):
            size = storage.size(path)
            paths[path] = size
            # print(path, size / 2 ** 20)
        return paths

    def get_models_paths(self):
        paths = set()
        for image in Image.objects.all():
            for path in image.get_all_paths():
                paths.add(path)
        for video in Video.objects.all():
            for path in video.get_all_paths():
                paths.add(path)
        for misc_file in File.objects.all():
            for path in misc_file.get_all_paths():
                paths.add(path)
        return paths

    def handle(self, *args, **options):
        paths_from_models = self.get_models_paths()

        print("stale s3")
        s3 = get_storage_class("storages.backends.s3boto3.S3Boto3Storage")()
        s3_paths = self.get_paths(s3)
        stale_s3 = {}
        for path, size in s3_paths.items():
            if path not in paths_from_models:
                print(path)
                stale_s3[path] = size
        print("stale s3 size: {} Mb".format(sum(stale_s3.values()) / 2 ** 20))

        print("stale locale")
        locale_paths = self.get_paths(default_storage)
        stale_locale = {}
        for path, size in locale_paths.items():
            if path not in paths_from_models:
                print(path)
                stale_locale[path] = size
        print("stale locale size: {} Mb".format(sum(stale_locale.values()) / 2 ** 20))

        if options["delete"]:
            # for path in stale_s3.keys():
            #     s3.delete(path)
            for path in stale_locale.keys():
                default_storage.delete(path)
