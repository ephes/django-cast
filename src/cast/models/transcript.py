import hashlib
import json
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError
from django.db import models
from wagtail.models import CollectionMember
from wagtail.search import index

from cast.file_replacement import StagedFileReplacementGroup

from ..private_storage import get_transcript_storage
from ..transcripts import dote, known_speakers, parsing, podlove, services, speaker_samples, voice_references, webvtt
from ..transcripts.dote import (
    convert_dote_to_podcastindex_transcript,
    convert_segments as convert_segments,
    time_to_seconds as time_to_seconds,
)
from ..transcripts.known_speakers import (
    KNOWN_SPEAKER_DECISION_APPROVE as KNOWN_SPEAKER_DECISION_APPROVE,
    KNOWN_SPEAKER_DECISION_CORRECT as KNOWN_SPEAKER_DECISION_CORRECT,
    KNOWN_SPEAKER_DECISION_REJECT as KNOWN_SPEAKER_DECISION_REJECT,
    KNOWN_SPEAKER_EDITOR_DECISION_FIELD,
)
from ..transcripts.speaker_samples import TranscriptSpeakerSample
from ..transcripts.voice_references import TranscriptVoiceReferenceCandidate
from . import Audio
from .contributors import Contributor, get_voice_reference_storage

TRANSCRIPT_SPEAKER_MAPPING_ARTIFACT_FIELDS = ("podlove", "dote", "vtt")


