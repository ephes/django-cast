from django.core.management.base import BaseCommand
from django.core.files.storage import get_storage_class

from cast.utils import storage_walk_paths


class Command(BaseCommand):
    help = "shows size of media on s3"

    def show_usage(self, paths):
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
        unit = 2 ** 20  # MB
        print("video usage: {}".format(video / unit))
        print("image usage: {}".format(image / unit))
        print("misc  usage: {}".format(misc / unit))
        print("total usage: {}".format(sum(paths.values()) / unit))

    def handle(self, *args, **options):
        s3 = get_storage_class("storages.backends.s3boto3.S3Boto3Storage")()
        paths = {}
        for path in storage_walk_paths(s3):
            size = s3.size(path)
            paths[path] = size
            print(path, size / 2 ** 20)
        self.show_usage(paths)
