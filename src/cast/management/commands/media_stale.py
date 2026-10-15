from argparse import ArgumentParser
from datetime import datetime, timedelta
from typing import Any

from django.apps import apps
from django.core.files.storage import Storage
from django.core.management.base import BaseCommand, CommandError
from django.db import models
from django.utils import timezone
from wagtail.images.models import Image, Rendition

from ... import appsettings
from ...utils import storage_walk_paths
from .storage_backend import get_production_and_backup_storage

MANAGED_MEDIA_PREFIXES = (
    "cast_audio/",
    "cast_files/",
    "cast_images/",
    "cast_transcript/",
    "cast_transcript_corrections/",
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

    def add_arguments(self, parser: ArgumentParser) -> None:
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
    def get_paths(storage: Storage) -> dict[str, int]:
        paths: dict[str, int] = {}
        for num, path in enumerate(storage_walk_paths(storage)):
            size = storage.size(path)
            paths[path] = size
            if num % 100 == 0:
                print(".", end="", flush=True)
            # print(path, size / 2 ** 20)
        return paths

    @staticmethod
    def get_cast_file_field_paths() -> set[str]:
        paths: set[str] = set()
        for model in apps.get_app_config("cast").get_models():
            file_fields = [field for field in model._meta.get_fields() if isinstance(field, models.FileField)]
            if not file_fields:
                continue
            for instance in model._default_manager.all().iterator():
                for field in file_fields:
                    field_file = getattr(instance, field.name)
                    if field_file and field_file.name:
                        paths.add(field_file.name)
        return paths

    @staticmethod
    def get_image_paths() -> set[str]:
        paths: set[str] = set()
        for image in Image.objects.all():
            paths.add(image.file.name)
            for rendition in image.renditions.all():
                paths.add(rendition.file.name)
        return paths

    def get_models_paths(self) -> set[str]:
        paths = self.get_image_paths()
        paths.update(self.get_cast_file_field_paths())
        return paths

    @staticmethod
    def is_referenced(path: str) -> bool:
        for model in (*apps.get_app_config("cast").get_models(), Image, Rendition):
            for field in model._meta.get_fields():
                if isinstance(field, models.FileField):
                    if model._default_manager.filter(**{field.name: path}).exists():
                        return True
        return False

    @staticmethod
    def is_old_enough(storage: Storage, path: str, cutoff: datetime) -> bool:
        # Naive times are in the Django default timezone, regardless of the active one.
        default_timezone = timezone.get_default_timezone()
        if timezone.is_naive(cutoff):
            cutoff = timezone.make_aware(cutoff, default_timezone)
        timestamps = []
        for get_time in (storage.get_modified_time, storage.get_created_time):
            try:
                timestamp = get_time(path)
            except Exception:
                # Storage backends use different exceptions for unavailable metadata.
                continue
            if timestamp is None:
                continue
            if timezone.is_naive(timestamp):
                timestamp = timezone.make_aware(timestamp, default_timezone)
            timestamps.append(timestamp)
        return bool(timestamps) and max(timestamps) <= cutoff

    def handle(self, *args: Any, **options: Any) -> None:
        production_storage, _ = get_production_and_backup_storage()
        paths_from_models = self.get_models_paths()
        min_age_days = appsettings.CAST_MEDIA_STALE_MIN_AGE_DAYS
        if type(min_age_days) is not int or min_age_days < 0:
            raise CommandError("CAST_MEDIA_STALE_MIN_AGE_DAYS must be a non-negative integer")
        cutoff = timezone.now() - timedelta(days=min_age_days)
        skipped_too_young = 0
        skipped_newly_referenced = 0
        deleted = 0

        print("stale production")
        production_paths = self.get_paths(production_storage)
        stale_production: dict[str, int] = {}
        for path, size in production_paths.items():
            if not self.is_managed_media_path(path):
                continue
            if path not in paths_from_models:
                if not self.is_old_enough(production_storage, path, cutoff):
                    skipped_too_young += 1
                    print(f"Skipped too young or unknown age: {path}")
                    continue
                print(path)
                stale_production[path] = size
        print(f"stale production size: {sum(stale_production.values()) / 2**20} Mb")

        if options["delete"]:
            for path in stale_production.keys():
                if not self.is_old_enough(production_storage, path, cutoff):
                    skipped_too_young += 1
                    print(f"Skipped too young or unknown age: {path}")
                    continue
                if self.is_referenced(path):
                    skipped_newly_referenced += 1
                    print(f"Skipped newly referenced: {path}")
                    continue
                production_storage.delete(path)
                deleted += 1
        print(
            f"media_stale: candidates={len(stale_production)} deleted={deleted} "
            f"skipped-too-young={skipped_too_young} skipped-newly-referenced={skipped_newly_referenced}"
        )