class Transcript(CollectionMember, index.Indexed, models.Model):
    """A transcript associated with an Audio instance.

    Supports three formats: Podlove (JSON for the web player), WebVTT
    (for feeds and podcast clients), and DOTe (JSON for feeds).
    """

    audio = models.OneToOneField(Audio, on_delete=models.CASCADE, related_name="transcript")
    podlove = models.FileField(
        upload_to="cast_transcript/",
        storage=get_transcript_storage,
        null=True,
        blank=True,
        verbose_name="Podlove Transcript",
        help_text="The transcript format for the Podlove Web Player",
    )
    vtt = models.FileField(
        upload_to="cast_transcript/",
        storage=get_transcript_storage,
        null=True,
        blank=True,
        verbose_name="WebVTT Transcript",
        help_text="The WebVTT format for feed / podcatchers",
    )
    dote = models.FileField(
        upload_to="cast_transcript/",
        storage=get_transcript_storage,
        null=True,
        blank=True,
        verbose_name="DOTe Transcript",
        help_text="The DOTe json format for feed / podcatchers",
    )
    speakers = models.FileField(
        upload_to="cast_transcript_speakers/",
        storage=get_voice_reference_storage,
        null=True,
        blank=True,
        verbose_name="Known-speaker suggestions",
        help_text=(
            "Private known-speaker suggestions returned by Voxhelm: per-segment "
            "candidates, confidence, margin, uncertainty, and raw diarization "
            "labels. Reviewable editorial state, never public transcript output."
        ),
    )

    admin_form_fields: tuple[str, ...] = ("audio", "podlove", "vtt", "dote")

    class Meta:
        ordering = ("-id",)
        permissions = (("choose_transcript", "Can choose transcript"),)

    def save(self, *args: Any, **kwargs: Any) -> None:
        update_fields = kwargs.get("update_fields")
        super().save(*args, **kwargs)
        if self._should_sync_speaker_mappings(update_fields):
            self.sync_speaker_mappings()

    @staticmethod
    def _should_sync_speaker_mappings(update_fields: Any) -> bool:
        if update_fields is None:
            return True
        return bool(set(update_fields).intersection((*TRANSCRIPT_SPEAKER_MAPPING_ARTIFACT_FIELDS, "audio")))

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
    def speakers_data(self) -> dict:
        """Parsed known-speaker suggestion sidecar, or an empty dict.

        This is private editorial review state. It must never be serialized into
        public transcript output, feeds, theme context, or APIs.
        """
        data: dict = {}
        if self.speakers:
            try:
                with self.speakers.open("r") as file:
                    data = json.load(file)
            except (FileNotFoundError, OSError, ValueError):
                data = {}
        return data if isinstance(data, dict) else {}

    def transcript_artifact_fingerprint(self) -> str:
        """Return a stable hash for the current raw public transcript artifacts."""
        digest = hashlib.sha256()
        saw_content = False
        for field_name in TRANSCRIPT_SPEAKER_MAPPING_ARTIFACT_FIELDS:
            content = self._read_file_bytes(field_name)
            if content is None:
                continue
            saw_content = True
            digest.update(field_name.encode("utf-8"))
            digest.update(b"\0")
            digest.update(content)
            digest.update(b"\0")
        return digest.hexdigest() if saw_content else ""

    def _read_file_bytes(self, field_name: str) -> bytes | None:
        file_field = getattr(self, field_name)
        if not file_field or not file_field.name:
            return None
        try:
            with file_field.storage.open(file_field.name, "rb") as file:
                return file.read()
        except (FileNotFoundError, OSError, ValueError):
            return None

    def sync_speaker_mappings(self) -> None:
        """Synchronize durable anonymous-speaker mapping rows with raw artifacts."""
        services.sync_speaker_mappings(self)

    def get_speaker_suggestions(self) -> list[dict]:
        """Per-segment known-speaker suggestions for editor review."""
        segments = self.speakers_data.get("segments", [])
        return [segment for segment in segments if isinstance(segment, dict)]

    def get_speaker_suggestion_summary(self) -> dict:
        summary = self.speakers_data.get("summary", {})
        return summary if isinstance(summary, dict) else {}

    def has_uncertain_speaker_suggestions(self) -> bool:
        return any(segment.get("speaker_uncertain") for segment in self.get_speaker_suggestions())

    def known_speaker_review_summary(self) -> dict:
        """Reviewable overview of known-speaker suggestions for the admin.

        Surfaces confident/uncertain counts and the confident speaker
        distribution so editors can see uncertainty before approving.
        """
        suggestions = self.get_speaker_suggestions()
        by_speaker: dict[str, int] = {}
        uncertain = 0
        for segment in suggestions:
            if segment.get("speaker_uncertain"):
                uncertain += 1
                continue
            name = segment.get("speaker")
            if name:
                by_speaker[name] = by_speaker.get(name, 0) + 1
        return {
            "total": len(suggestions),
            "confident": len(suggestions) - uncertain,
            "uncertain": uncertain,
            "by_speaker": dict(sorted(by_speaker.items())),
            "metadata": self.get_speaker_suggestion_summary(),
        }

    def apply_known_speaker_suggestions(self, *, smooth: bool = True) -> int:
        """Apply known-speaker suggestions to public transcript output.

        Editor approval step: confident (non-uncertain) per-segment suggestions
        are written into the public Podlove ``speaker``/``voice``, DOTe
        ``speakerDesignation``, and WebVTT voice-label fields, matched to
        segments or cues by start time.

        With ``smooth=True`` (the default), uncertain segments are filled with
        the surrounding confident speaker (carry the previous confident speaker
        forward, backfill any leading gap) so the public transcript reads
        continuously instead of showing speaker-less paragraphs between labeled
        ones. With ``smooth=False`` only confident segments are labeled and
        uncertain ones are left blank for review.

        Explicit per-segment editor decisions stored in the private sidecar
        take precedence over the confident/smoothed result. Rejected segments
        clear any existing public speaker label for that start time.

        The raw Voxhelm metadata in the private ``speakers`` sidecar is
        preserved, so the raw per-segment candidates and uncertainty flags stay
        available for audit and re-application. Returns the number of public
        transcript entries matched across stored formats.
        """
        return services.apply_known_speaker_suggestions(self, smooth=smooth)

    def save_known_speaker_editor_decisions(
        self,
        decisions_by_position: Mapping[int, Mapping[str, str] | None],
    ) -> int:
        """Persist per-segment editor decisions in the private sidecar.

        Decisions are additive metadata on each segment. Raw Voxhelm fields
        such as ``speaker``, ``speaker_uncertain``, candidate lists, confidence,
        margin, and raw diarization labels are never overwritten.
        """
        return services.save_known_speaker_editor_decisions(self, decisions_by_position)

    def get_known_speaker_editor_decisions(self) -> dict[int, dict[str, str]]:
        """Return valid per-segment editor decisions keyed by sidecar position."""
        decisions: dict[int, dict[str, str]] = {}
        for position, segment in enumerate(self.get_speaker_suggestions()):
            decision = known_speakers.normalize_editor_decision(segment.get(KNOWN_SPEAKER_EDITOR_DECISION_FIELD))
            if decision is not None:
                decisions[position] = decision
        return decisions

    def _write_speakers_data(
        self, data: dict[str, Any], *, replacements: StagedFileReplacementGroup | None = None
    ) -> None:
        content = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self._save_file_content("speakers", content, replacements=replacements)

    def _apply_suggestions_to_podlove(
        self, names_by_start_ms: dict[int, str], *, replacements: StagedFileReplacementGroup | None = None
    ) -> int:
        data = self._load_transcript_json("podlove")
        applied = podlove.apply_suggestions(data, names_by_start_ms)
        if applied:
            self._write_transcript_json("podlove", data, replacements=replacements)
        return applied

    def _apply_suggestions_to_dote(
        self, names_by_start_ms: dict[int, str], *, replacements: StagedFileReplacementGroup | None = None
    ) -> int:
        data = self._load_transcript_json("dote")
        applied = dote.apply_suggestions(data, names_by_start_ms)
        if applied:
            self._write_transcript_json("dote", data, replacements=replacements)
        return applied

    def _clear_suggestions_from_podlove(
        self, start_milliseconds: set[int], *, replacements: StagedFileReplacementGroup | None = None
    ) -> int:
        data = self._load_transcript_json("podlove")
        applied, changed = podlove.clear_suggestions(data, start_milliseconds)
        if changed:
            self._write_transcript_json("podlove", data, replacements=replacements)
        return applied

    def _clear_suggestions_from_dote(
        self, start_milliseconds: set[int], *, replacements: StagedFileReplacementGroup | None = None
    ) -> int:
        data = self._load_transcript_json("dote")
        applied, changed = dote.clear_suggestions(data, start_milliseconds)
        if changed:
            self._write_transcript_json("dote", data, replacements=replacements)
        return applied

    def _clear_suggestions_from_webvtt(
        self, start_milliseconds: set[int], *, replacements: StagedFileReplacementGroup | None = None
    ) -> int:
        content = self._load_text_file("vtt")
        rewritten_content, applied, changed = webvtt.clear_suggestions_from_content(content, start_milliseconds)
        if changed:
            self._save_text_file("vtt", rewritten_content, replacements=replacements)
        return applied

    def _apply_suggestions_to_webvtt(
        self, names_by_start_ms: dict[int, str], *, replacements: StagedFileReplacementGroup | None = None
    ) -> int:
        content = self._load_text_file("vtt")
        rewritten_content, applied, changed = webvtt.apply_suggestions_to_content(content, names_by_start_ms)
        if changed:
            self._save_text_file("vtt", rewritten_content, replacements=replacements)
        return applied

    def _write_transcript_json(
        self, field_name: str, data: dict, *, replacements: StagedFileReplacementGroup | None = None
    ) -> None:
        # Only called after _load_transcript_json read this field's file, so the
        # field always has a stored name here.
        field = getattr(self, field_name)
        payload = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        filename = field.name.rsplit("/", 1)[-1]
        self._save_file_content(field_name, payload, filename=filename, replacements=replacements)

    @property
    def podcastindex_data(self) -> dict:
        data = self.dote_data
        if not data:
            return data
        return convert_dote_to_podcastindex_transcript(data)

    def get_speaker_labels(self) -> list[str]:
        """Return unique speaker labels used by the Podlove and DOTe transcript files."""
        return services.get_speaker_labels(self)

    def get_speaker_samples(
        self,
        *,
        limit: int = speaker_samples.SPEAKER_SAMPLE_LIMIT,
        max_chars: int = speaker_samples.SPEAKER_SAMPLE_MAX_CHARS,
        min_chars: int = speaker_samples.SPEAKER_SAMPLE_MIN_CHARS,
        min_words: int = speaker_samples.SPEAKER_SAMPLE_MIN_WORDS,
    ) -> dict[str, list[TranscriptSpeakerSample]]:
        """Return short transcript excerpts keyed by diarization speaker label.

        Samples prefer Podlove transcript segments, use DOTe lines as a fallback,
        skip low-information backchannels where possible, and spread the chosen
        examples across each speaker's appearances.
        """
        return services.get_speaker_samples(
            self,
            limit=limit,
            max_chars=max_chars,
            min_chars=min_chars,
            min_words=min_words,
        )

    def get_voice_reference_candidates(
        self,
        *,
        target_seconds: Decimal = voice_references.VOICE_REFERENCE_CANDIDATE_TARGET_SECONDS,
        min_seconds: Decimal = voice_references.VOICE_REFERENCE_CANDIDATE_MIN_SECONDS,
        max_gap_seconds: Decimal = voice_references.VOICE_REFERENCE_CANDIDATE_MAX_GAP_SECONDS,
        limit_per_speaker: int = voice_references.VOICE_REFERENCE_CANDIDATE_LIMIT,
    ) -> list[TranscriptVoiceReferenceCandidate]:
        """Return source-range candidates derived from diarized Podlove segments.

        Candidates are contiguous, same-label Podlove runs with usable start and
        end times. Derivation is read-only: transcript files and private
        known-speaker sidecars are never mutated by this helper.
        """
        return services.get_voice_reference_candidates(
            self,
            target_seconds=target_seconds,
            min_seconds=min_seconds,
            max_gap_seconds=max_gap_seconds,
            limit_per_speaker=limit_per_speaker,
        )

    def rewrite_speaker_labels(self, mapping: Mapping[str, str]) -> bool:
        """Rewrite speaker labels in stored transcript artifacts.

        The mapping is destructive: matching Podlove ``speaker``/``voice``,
        DOTe ``speakerDesignation``, and WebVTT voice-label values are replaced
        in-place.
        """
        return services.rewrite_speaker_labels(self, mapping)

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

    def _save_json_file(
        self, field_name: str, data: dict[str, Any], *, replacements: StagedFileReplacementGroup | None = None
    ) -> None:
        content = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self._save_file_content(field_name, content, replacements=replacements)

    def _load_text_file(self, field_name: str) -> str:
        file_field = getattr(self, field_name)
        try:
            with file_field.open("rb") as file:
                return file.read().decode("utf-8")
        except (FileNotFoundError, OSError, UnicodeDecodeError, ValueError):
            return ""

    def _save_text_file(
        self, field_name: str, content: str, *, replacements: StagedFileReplacementGroup | None = None
    ) -> None:
        self._save_file_content(field_name, content.encode("utf-8"), replacements=replacements)

    def _save_file_content(
        self,
        field_name: str,
        content: bytes,
        *,
        filename: str | None = None,
        replacements: StagedFileReplacementGroup | None = None,
    ) -> None:
        file_field = getattr(self, field_name)
        file_name = filename or file_field.name.rsplit("/", 1)[-1]
        active_replacements = replacements or StagedFileReplacementGroup()
        active_replacements.stage(file_field, file_name, content)


