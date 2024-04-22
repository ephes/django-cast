from argparse import RawTextHelpFormatter

from django.core.management.base import BaseCommand
from rich.progress import track
from wagtail.images.models import Image, Rendition

from ...models import Blog, Post
from ...models.image_renditions import get_obsolete_and_missing_rendition_strings


class Command(BaseCommand):
    help = """
What does it mean to sync the renditions for all posts?
    - create missing renditions
    - delete obsolete renditions

Optional arguments:
    --post-slug: sync renditions for a specific post
    --blog-slug: sync renditions for posts in a specific blog

By default all posts are synced.
    """

    def create_parser(self, *args, **kwargs):
        parser = super().create_parser(*args, **kwargs)
        parser.formatter_class = RawTextHelpFormatter
        return parser

    def add_arguments(self, parser):
        # Optional argument for a post slug
        parser.add_argument("--post-slug", type=str, help="Sync renditions for a specific post")
        # Optional argument for a blog slug
        parser.add_argument("--blog-slug", type=str, help="Sync renditions for posts in a specific blog")

    def handle(self, *args, **options):
        post_slug = options.get("post_slug")
        blog_slug = options.get("blog_slug")

        if post_slug is not None:
            posts_queryset = Post.objects.filter(slug=post_slug)
        elif blog_slug is not None:
            blog = Blog.objects.get(slug=blog_slug)
            posts_queryset = Post.objects.descendant_of(blog)
        else:
            posts_queryset = Post.objects.all()

        posts_queryset = posts_queryset.prefetch_related("images", "galleries__images")
        all_images = Post.get_all_images_from_queryset(posts_queryset)
        obsolete_renditions, missing_renditions = get_obsolete_and_missing_rendition_strings(all_images)
        Rendition.objects.filter(id__in=obsolete_renditions).delete()
        missing_renditions = list(missing_renditions.items())
        print("len missing renditions: ", len(missing_renditions))
        for image_id, filter_specs in track(missing_renditions, description="create missing renditions"):
            image = Image.objects.get(id=image_id)
            image.get_renditions(*filter_specs)
