from django.core.management.base import BaseCommand
from django.db import models
from wagtail.images.models import Image

from ...utils import storage_walk_paths
from .storage_backend import get_production_and_backup_storage


MANAGED_MEDIA_PREFIXES = (
    "cast_audio/",
    "cast_files/",
    "cast_images/",
    "cast_transcript/",
    "cast_transcript_speakers/",
    "cast_videos/",
    "cast_voice_references/",
    "images/",
    "original_images/",
)


class Command(BaseCommand):
    help = (
        "show media files which are in the production storage backend, but not in database and optionally delete them "
        "(requires production and backup storage backends configured)"
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
    def is_managed_media_path(path: str) -> bool:
        normalized_path = path.lstrip("/")
        return any(normalized_path.startswith(prefix) for prefix in MANAGED_MEDIA_PREFIXES)

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
    def get_cast_file_field_paths() -> set[str]:
        paths = set()
        from django.apps import apps

        for model in apps.get_app_config("cast").get_models():
            file_fields = [field for field in model._meta.get_fields() if isinstance(field, models.FileField)]
            if not file_fields:
                continue
            for instance in model.objects.all().iterator():
                for field in file_fields:
                    field_file = getattr(instance, field.name)
                    if field_file and field_file.name:
                        paths.add(field_file.name)
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
        paths.update(self.get_cast_file_field_paths())
        return paths

    def handle(self, *args, **options):
        production_storage, _ = get_production_and_backup_storage()
        paths_from_models = self.get_models_paths()

        print("stale production")
        production_paths = self.get_paths(production_storage)
        stale_production = {}
        for path, size in production_paths.items():
            if not self.is_managed_media_path(path):
                continue
            if path not in paths_from_models:
                print(path)
                stale_production[path] = size
        print(f"stale production size: {sum(stale_production.values()) / 2**20} Mb")

        if options["delete"]:
            for path in stale_production.keys():
                production_storage.delete(path)
