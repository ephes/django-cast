from django.core.management.base import BaseCommand
from wagtail.images.models import Image

from ...models import File, Video
from ...utils import storage_walk_paths
from .storage_backend import get_production_and_backup_storage


class Command(BaseCommand):
    help = (
        "show media files which are in the production storage backend, but not in database and optionally delete them "
        "(requires Django >= 4.2 and production and backup storage configured)"
    )

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
        production_storage, _ = get_production_and_backup_storage()
        paths_from_models = self.get_models_paths()

        print("stale production")
        production_paths = self.get_paths(production_storage)
        stale_production = {}
        for path, size in production_paths.items():
            if path not in paths_from_models:
                print(path)
                stale_production[path] = size
        print(f"stale production size: {sum(stale_production.values()) / 2**20} Mb")

        if options["delete"]:
            for path in stale_production.keys():
                production_storage.delete(path)
