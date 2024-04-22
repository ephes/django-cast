from collections.abc import Iterable

from django.db import models
from model_utils.models import TimeStampedModel
from wagtail.images.models import Image

from cast.models.image_renditions import (
    create_missing_renditions_for_images,
    get_obsolete_and_missing_rendition_strings,
)


class Gallery(TimeStampedModel):
    images: models.ManyToManyField = models.ManyToManyField(Image)  # FIXME mypy are you ok?
    post_context_key = "gallery"

    @property
    def image_ids(self) -> set[int]:
        return {i.pk for i in self.images.all()}

    def create_renditions(self):
        images_with_type = [("gallery", image) for image in self.images.all()]
        _, missing_renditions = get_obsolete_and_missing_rendition_strings(images_with_type)
        create_missing_renditions_for_images(missing_renditions)


def get_or_create_gallery(image_ids: Iterable[int]) -> Gallery | None:
    candidate_images = Image.objects.filter(id__in=image_ids)  # FIXME filter permissions
    if candidate_images.count() == 0:
        return None
    filtered_image_ids = [ci.id for ci in candidate_images]
    gallery_to_image_ids = {}
    # FIXME filter permissions - fetch only images / galleries that
    # this user has permission to view
    candidate_galleries = Gallery.objects.filter(images__in=filtered_image_ids).prefetch_related("images")
    for candidate_gallery in candidate_galleries:
        gallery_to_image_ids[frozenset(i.id for i in candidate_gallery.images.all())] = candidate_gallery
    gallery = gallery_to_image_ids.get(frozenset(filtered_image_ids))
    if gallery is None:
        gallery = Gallery.objects.create()
        gallery.images.add(*filtered_image_ids)
    return gallery
