import json
import re
from collections.abc import Mapping
from typing import Any

from django.core.files.base import ContentFile
from django.db import models
from wagtail.models import CollectionMember
from wagtail.search import index

from . import Audio


class Transcript(CollectionMember, index.Indexed, models.Model):
    """A transcript associated with an Audio instance.

    Supports three formats: Podlove (JSON for the web player), WebVTT
    (for feeds and podcast clients), and DOTe (JSON for feeds).
    """

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

    def get_all_paths(self) -> set[str]:
        paths = set()
        for field_name in ("podlove", "vtt", "dote"):
            field = getattr(self, field_name)
            if field:
                paths.add(field.name)
        return paths

    @property
    def podlove_data(self) -> dict:
        data = {}
        if self.podlove:
            try:
                with self.podlove.open("r") as file:
                    data = json.load(file)
            except (FileNotFoundError, OSError):
                data = {}
        return data

    @property
    def dote_data(self) -> dict:
        data = {}
        if self.dote:
            try:
                with self.dote.open("r") as file:
                    data = json.load(file)
            except (FileNotFoundError, OSError):
                data = {}
        return data

    @property
    def podcastindex_data(self) -> dict:
        data = self.dote_data
        if not data:
            return data
        return convert_dote_to_podcastindex_transcript(data)

    def get_speaker_labels(self) -> list[str]:
        """Return unique speaker labels used by the Podlove and DOTe transcript files."""
        labels = set()
        podlove_data = self._load_transcript_json("podlove")
        for segment in podlove_data.get("transcripts", []):
            if not isinstance(segment, dict):
                continue
            for field_name in ("speaker", "voice"):
                label = segment.get(field_name)
                if isinstance(label, str) and label.strip():
                    labels.add(label)

        dote_data = self._load_transcript_json("dote")
        for line in dote_data.get("lines", []):
            if not isinstance(line, dict):
                continue
            label = line.get("speakerDesignation")
            if isinstance(label, str) and label.strip():
                labels.add(label)
        return sorted(labels)

    def rewrite_speaker_labels(self, mapping: Mapping[str, str]) -> bool:
        """Rewrite speaker labels in Podlove and DOTe transcript files.

        The mapping is destructive: matching Podlove ``speaker``/``voice`` and
        DOTe ``speakerDesignation`` values are replaced in-place. WebVTT files
        are intentionally left unchanged because they do not carry speaker data.
        """
        cleaned_mapping = {
            source: target for source, target in mapping.items() if source and target and source != target
        }
        if not cleaned_mapping:
            return False

        changed_fields = []
        podlove_data = self._load_transcript_json("podlove")
        if self._rewrite_podlove_speakers(podlove_data, cleaned_mapping):
            self._save_json_file("podlove", podlove_data)
            changed_fields.append("podlove")

        dote_data = self._load_transcript_json("dote")
        if self._rewrite_dote_speakers(dote_data, cleaned_mapping):
            self._save_json_file("dote", dote_data)
            changed_fields.append("dote")

        if not changed_fields:
            return False
        self.save(update_fields=changed_fields)
        return True

    def _load_transcript_json(self, field_name: str) -> dict[str, Any]:
        file_field = getattr(self, field_name)
        if not file_field:
            return {}
        try:
            with file_field.open("r") as file:
                data = json.load(file)
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return {}
        if not isinstance(data, dict):
            return {}
        return data

    def _save_json_file(self, field_name: str, data: dict[str, Any]) -> None:
        file_field = getattr(self, field_name)
        file_name = file_field.name
        # Keep the file path stable for existing URLs; rewriting is intentionally destructive.
        if file_field.storage.exists(file_name):
            file_field.storage.delete(file_name)
        content = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        file_field.name = file_field.storage.save(file_name, ContentFile(content))

    @staticmethod
    def _rewrite_podlove_speakers(data: dict[str, Any], mapping: Mapping[str, str]) -> bool:
        changed = False
        for segment in data.get("transcripts", []):
            if not isinstance(segment, dict):
                continue
            for field_name in ("speaker", "voice"):
                label = segment.get(field_name)
                if isinstance(label, str) and label in mapping:
                    segment[field_name] = mapping[label]
                    changed = True
        return changed

    @staticmethod
    def _rewrite_dote_speakers(data: dict[str, Any], mapping: Mapping[str, str]) -> bool:
        changed = False
        for line in data.get("lines", []):
            if not isinstance(line, dict):
                continue
            label = line.get("speakerDesignation")
            if isinstance(label, str) and label in mapping:
                line["speakerDesignation"] = mapping[label]
                changed = True
        return changed


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
