"""Read-only inventory of GPS-bearing Wagtail originals."""

from typing import Any

from django.core.management.base import BaseCommand, CommandError
from PIL import Image
from wagtail.images import get_image_model
from willow.image import Image as WillowImage, UnrecognisedImageFormatError

from cast.image_metadata import has_gps


class Command(BaseCommand):
    help = "List image IDs and original storage names containing EXIF GPS; never modify files or rows."

    def handle(self, *args: Any, **options: Any) -> None:
        failed = 0
        found = 0
        for image in get_image_model().objects.order_by("pk").iterator():
            try:
                with image.file.storage.open(image.file.name, "rb") as original:
                    if WillowImage.open(original).format_name == "svg":
                        continue
                    with Image.open(original) as raster:
                        if has_gps(raster):
                            self.stdout.write(f"{image.pk}\t{image.file.name}")
                            found += 1
            except (
                OSError,
                ValueError,
                SyntaxError,
                Image.DecompressionBombError,
                UnrecognisedImageFormatError,
            ) as exc:
                failed += 1
                self.stderr.write(f"Could not inspect image {image.pk} ({image.file.name}): {exc}")
        self.stdout.write(f"GPS images: {found}; unreadable images: {failed}")
        if failed:
            raise CommandError("GPS report is incomplete; see unreadable images above.")
