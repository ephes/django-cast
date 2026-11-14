import hashlib
from collections.abc import Iterable
from typing import Any

from django.db import connections, models, router, transaction
from django.db.models.signals import m2m_changed, post_delete, pre_delete
from django.dispatch import receiver
from model_utils.models import TimeStampedModel
from wagtail.images.models import Image

from cast.models.image_renditions import (
    ImagesWithType,
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

    def refresh_signature(self, using: str | None = None) -> str:
        using = using or self._state.db or router.db_for_write(type(self), instance=self)
        signature = self.build_signature(self.images.using(using).values_list("id", flat=True))
        type(self).objects.using(using).filter(pk=self.pk).update(signature=signature)
        self.signature = signature
        return signature

    def create_renditions(self) -> None:
        using = self._state.db or router.db_for_write(type(self), instance=self)
        images_with_type: ImagesWithType = [("gallery", image) for image in self.images.using(using).all()]
        _, missing_renditions = get_obsolete_and_missing_rendition_strings(images_with_type, using=using)
        create_missing_renditions_for_images(missing_renditions, using=using)


def get_or_create_gallery(image_ids: Iterable[int]) -> Gallery | None:
    return get_or_create_galleries([image_ids])[0]


def get_or_create_galleries(image_sets: Iterable[Iterable[int]]) -> list[Gallery | None]:
    """Resolve a body's galleries with one globally ordered set of image locks."""
    requested_sets = [set(image_ids) for image_ids in image_sets]
    all_ids = {image_id for image_ids in requested_sets for image_id in image_ids}
    if not all_ids:
        return [None for _ in requested_sets]
    using = router.db_for_write(Gallery)
    with transaction.atomic(using=using):
        existing_ids = set(
            Image.objects.using(using)
            .select_for_update(no_key=connections[using].features.has_select_for_no_key_update)
            .filter(id__in=all_ids)
            .order_by("pk")
            .values_list("id", flat=True)
        )
        galleries: list[Gallery | None] = []
        for requested_ids in requested_sets:
            effective_ids = requested_ids & existing_ids
            if not effective_ids:
                galleries.append(None)
                continue
            signature = Gallery.build_signature(effective_ids)
            gallery = Gallery.objects.using(using).filter(signature=signature).order_by("pk").first()
            if gallery is None:
                gallery = Gallery.objects.using(using).create(signature=signature)
                gallery.images.add(*sorted(effective_ids))
            galleries.append(gallery)
        return galleries


@receiver(m2m_changed, sender=Gallery.images.through)
def refresh_gallery_signature_on_image_change(
    sender: Any,
    instance: Gallery | Image,
    action: str,
    reverse: bool,
    pk_set: set[int] | None,
    using: str,
    **kwargs: Any,
) -> None:
    if not reverse:
        if action not in {"post_add", "post_clear", "post_remove"}:
            return
        assert isinstance(instance, Gallery)
        instance.refresh_signature(using=using)
        return

    assert isinstance(instance, Image)
    if action == "pre_clear":
        setattr(
            instance, "gallery_ids_to_refresh", list(instance.gallery_set.using(using).values_list("pk", flat=True))
        )
        return
    if action not in {"post_add", "post_clear", "post_remove"}:
        return
    if action == "post_clear":
        gallery_ids: Iterable[int] = getattr(instance, "gallery_ids_to_refresh")
        delattr(instance, "gallery_ids_to_refresh")
    else:
        gallery_ids = pk_set or []
    for gallery in Gallery.objects.using(using).filter(pk__in=gallery_ids):
        gallery.refresh_signature(using=using)


@receiver(pre_delete, sender=Image)
def cache_gallery_ids_before_image_delete(sender: Any, instance: Image, using: str, **kwargs: Any) -> None:
    instance.gallery_ids_to_refresh = list(instance.gallery_set.using(using).values_list("pk", flat=True))


@receiver(post_delete, sender=Image)
def refresh_gallery_signatures_after_image_delete(sender: Any, instance: Image, using: str, **kwargs: Any) -> None:
    gallery_ids = getattr(instance, "gallery_ids_to_refresh", [])
    for gallery in Gallery.objects.using(using).filter(pk__in=gallery_ids):
        gallery.refresh_signature(using=using)