class TranscriptSpeakerMapping(models.Model):
    """Durable editor mapping for raw anonymous transcript speaker labels."""

    class ReviewState(models.TextChoices):
        UNMAPPED = "unmapped", "Unmapped"
        APPROVED = "approved", "Approved"
        STALE = "stale", "Needs review"

    transcript = models.ForeignKey(Transcript, related_name="speaker_mappings", on_delete=models.CASCADE)
    speaker_label = models.CharField(max_length=256)
    contributor = models.ForeignKey(
        Contributor,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        help_text="Reusable contributor target for this raw transcript speaker label.",
    )
    display_name = models.CharField(
        max_length=128,
        blank=True,
        help_text="One-off public name for this transcript speaker label.",
    )
    review_state = models.CharField(
        max_length=32,
        choices=ReviewState.choices,
        default=ReviewState.UNMAPPED,
    )
    source_artifact_fingerprint = models.CharField(max_length=64, blank=True)
    active = models.BooleanField(default=True)
    last_seen = models.DateTimeField(null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("transcript_id", "-active", "speaker_label")
        constraints = [
            models.UniqueConstraint(
                fields=["transcript", "speaker_label"],
                name="unique_transcript_speaker_label",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.transcript_id}: {self.speaker_label}"

    @property
    def target_display_name(self) -> str:
        if self.contributor_id is not None and self.contributor is not None:
            return self.contributor.display_name
        return parsing.clean_speaker_label(self.display_name)

    def clean(self) -> None:
        super().clean()
        self.speaker_label = parsing.clean_speaker_label(self.speaker_label)
        self.display_name = parsing.clean_speaker_label(self.display_name)
        has_contributor = self.contributor_id is not None
        has_display_name = bool(self.display_name)
        if has_contributor and has_display_name:
            raise ValidationError("Choose either a contributor or a display name, not both.")
        if self.review_state == self.ReviewState.APPROVED and not (has_contributor or has_display_name):
            raise ValidationError("Approved speaker mappings need a contributor or display name.")

    def is_current_for_fingerprint(self, fingerprint: str) -> bool:
        return (
            self.active
            and self.review_state == self.ReviewState.APPROVED
            and self.source_artifact_fingerprint == fingerprint
        )
