import logging

from django.core.management.base import BaseCommand

from ...models import Post

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "add links between blogpost and media objects"

    def handle(self, *args, **options):
        posts = list(Post.objects.all().order_by("-created"))
        for post in posts:
            logger.info("-----------------")
            post.add_missing_media_objects()
