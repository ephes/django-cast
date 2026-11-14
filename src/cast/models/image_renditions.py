from collections import defaultdict
from collections.abc import Iterable, Iterator
from typing import TYPE_CHECKING, TypeAlias

from django.db import router, transaction
from django.db.models import Prefetch
from wagtail.images.models import Filter, Image, Rendition

from ..renditions import ImageType, RenditionFilters, get_srgb_counterpart_filter_spec

ImageIdSet = set[int]
RenditionStringsByImageId = dict[int, set[str]]
ObsoleteAndMissing = tuple[ImageIdSet, RenditionStringsByImageId]
ImagesWithType: TypeAlias = Iterable[tuple[ImageType, Image]]

if TYPE_CHECKING:
    from cast.models import Post


def get_gallery_thumbnail_srgb_counterpart_filterstrings(image: Image) -> Iterator[tuple[int, str]]:
    """Return sRGB-policy counterpart filter strings for a gallery image's thumbnail slot."""
    rendition_filters = RenditionFilters.from_wagtail_image_with_type(image, "gallery")
    if len(rendition_filters.slots) < 2:
        return
    thumbnail_slot = rendition_filters.slots[1]
    for filters_for_format in rendition_filters.filters[thumbnail_slot].values():
        for rendition_filter in filters_for_format:
            filter_spec = rendition_filter.get_wagtail_filter_str(rendition_filters.original_format)
            counterpart = get_srgb_counterpart_filter_spec(filter_spec)
            assert counterpart is not None
            yield image.pk, counterpart


def get_all_filterstrings(images_with_type: ImagesWithType) -> Iterator[tuple[int, str]]:
    """
    For an iterator of images with types, return an iterator of all image ids and filter strings that
    are required for the images.
    """
    for image_type, image in images_with_type:
        rendition_filters = RenditionFilters.from_wagtail_image_with_type(image, image_type)
        filter_strings_to_fetch = rendition_filters.filter_strings
        for filter_string in filter_strings_to_fetch:
            yield image.pk, filter_string


def get_obsolete_and_missing_rendition_strings(
    images_with_type: ImagesWithType, *, using: str | None = None
) -> ObsoleteAndMissing:
    """
    Get all obsolete and missing rendition strings from a queryset of posts.
    """
    images_with_type = list(images_with_type)
    aliases = {image._state.db for _, image in images_with_type if hasattr(image, "_state")}
    if using is None:
        if len(aliases) > 1:
            raise ValueError("Rendition inventory requires images from one database.")
        using = next(iter(aliases), None)
    required_renditions: set[tuple[int, str]] = set()
    srgb_counterpart_renditions: set[tuple[int, str]] = set()
    for image_type, image in images_with_type:
        required_renditions.update(get_all_filterstrings([(image_type, image)]))
        if image_type == "gallery":
            srgb_counterpart_renditions.update(get_gallery_thumbnail_srgb_counterpart_filterstrings(image))
    all_image_ids = {image_id for image_id, filter_string in required_renditions}
    renditions = Rendition.objects if using is None else Rendition.objects.using(using)
    renditions_queryset = renditions.filter(image__in=all_image_ids)
    existing_rendition_to_id = {
        (image_id, filter_spec): pk
        for pk, image_id, filter_spec in renditions_queryset.values_list("pk", "image_id", "filter_spec")
    }
    existing_renditions = set(existing_rendition_to_id.keys())
    # Inspect only required keys, once per storage/key even for repeated images.
    exists: dict[tuple[int, str], bool] = {}
    for rendition in renditions_queryset:
        key = (rendition.image_id, rendition.filter_spec)
        if key in required_renditions:
            storage_key = (id(rendition.file.storage), rendition.file.name)
            if storage_key not in exists:
                exists[storage_key] = bool(rendition.file.name) and rendition.file.storage.exists(rendition.file.name)
            if not exists[storage_key]:
                existing_renditions.discard(key)
    obsolete_renditions_unfiltered = existing_renditions - required_renditions

    # Only remove known predecessor/successor specs from django-cast's gallery thumbnail sRGB policy.
    # Generic Wagtail filter specs such as ``width-400`` do not encode ownership and must be preserved.
    obsolete_renditions = obsolete_renditions_unfiltered & srgb_counterpart_renditions
    obsolete_rendition_pks = {
        existing_rendition_to_id[(image_id, filter_spec)] for image_id, filter_spec in obsolete_renditions
    }

    # build missing renditions aggregated by image id
    missing_renditions = required_renditions - existing_renditions
    missing_renditions_by_image_id: dict[int, set[str]] = {}  # why mypy?
    for image_id, filter_spec in missing_renditions:
        missing_renditions_by_image_id.setdefault(image_id, set()).add(filter_spec)
    return obsolete_rendition_pks, missing_renditions_by_image_id


def get_all_images_from_posts(posts: Iterator["Post"]) -> ImagesWithType:
    """
    Get all images from a queryset of posts.
    """
    for post in posts:
        yield from post.get_all_images()


def repair_missing_rendition_files(image: Image, filter_specs: Iterable[str]) -> None:
    """Repair broken files without scheduling deletion of a reused storage key.

    The caller owns the transaction. Preserve existing rows and usable policy
    counterparts; Wagtail's public generation and cache APIs handle the file.
    """
    for rendition in image.renditions.select_for_update().filter(filter_spec__in=filter_specs):
        if not rendition.file.name or not rendition.file.storage.exists(rendition.file.name):
            with image.generate_rendition_file(Filter(rendition.filter_spec)) as generated:
                rendition.file.save(generated.name, generated, save=False)
            name = rendition.file.name
            try:
                if not rendition.file.storage.exists(name):
                    raise OSError("Required rendition file was not saved.")
                rendition.save(using=image._state.db, update_fields=["file"])
            except Exception:
                rendition.file.storage.delete(name)
                raise
            rendition.purge_from_cache()


def create_missing_renditions_for_images(
    missing_renditions: RenditionStringsByImageId, *, using: str | None = None
) -> None:
    """Create required renditions on the source database without shared cache collisions."""
    using = using or router.db_for_write(Image)
    images = Image.objects.using(using).prefetch_related(
        Prefetch("renditions", queryset=Rendition.objects.using(using))
    )
    for image_id, filter_specs in missing_renditions.items():
        image = images.get(id=image_id)
        with transaction.atomic(using=using):
            repair_missing_rendition_files(image, filter_specs)
            for filter_string in filter_specs:
                clean_filter = getattr(image, "clean_filter_for_svg", lambda value: value)
                # Public single-rendition API uses the explicitly bound related
                # manager; bulk creation and the shared cache can lose the alias.
                rendition = image.create_rendition(clean_filter(Filter(filter_string)))
                if not rendition.file.storage.exists(rendition.file.name):
                    raise OSError("Required rendition file was not saved.")


def create_missing_renditions_for_posts(posts: Iterable["Post"]) -> None:
    """Create required renditions, grouping source instances by database."""
    grouped: dict[str, list[tuple[ImageType, Image]]] = defaultdict(list)
    for image_type, image in get_all_images_from_posts(iter(posts)):
        using = image._state.db or router.db_for_write(Image, instance=image)
        grouped[using].append((image_type, image))
    for using, images in grouped.items():
        _, missing = get_obsolete_and_missing_rendition_strings(images, using=using)
        create_missing_renditions_for_images(missing, using=using)
