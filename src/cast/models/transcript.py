import json
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from django.core.files.base import ContentFile
from django.db import models
from wagtail.models import CollectionMember
from wagtail.search import index

from . import Audio


SPEAKER_SAMPLE_LIMIT = 3
SPEAKER_SAMPLE_MAX_CHARS = 180
SPEAKER_SAMPLE_MIN_CHARS = 35
SPEAKER_SAMPLE_MIN_WORDS = 4
LOW_SIGNAL_TRANSCRIPT_SAMPLE_TEXTS = frozenset(
    {
        "ah",
        "ahm",
        "aeh",
        "aehm",
        "genau",
        "hm",
        "hmm",
        "ja",
        "mhm",
        "no",
        "ok",
        "okay",
        "stimmt",
        "yes",
    }
)


@dataclass(frozen=True)
class TranscriptSpeakerSample:
    """Short transcript excerpt used to identify diarized speakers in the admin."""

    text: str
    timestamp_label: str
    start_seconds: float | None

    @property
    def has_start_time(self) -> bool:
        return self.start_seconds is not None


@dataclass(frozen=True)
class _SpeakerSampleCandidate:
    speaker_label: str
    text: str
    timestamp_label: str
    start_seconds: float | None
    position: int
    useful: bool


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
                label = self._clean_speaker_label(segment.get(field_name))
                if label:
                    labels.add(label)

        dote_data = self._load_transcript_json("dote")
        for line in dote_data.get("lines", []):
            if not isinstance(line, dict):
                continue
            label = self._clean_speaker_label(line.get("speakerDesignation"))
            if label:
                labels.add(label)
        return sorted(labels)

    def get_speaker_samples(
        self,
        *,
        limit: int = SPEAKER_SAMPLE_LIMIT,
        max_chars: int = SPEAKER_SAMPLE_MAX_CHARS,
        min_chars: int = SPEAKER_SAMPLE_MIN_CHARS,
        min_words: int = SPEAKER_SAMPLE_MIN_WORDS,
    ) -> dict[str, list[TranscriptSpeakerSample]]:
        """Return short transcript excerpts keyed by diarization speaker label.

        Samples prefer Podlove transcript segments, use DOTe lines as a fallback,
        skip low-information backchannels where possible, and spread the chosen
        examples across each speaker's appearances.
        """
        if limit <= 0:
            return {}
        podlove_candidates = self._get_podlove_speaker_sample_candidates(
            max_chars=max_chars,
            min_chars=min_chars,
            min_words=min_words,
        )
        dote_candidates = self._get_dote_speaker_sample_candidates(
            max_chars=max_chars,
            min_chars=min_chars,
            min_words=min_words,
        )
        return self._select_speaker_samples(
            podlove_candidates=podlove_candidates,
            dote_candidates=dote_candidates,
            limit=limit,
        )

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

    def _get_podlove_speaker_sample_candidates(
        self,
        *,
        max_chars: int,
        min_chars: int,
        min_words: int,
    ) -> list[_SpeakerSampleCandidate]:
        candidates: list[_SpeakerSampleCandidate] = []
        podlove_data = self._load_transcript_json("podlove")
        for position, segment in enumerate(podlove_data.get("transcripts", [])):
            if not isinstance(segment, dict):
                continue
            speaker_labels = {
                label
                for field_name in ("speaker", "voice")
                if (label := self._clean_speaker_label(segment.get(field_name)))
            }
            if not speaker_labels:
                continue
            text = self._clean_sample_text(segment.get("text"))
            if not text:
                continue
            start_seconds = self._parse_record_start_seconds(segment, timestamp_fields=("start", "startTime"))
            candidates.extend(
                self._build_sample_candidate(
                    speaker_label=speaker_label,
                    text=text,
                    position=position,
                    start_seconds=start_seconds,
                    max_chars=max_chars,
                    min_chars=min_chars,
                    min_words=min_words,
                )
                for speaker_label in sorted(speaker_labels)
            )
        return candidates

    def _get_dote_speaker_sample_candidates(
        self,
        *,
        max_chars: int,
        min_chars: int,
        min_words: int,
    ) -> list[_SpeakerSampleCandidate]:
        candidates: list[_SpeakerSampleCandidate] = []
        dote_data = self._load_transcript_json("dote")
        for position, line in enumerate(dote_data.get("lines", [])):
            if not isinstance(line, dict):
                continue
            speaker_label = self._clean_speaker_label(line.get("speakerDesignation"))
            if not speaker_label:
                continue
            text = self._clean_sample_text(line.get("text"))
            if not text:
                continue
            start_seconds = self._parse_record_start_seconds(line, timestamp_fields=("startTime",))
            candidates.append(
                self._build_sample_candidate(
                    speaker_label=speaker_label,
                    text=text,
                    position=position,
                    start_seconds=start_seconds,
                    max_chars=max_chars,
                    min_chars=min_chars,
                    min_words=min_words,
                )
            )
        return candidates

    @classmethod
    def _select_speaker_samples(
        cls,
        *,
        podlove_candidates: list[_SpeakerSampleCandidate],
        dote_candidates: list[_SpeakerSampleCandidate],
        limit: int,
    ) -> dict[str, list[TranscriptSpeakerSample]]:
        samples = {}
        speaker_labels = sorted(
            {candidate.speaker_label for candidate in podlove_candidates}
            | {candidate.speaker_label for candidate in dote_candidates}
        )
        for speaker_label in speaker_labels:
            podlove_speaker_candidates = cls._sort_sample_candidates(
                [candidate for candidate in podlove_candidates if candidate.speaker_label == speaker_label]
            )
            dote_speaker_candidates = cls._sort_sample_candidates(
                [candidate for candidate in dote_candidates if candidate.speaker_label == speaker_label]
            )
            candidate_pool = (
                [candidate for candidate in podlove_speaker_candidates if candidate.useful]
                or [candidate for candidate in dote_speaker_candidates if candidate.useful]
                or podlove_speaker_candidates
                or dote_speaker_candidates
            )
            samples[speaker_label] = [
                TranscriptSpeakerSample(
                    text=candidate.text,
                    timestamp_label=candidate.timestamp_label,
                    start_seconds=candidate.start_seconds,
                )
                for candidate in cls._spread_sample_candidates(candidate_pool, limit=limit)
            ]
        return samples

    @staticmethod
    def _sort_sample_candidates(candidates: list[_SpeakerSampleCandidate]) -> list[_SpeakerSampleCandidate]:
        return sorted(
            candidates,
            key=lambda candidate: (
                candidate.start_seconds is None,
                candidate.start_seconds if candidate.start_seconds is not None else candidate.position,
                candidate.position,
            ),
        )

    @staticmethod
    def _spread_sample_candidates(
        candidates: list[_SpeakerSampleCandidate],
        *,
        limit: int,
    ) -> list[_SpeakerSampleCandidate]:
        if len(candidates) <= limit:
            return candidates
        if limit == 1:
            return candidates[:1]
        last_index = len(candidates) - 1
        selected_indexes = []
        for sample_index in range(limit):
            candidate_index = int((sample_index * last_index / (limit - 1)) + 0.5)
            selected_indexes.append(candidate_index)
        return [candidates[index] for index in selected_indexes]

    @classmethod
    def _build_sample_candidate(
        cls,
        *,
        speaker_label: str,
        text: str,
        position: int,
        start_seconds: float | None,
        max_chars: int,
        min_chars: int,
        min_words: int,
    ) -> _SpeakerSampleCandidate:
        return _SpeakerSampleCandidate(
            speaker_label=speaker_label,
            text=cls._truncate_sample_text(text, max_chars=max_chars),
            timestamp_label=cls._format_sample_timestamp(start_seconds),
            start_seconds=start_seconds,
            position=position,
            useful=cls._sample_text_is_useful(text, min_chars=min_chars, min_words=min_words),
        )

    @staticmethod
    def _clean_sample_text(value: Any) -> str:
        if not isinstance(value, str):
            return ""
        return re.sub(r"\s+", " ", value).strip()

    @staticmethod
    def _clean_speaker_label(value: Any) -> str:
        if not isinstance(value, str):
            return ""
        return value.strip()

    @classmethod
    def _sample_text_is_useful(cls, text: str, *, min_chars: int, min_words: int) -> bool:
        if len(text) < min_chars:
            return False
        words = re.findall(r"\w+", text)
        if len(words) < min_words:
            return False
        # The low-signal list is intentionally Latin-script only; non-Latin text falls through as useful.
        normalized_text = cls._normalize_sample_text(text)
        if normalized_text in LOW_SIGNAL_TRANSCRIPT_SAMPLE_TEXTS:
            return False
        normalized_words = normalized_text.split()
        return not normalized_words or not all(word in LOW_SIGNAL_TRANSCRIPT_SAMPLE_TEXTS for word in normalized_words)

    @staticmethod
    def _normalize_sample_text(text: str) -> str:
        ascii_text = unicodedata.normalize("NFKD", text.casefold()).encode("ascii", errors="ignore").decode("ascii")
        normalized_text = re.sub(r"[^a-z0-9]+", " ", ascii_text)
        return re.sub(r"\s+", " ", normalized_text).strip()

    @staticmethod
    def _truncate_sample_text(text: str, *, max_chars: int) -> str:
        if len(text) <= max_chars:
            return text
        truncated = text[:max_chars].rsplit(" ", 1)[0] or text[:max_chars]
        return f"{truncated}..."

    @classmethod
    def _parse_record_start_seconds(cls, record: dict[str, Any], *, timestamp_fields: tuple[str, ...]) -> float | None:
        start_ms = record.get("start_ms")
        if not isinstance(start_ms, bool) and isinstance(start_ms, int | float) and start_ms >= 0:
            return float(start_ms) / 1000
        for field_name in timestamp_fields:
            start_seconds = cls._parse_timestamp_seconds(record.get(field_name))
            if start_seconds is not None:
                return start_seconds
        return None

    @staticmethod
    def _parse_timestamp_seconds(value: Any) -> float | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, int | float):
            return float(value) if value >= 0 else None
        if not isinstance(value, str):
            return None
        timestamp = value.strip().replace(",", ".")
        if not timestamp:
            return None
        parts = timestamp.split(":")
        try:
            if len(parts) == 3:
                hours = int(parts[0])
                minutes = int(parts[1])
                seconds = float(parts[2])
            elif len(parts) == 2:
                hours = 0
                minutes = int(parts[0])
                seconds = float(parts[1])
            elif len(parts) == 1:
                return float(timestamp) if float(timestamp) >= 0 else None
            else:
                return None
        except ValueError:
            return None
        start_seconds = (hours * 3600) + (minutes * 60) + seconds
        return start_seconds if start_seconds >= 0 else None

    @staticmethod
    def _format_sample_timestamp(start_seconds: float | None) -> str:
        if start_seconds is None:
            return ""
        total_seconds = int(start_seconds)
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60
        if hours:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:02d}:{seconds:02d}"

    @classmethod
    def _rewrite_podlove_speakers(cls, data: dict[str, Any], mapping: Mapping[str, str]) -> bool:
        changed = False
        for segment in data.get("transcripts", []):
            if not isinstance(segment, dict):
                continue
            for field_name in ("speaker", "voice"):
                label = cls._clean_speaker_label(segment.get(field_name))
                if label in mapping:
                    segment[field_name] = mapping[label]
                    changed = True
        return changed

    @classmethod
    def _rewrite_dote_speakers(cls, data: dict[str, Any], mapping: Mapping[str, str]) -> bool:
        changed = False
        for line in data.get("lines", []):
            if not isinstance(line, dict):
                continue
            label = cls._clean_speaker_label(line.get("speakerDesignation"))
            if label in mapping:
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
