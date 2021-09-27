from django.db import models

from wagtail.images.models import Image

from model_utils.models import TimeStampedModel


class Gallery(TimeStampedModel):
    images = models.ManyToManyField(Image)
    post_context_key = "gallery"

    @property
    def image_ids(self):
        return {i.pk for i in self.images.all()}


def get_or_create_gallery(image_ids):
    candidate_images = Image.objects.filter(id__in=image_ids)  # FIXME filter permissions
    if candidate_images.count() == 0:
        return None
    filtered_image_ids = [ci.id for ci in candidate_images]
    gallery_to_image_ids = {}
    # FIXME filter permissions - fetch only images / galleries that
    # this user has permission to view
    candidate_galleries = Gallery.objects.filter(images__in=filtered_image_ids).prefetch_related("images")
    for gallery in candidate_galleries:
        gallery_to_image_ids[frozenset(i.id for i in gallery.images.all())] = gallery
    gallery = gallery_to_image_ids.get(frozenset(filtered_image_ids))
    if gallery is None:
        gallery = Gallery.objects.create()
        gallery.images.add(*filtered_image_ids)
    return gallery
