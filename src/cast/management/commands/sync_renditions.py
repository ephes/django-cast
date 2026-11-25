from argparse import ArgumentParser, RawTextHelpFormatter
from collections import defaultdict
from collections.abc import Iterator
from typing import Any, NamedTuple

from django.core.files.storage import Storage
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction
from django.db.models import F, QuerySet
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
from ...renditions import ImageType, get_srgb_counterpart_filter_spec

BATCH_SIZE = 200
ImageIdentity = tuple[str, int, int, int | None, int | None, int | None, int | None]


def image_batches(images: QuerySet[Image], ids: list[int]) -> Iterator[dict[int, Image]]:
    for start in range(0, len(ids), BATCH_SIZE):
        requested = ids[start : start + BATCH_SIZE]
        batch = images.in_bulk(requested)
        if missing := set(requested) - batch.keys():
            raise CommandError(f"Images disappeared during rendition synchronization: {sorted(missing)}.")
        yield batch


class RenditionIdentity(NamedTuple):
    pk: int
    spec: str
    focal_key: str
    name: str

    @classmethod
    def from_row(cls, rendition: Rendition) -> "RenditionIdentity":
        return cls(rendition.pk, rendition.filter_spec, rendition.focal_point_key, rendition.file.name)


def source_identity(image: Image) -> ImageIdentity:
    return (
        image.file.name,
        image.width,
        image.height,
        image.focal_point_x,
        image.focal_point_y,
        image.focal_point_width,
        image.focal_point_height,
    )


def file_exists(rendition: Rendition) -> bool:
    return bool(rendition.file.name) and rendition.file.storage.exists(rendition.file.name)


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

        using = posts_queryset.db
        posts = posts_queryset.using(using).prefetch_related("images", "galleries__images")
        roles: dict[int, set[ImageType]] = defaultdict(set)
        for role, image in Post.get_all_images_from_queryset(posts.iterator(chunk_size=BATCH_SIZE)):
            roles[image.pk].add(role)

        images = Image.objects.using(using)
        obsolete_by_image: dict[int, list[RenditionIdentity]] = defaultdict(list)
        renditions = Rendition.objects.using(using)
        missing_renditions: dict[int, set[str]] = {}
        for batch in image_batches(images, sorted(roles)):
            obsolete, missing = get_obsolete_and_missing_rendition_strings(
                ((role, image) for image_id, image in batch.items() for role in sorted(roles[image_id])),
                using=using,
                check_files=True,
            )
            for row in renditions.filter(pk__in=obsolete).iterator(chunk_size=BATCH_SIZE):
                obsolete_by_image[row.image_id].append(RenditionIdentity.from_row(row))
            missing_renditions.update(missing)

        print("len missing renditions: ", len(missing_renditions))
        work_ids = missing_renditions.keys() | obsolete_by_image.keys()
        batches = image_batches(images, sorted(work_ids))
        # Keep only identities after verification. All repairs must finish
        # before any old counterpart is retired.
        verified: dict[int, tuple[ImageIdentity, list[tuple[RenditionIdentity, RenditionIdentity]]]] = {}
        for image in track(
            (image for batch in batches for image in batch.values()),
            total=len(work_ids),
            description="create missing renditions",
        ):
            image_id = image.pk
            filter_specs = missing_renditions.get(image_id, set())
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
                    pairs = []
                    for old in obsolete_by_image.get(image_id, ()):
                        counterpart = get_srgb_counterpart_filter_spec(old.spec)
                        assert counterpart is not None
                        pairs.append((old, clean_filter(Filter(counterpart)).spec))
                    required.update(spec for _, spec in pairs)
                    rows = {
                        r.filter_spec: r
                        for r in renditions.filter(image_id=image_id, filter_spec__in=required)
                        if r.focal_point_key == Filter(r.filter_spec).get_cache_key(image)
                    }
                    for filter_spec in required:
                        rendition = rows.get(filter_spec)
                        if rendition is None or not file_exists(rendition):
                            raise CommandError(
                                f"Required replacement {filter_spec} for image {image_id} was not saved."
                            )
                    if pairs:
                        verified[image_id] = (
                            source_identity(image),
                            [(old, RenditionIdentity.from_row(rows[spec])) for old, spec in pairs],
                        )
            except RenditionCacheInvalidationError as error:
                raise CommandError(str(error)) from error
            except BaseException:
                discard_unreferenced_rendition_files(written, using=using)
                raise

        conflicts = 0
        for image_id, (source, pairs) in verified.items():
            with transaction.atomic(using=using):
                image_query = images.filter(pk=image_id)
                # Lock the source on SQLite as well as databases with row locks.
                locked = image_query.update(title=F("title"))
                current = image_query.get() if locked else None
                rows_by_id = (
                    renditions.select_for_update()
                    .filter(image_id=image_id)
                    .in_bulk({identity.pk for pair in pairs for identity in pair})
                )
                for old, replacement in pairs:
                    old_row = rows_by_id.get(old.pk)
                    new_row = rows_by_id.get(replacement.pk)
                    if (
                        current is None
                        or source_identity(current) != source
                        or old_row is None
                        or RenditionIdentity.from_row(old_row) != old
                        or new_row is None
                        or RenditionIdentity.from_row(new_row) != replacement
                        # Wagtail's deletion hook would also delete a shared file.
                        or old.name == replacement.name
                        or not file_exists(new_row)
                    ):
                        conflicts += 1
                        self.stderr.write(f"Rendition retirement conflict for image {image_id}, rendition {old.pk}.")
                        continue
                    old_row.delete(using=using)
        if conflicts:
            raise CommandError(f"{conflicts} rendition retirement conflict(s). Rerun sync_renditions.")
