import hashlib
from collections.abc import Iterable

from django.db import models
from django.db.models.signals import m2m_changed
from django.db.models.signals import post_delete
from django.db.models.signals import pre_delete
from django.dispatch import receiver
from model_utils.models import TimeStampedModel
from wagtail.images.models import Image

from cast.models.image_renditions import (
    create_missing_renditions_for_images,
    get_obsolete_and_missing_rendition_strings,
)


class Gallery(TimeStampedModel):
    """A collection of images displayed as thumbnails with a modal full-size view.

    Galleries are created automatically via ``get_or_create_gallery()`` and
    are deduplicated so the same set of images always maps to one gallery.
    """

    images: models.ManyToManyField = models.ManyToManyField(Image)  # FIXME mypy are you ok?
    signature = models.CharField(blank=True, db_index=True, default="", editable=False, max_length=64)
    post_context_key = "gallery"

    @property
    def image_ids(self) -> set[int]:
        return {i.pk for i in self.images.all()}

    @staticmethod
    def build_signature(image_ids: Iterable[int]) -> str:
        normalized_image_ids = sorted(set(image_ids))
        if not normalized_image_ids:
            return ""
        signature_input = ",".join(str(image_id) for image_id in normalized_image_ids)
        return hashlib.sha256(signature_input.encode("ascii")).hexdigest()

    def refresh_signature(self) -> str:
        signature = self.build_signature(self.images.values_list("id", flat=True))
        type(self).objects.filter(pk=self.pk).update(signature=signature)
        self.signature = signature
        return signature

    def create_renditions(self):
        images_with_type = [("gallery", image) for image in self.images.all()]
        _, missing_renditions = get_obsolete_and_missing_rendition_strings(images_with_type)
        create_missing_renditions_for_images(missing_renditions)


def get_or_create_gallery(image_ids: Iterable[int]) -> Gallery | None:
    filtered_image_ids = list(
        Image.objects.filter(id__in=image_ids).values_list("id", flat=True)  # FIXME filter permissions
    )
    if not filtered_image_ids:
        return None
    signature = Gallery.build_signature(filtered_image_ids)
    gallery = Gallery.objects.filter(signature=signature).order_by("pk").first()
    if gallery is None:
        gallery = Gallery.objects.create(signature=signature)
        gallery.images.add(*filtered_image_ids)
    return gallery


@receiver(m2m_changed, sender=Gallery.images.through)
def refresh_gallery_signature_on_image_change(sender, instance, action, **kwargs):
    if action in {"post_add", "post_clear", "post_remove"}:
        instance.refresh_signature()


@receiver(pre_delete, sender=Image)
def cache_gallery_ids_before_image_delete(sender, instance, **kwargs):
    instance.gallery_ids_to_refresh = list(instance.gallery_set.values_list("pk", flat=True))


@receiver(post_delete, sender=Image)
def refresh_gallery_signatures_after_image_delete(sender, instance, **kwargs):
    gallery_ids = getattr(instance, "gallery_ids_to_refresh", [])
    for gallery in Gallery.objects.filter(pk__in=gallery_ids):
        gallery.refresh_signature()
