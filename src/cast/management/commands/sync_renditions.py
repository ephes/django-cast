from argparse import ArgumentParser, RawTextHelpFormatter
from typing import Any

from django.core.files.storage import Storage
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction
from rich.progress import track
from wagtail.images.models import Filter, Image, Rendition

from ...models import Blog, Post
from ...models.image_renditions import (
    RenditionCacheInvalidationError,
    create_rendition_with_receipt,
    discard_unreferenced_rendition_files,
    get_obsolete_and_missing_rendition_strings,
    repair_missing_rendition_files,
)


class Command(BaseCommand):
    help = """
What does it mean to sync the renditions for all posts?
    - create missing renditions
    - delete previous/next gallery thumbnail sRGB-policy counterpart renditions

Optional arguments:
    --post-slug: sync renditions for a specific post
    --blog-slug: sync renditions for posts in a specific blog

When both selectors are supplied, only matching posts in that blog are synced.
Explicitly empty selections fail before media changes.
By default all posts are synced.
    """

    def create_parser(self, prog_name: str, subcommand: str, **kwargs: Any) -> CommandParser:
        parser = super().create_parser(prog_name, subcommand, **kwargs)
        parser.formatter_class = RawTextHelpFormatter
        return parser

    def add_arguments(self, parser: ArgumentParser) -> None:
        # Optional argument for a post slug
        parser.add_argument("--post-slug", type=str, help="Sync renditions for a specific post")
        # Optional argument for a blog slug
        parser.add_argument("--blog-slug", type=str, help="Sync renditions for posts in a specific blog")

    def handle(self, *args: Any, **options: Any) -> None:
        post_slug = options.get("post_slug")
        blog_slug = options.get("blog_slug")

        posts_queryset = Post.objects.all()
        if blog_slug is not None:
            matching_blogs = list(Blog.objects.filter(slug=blog_slug).order_by("pk")[:2])
            if not matching_blogs:
                raise CommandError(f"No blog found for slug '{blog_slug}'.")
            if len(matching_blogs) > 1:
                raise CommandError(
                    f"Multiple blogs found for slug '{blog_slug}'. Use a unique slug or target posts more explicitly."
                )
            posts_queryset = Post.objects.descendant_of(matching_blogs[0])
        if post_slug is not None:
            posts_queryset = posts_queryset.filter(slug=post_slug)
        if (post_slug is not None or blog_slug is not None) and not posts_queryset.exists():
            raise CommandError("No posts found for the supplied selectors.")

        posts_queryset = posts_queryset.prefetch_related("images", "galleries__images")
        all_images = Post.get_all_images_from_queryset(posts_queryset)
        obsolete_renditions, missing_renditions = get_obsolete_and_missing_rendition_strings(
            all_images, check_files=True
        )
        missing_rendition_items = list(missing_renditions.items())
        print("len missing renditions: ", len(missing_rendition_items))
        for image_id, filter_specs in track(missing_rendition_items, description="create missing renditions"):
            image = Image.objects.get(id=image_id)
            using = image._state.db or "default"
            written: list[tuple[Storage, str]] = []
            try:
                with transaction.atomic(using=using):
                    present = repair_missing_rendition_files(
                        image, filter_specs, written=written, strict_cache_invalidation=True
                    )
                    clean_filter = getattr(image, "clean_filter_for_svg", lambda value: value)
                    required = {clean_filter(Filter(spec)).spec for spec in filter_specs}
                    for filter_spec in required - present:
                        create_rendition_with_receipt(image, Filter(filter_spec), written)
                    # Read the writer's rows directly, never an old shared cache entry.
                    rows = {r.filter_spec: r for r in image.renditions.filter(filter_spec__in=required)}
                    for filter_spec in required:
                        rendition = rows.get(filter_spec)
                        if (
                            rendition is None
                            or not rendition.file.name
                            or not rendition.file.storage.exists(rendition.file.name)
                        ):
                            raise CommandError(
                                f"Required replacement {filter_spec} for image {image_id} was not saved."
                            )
            except RenditionCacheInvalidationError as error:
                raise CommandError(str(error)) from error
            except BaseException:
                discard_unreferenced_rendition_files(written, using=using)
                raise
        # Keep all old counterparts until every planned replacement is usable.
        Rendition.objects.filter(id__in=obsolete_renditions).delete()
