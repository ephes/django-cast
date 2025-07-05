import json
import re

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

    class Meta:
        ordering = ("-id",)

    @property
    def podlove_data(self) -> dict:
        data = {}
        if self.podlove:
            with self.podlove.open("r") as file:
                data = json.load(file)
        return data

    @property
    def dote_data(self) -> dict:
        data = {}
        if self.dote:
            with self.dote.open("r") as file:
                data = json.load(file)
        return data

    @property
    def podcastindex_data(self) -> dict:
        data = self.dote_data
        if not data:
            return data
        return convert_dote_to_podcastindex_transcript(data)


def time_to_seconds(time_str) -> float:
    match = re.match(r"(\d+):(\d+):(\d+),(\d+)", time_str)
    if match:
        hours, minutes, seconds, milliseconds = map(int, match.groups())
        return hours * 3600 + minutes * 60 + seconds + milliseconds / 1000
    raise ValueError(f"Invalid time format: {time_str}")


def convert_segments(segments) -> list[dict]:
    converted = []
    for segment in segments:
        converted.append(
            {
                "startTime": time_to_seconds(segment["startTime"]),
                "endTime": time_to_seconds(segment["endTime"]),
                "speaker": segment["speakerDesignation"],
                "body": segment["text"],
            }
        )
    return converted


def convert_dote_to_podcastindex_transcript(transcript: dict) -> dict:
    return {
        "version": "1.0",
        "segments": convert_segments(transcript["lines"]),
    }
