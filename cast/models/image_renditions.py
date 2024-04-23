from collections.abc import Iterator
from typing import TYPE_CHECKING, TypeAlias

from wagtail.images.models import Image, Rendition

from ..renditions import ImageType, RenditionFilters

ImageIdSet = set[int]
RenditionStringsByImageId = dict[int, set[str]]
ObsoleteAndMissing = tuple[ImageIdSet, RenditionStringsByImageId]
ImagesWithType: TypeAlias = Iterator[tuple[ImageType, Image]]

if TYPE_CHECKING:
    from cast.models import Post


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
    required_renditions = set(get_all_filterstrings(images_with_type))
    all_image_ids = {image_id for image_id, filter_string in required_renditions}
    renditions_queryset = Rendition.objects.filter(image__in=all_image_ids)
    existing_rendition_to_id = {
        (image_id, filter_spec): pk
        for pk, image_id, filter_spec in renditions_queryset.values_list("pk", "image_id", "filter_spec")
    }
    existing_renditions = set(existing_rendition_to_id.keys())
    obsolete_renditions_unfiltered = existing_renditions - required_renditions

    # remove wagtail generated renditions from obsolete_renditions
    obsolete_renditions = set()
    wagtail_filter_specs = {"max-165x165", "max-800x600"}
    for image_id, filter_spec in obsolete_renditions_unfiltered:
        if filter_spec not in wagtail_filter_specs:
            obsolete_renditions.add((image_id, filter_spec))
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
