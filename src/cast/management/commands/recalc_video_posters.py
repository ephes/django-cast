from typing import Any

from django.core.management.base import BaseCommand, CommandError
from rich.progress import track

from ...models import Video


class Command(BaseCommand):
    help = "recalc the poster images for videos from the videos"

    def handle(self, *args: Any, **options: Any) -> None:
        total = 0
        errors = 0
        videos = Video.objects.all().order_by("pk")
        for video in track(videos, description="Recalculating video posters"):
            total += 1
            try:
                video.publish_missing_poster()
            except Exception:
                errors += 1
                self.stderr.write(f"error recalculating poster for video {video.pk}: generation/publication failed")
        self.stdout.write(f"processed={total} errors={errors}")
        if errors:
            raise CommandError(f"{errors} of {total} video posters could not be recalculated")
