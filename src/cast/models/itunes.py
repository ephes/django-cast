from django.db import models
from model_utils.models import TimeStampedModel


class ItunesArtWork(TimeStampedModel):  # type: ignore
    original = models.ImageField(
        upload_to="cast_images/itunes_artwork",
        height_field="original_height",
        width_field="original_width",
    )
    original_height = models.PositiveIntegerField(blank=True, null=True)
    original_width = models.PositiveIntegerField(blank=True, null=True)
