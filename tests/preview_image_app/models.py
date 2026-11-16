from django.db import models
from wagtail.images.models import AbstractImage, AbstractRendition


class PreviewImage(AbstractImage):
    admin_form_fields = ()


class PreviewRendition(AbstractRendition):
    image = models.ForeignKey(PreviewImage, on_delete=models.CASCADE, related_name="renditions")

    class Meta:
        unique_together = (("image", "filter_spec", "focal_point_key"),)
