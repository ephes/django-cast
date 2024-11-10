from django.db import models
from wagtail.models import CollectionMember
from wagtail.search import index

from . import Audio


class Transcript(CollectionMember, index.Indexed, models.Model):
    audio = models.OneToOneField(Audio, on_delete=models.CASCADE, related_name="transcript")
    podlove = models.FileField(
        upload_to="cast_transcript/",
        null=True,
        blank=True,
        verbose_name="Podlove Transcript",
        help_text="The transcript format for the Podlove Web Player",
    )
    vtt = models.FileField(
        upload_to="cast_transcript/",
        null=True,
        blank=True,
        verbose_name="WebVTT Transcript",
        help_text="The WebVTT format for feed / podcatchers",
    )
    dote = models.FileField(
        upload_to="cast_transcript/",
        null=True,
        blank=True,
        verbose_name="DOTe Transcript",
        help_text="The DOTe json format for feed / podcatchers",
    )

    admin_form_fields: tuple[str, ...] = ("audio", "podlove", "vtt", "dote")
