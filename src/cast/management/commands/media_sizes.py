from django.core.management.base import BaseCommand

from cast.utils import storage_walk_paths

from .storage_backend import get_production_and_backup_storage


class Command(BaseCommand):
    help = (
        "show size of media files on production storage backend"
        "(requires Django >= 4.2 and production and backup storage configured)"
    )

    @staticmethod
    def show_usage(paths):
        video_endings = {"mov", "mp4"}
        image_endings = {"jpg", "jpeg", "png"}
        image, video, misc = 0, 0, 0
        for path, size in paths.items():
            ending = path.split(".")[-1].lower()
            if ending in video_endings:
                video += size
            elif ending in image_endings:
                image += size
            else:
                misc += size
        unit = 2**20  # MB
        print(f"video usage: {video / unit}")
        print(f"image usage: {image / unit}")
        print(f"misc  usage: {misc / unit}")
        print(f"total usage: {sum(paths.values()) / unit}")

    @staticmethod
    def get_paths_with_sizes_for(storage_backend):
        paths = {}
        for path in storage_walk_paths(storage_backend):
            size = storage_backend.size(path)
            paths[path] = size
            print(path, size / 2**20)
        return paths

    def handle(self, *args, **options):
        production, _ = get_production_and_backup_storage()
        paths = self.get_paths_with_sizes_for(production)
        self.show_usage(paths)
