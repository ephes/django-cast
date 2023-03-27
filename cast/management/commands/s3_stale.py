from django.core.files.storage import default_storage, get_storage_class
from django.core.management.base import BaseCommand
from wagtail.images.models import Image

from ...models import File, Video
from ...utils import storage_walk_paths


class Command(BaseCommand):
    help = "show media files which are in the filesystem (s3, locale), but not in database and optionally delete them"

    def add_arguments(self, parser):
        parser.add_argument(
            "--delete",
            action="store_true",
            dest="delete",
            default=False,
            help="Delete stale files instead of only showing them",
        )

    @staticmethod
    def get_paths(storage):
        paths = {}
        for num, path in enumerate(storage_walk_paths(storage)):
            size = storage.size(path)
            paths[path] = size
            if num % 100 == 0:
                print(".", end="", flush=True)
            # print(path, size / 2 ** 20)
        return paths

    @staticmethod
    def get_image_paths() -> set[str]:
        paths = set()
        for image in Image.objects.all():
            paths.add(image.file.name)
            for rendition in image.renditions.all():
                paths.add(rendition.file.name)
        return paths

    def get_models_paths(self):
        paths = self.get_image_paths()
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
        print(f"stale s3 size: {sum(stale_s3.values()) / 2 ** 20} Mb")

        print("stale locale")
        locale_paths = self.get_paths(default_storage)
        stale_locale = {}
        for path, size in locale_paths.items():
            if path not in paths_from_models:
                print(path)
                stale_locale[path] = size
        print(f"stale locale size: {sum(stale_locale.values()) / 2 ** 20} Mb")

        if options["delete"]:
            # for path in stale_s3.keys():
            #     s3.delete(path)
            for path in stale_locale.keys():
                default_storage.delete(path)
