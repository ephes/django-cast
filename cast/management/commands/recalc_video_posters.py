from django.core.management.base import BaseCommand

from ...models import Video


class Command(BaseCommand):
    help = "recalc the poster images for videos from the videos"

    def handle(self, *args, **options):
        for video in Video.objects.all():
            # orig = video.original
            video.create_poster()
            video.save(poster=False)
            # break
