from django.core.management.base import BaseCommand
from rich.progress import track
from wagtail.images.models import Image

from ...models import Post


class Command(BaseCommand):
    """
    What does it mean to sync the renditions for all posts?

    - create missing renditions
    - delete obsolete renditions
    """

    help = "sync the renditions for all posts"

    def handle(self, *args, **options):
        posts_queryset = Post.objects.all().prefetch_related("images", "galleries__images")
        # posts_queryset = Post.objects.filter(
        #     slug="november-2023-11-20").prefetch_related("images", "galleries__images")
        all_images = Post.get_all_images_from_queryset(posts_queryset)
        print(all_images)
        obsolete_renditions, missing_renditions = Post.get_obsolete_and_missing_rendition_strings(all_images)
        # Rendition.objects.filter(id__in=obsolete_renditions).delete()
        missing_renditions = list(missing_renditions.items())
        print("len missing renditions: ", len(missing_renditions))
        for image_id, filter_specs in track(missing_renditions, description="create missing renditions"):
            image = Image.objects.get(id=image_id)
            image.get_renditions(*filter_specs)
