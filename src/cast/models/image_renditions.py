from collections.abc import Iterable, Iterator
from typing import TYPE_CHECKING, TypeAlias

from wagtail.images.models import Image, Rendition

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


def get_obsolete_and_missing_rendition_strings(images_with_type: ImagesWithType) -> ObsoleteAndMissing:
    """
    Get all obsolete and missing rendition strings from a queryset of posts.
    """
    required_renditions: set[tuple[int, str]] = set()
    srgb_counterpart_renditions: set[tuple[int, str]] = set()
    for image_type, image in images_with_type:
        required_renditions.update(get_all_filterstrings([(image_type, image)]))
        if image_type == "gallery":
            srgb_counterpart_renditions.update(get_gallery_thumbnail_srgb_counterpart_filterstrings(image))
    all_image_ids = {image_id for image_id, filter_string in required_renditions}
    renditions_queryset = Rendition.objects.filter(image__in=all_image_ids)
    existing_rendition_to_id = {
        (image_id, filter_spec): pk
        for pk, image_id, filter_spec in renditions_queryset.values_list("pk", "image_id", "filter_spec")
    }
    existing_renditions = set(existing_rendition_to_id.keys())
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


def create_missing_renditions_for_images(missing_renditions: RenditionStringsByImageId) -> None:
    """
    Create all required renditions for all images in the iterable posts.
    """
    for image_id, filter_specs in missing_renditions.items():
        image = Image.objects.get(id=image_id)
        for filter_string in filter_specs:
            image.get_rendition(filter_string).save()
        # for filter_string, rendition in image.get_renditions(*filter_specs).items():
        #     if rendition.pk is None:
        #         # this causes a lot of weird errors, probably a bug in Wagtail :(
        #         rendition.save()  # FIXME why do we need to save the rendition twice?


def create_missing_renditions_for_posts(posts: Iterator["Post"]) -> None:
    """
    Create all required renditions for all images in the iterable posts.
    """
    images_with_type = get_all_images_from_posts(posts)
    _, missing_renditions = get_obsolete_and_missing_rendition_strings(images_with_type)
    create_missing_renditions_for_images(missing_renditions)
