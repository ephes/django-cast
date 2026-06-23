import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, replace
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from wagtail.models import CollectionMember
from wagtail.search import index

from cast.file_replacement import StagedFileReplacementGroup

from . import Audio
from ..private_storage import get_private_media_storage
from .contributors import Contributor, get_voice_reference_storage


def _segment_sort_key(segment: dict) -> float:
    try:
        return float(segment.get("start") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _dote_timestamp_to_ms(value: object) -> int | None:
    """Parse a DOTe ``HH:MM:SS,mmm`` timestamp into milliseconds."""
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})", value.strip())
    if match is None:
        return None
    hours, minutes, seconds, millis = (int(part) for part in match.groups())
    return ((hours * 3600 + minutes * 60 + seconds) * 1000) + millis


def _webvtt_timestamp_to_ms(value: object) -> int | None:
    """Parse a WebVTT ``HH:MM:SS.mmm`` or ``MM:SS.mmm`` timestamp into milliseconds."""
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"(?:(\d+):)?(\d{2}):(\d{2})\.(\d{1,3})", value.strip())
    if match is None:
        return None
    hours, minutes, seconds, millis = match.groups()
    return ((int(hours or 0) * 3600 + int(minutes) * 60 + int(seconds)) * 1000) + int(millis.ljust(3, "0"))


def _webvtt_timing_line_start_ms(line: str) -> int | None:
    start_timestamp = line.split(WEBVTT_TIMING_SEPARATOR, 1)[0].strip()
    return _webvtt_timestamp_to_ms(start_timestamp)


SPEAKER_SAMPLE_LIMIT = 3
SPEAKER_SAMPLE_MAX_CHARS = 180
SPEAKER_SAMPLE_MIN_CHARS = 35
SPEAKER_SAMPLE_MIN_WORDS = 4
VOICE_REFERENCE_CANDIDATE_LIMIT = 3
VOICE_REFERENCE_CANDIDATE_TARGET_SECONDS = Decimal("30.000")
VOICE_REFERENCE_CANDIDATE_MIN_SECONDS = Decimal("8.000")
VOICE_REFERENCE_CANDIDATE_MAX_GAP_SECONDS = Decimal("2.000")
VOICE_REFERENCE_CANDIDATE_MAX_CHARS = 240
VOICE_REFERENCE_CANDIDATE_QUANTUM = Decimal("0.001")
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
WEBVTT_TIMING_SEPARATOR = "-->"
WEBVTT_VOICE_OPENING_RE = re.compile(r"<v(?P<classes>(?:\.[^\s>]+)*)(?:\s+(?P<label>[^>]*))?>")
WEBVTT_VOICE_CLOSING_RE = re.compile(r"</v>")
WEBVTT_GENERIC_SPEAKER_PREFIX_RE = re.compile(r"^(?P<label>Speaker\s+\d+)\s*:\s*(?P<text>.*)$", re.IGNORECASE)
KNOWN_SPEAKER_EDITOR_DECISION_FIELD = "editor_decision"
KNOWN_SPEAKER_DECISION_APPROVE = "approve"
KNOWN_SPEAKER_DECISION_CORRECT = "correct"
KNOWN_SPEAKER_DECISION_REJECT = "reject"
TRANSCRIPT_SPEAKER_MAPPING_ARTIFACT_FIELDS = ("podlove", "dote", "vtt")


def _quantize_seconds(value: Decimal) -> Decimal:
    return value.quantize(VOICE_REFERENCE_CANDIDATE_QUANTUM, rounding=ROUND_HALF_UP)


def _format_decimal_timestamp(value: Decimal) -> str:
    total_milliseconds = int((value * 1000).to_integral_value(rounding=ROUND_HALF_UP))
    total_seconds, milliseconds = divmod(total_milliseconds, 1000)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}"
    return f"{minutes:02d}:{seconds:02d}.{milliseconds:03d}"


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
class TranscriptVoiceReferenceCandidate:
    """Timed clean-solo source-range candidate derived from diarized transcript data."""

    speaker_label: str
    start_seconds: Decimal
    end_seconds: Decimal
    duration_seconds: Decimal
    text: str
    rank: int

    @property
    def start_timestamp_label(self) -> str:
        return _format_decimal_timestamp(self.start_seconds)

    @property
    def end_timestamp_label(self) -> str:
        return _format_decimal_timestamp(self.end_seconds)

    @property
    def duration_label(self) -> str:
        return _format_decimal_timestamp(self.duration_seconds)


@dataclass(frozen=True)
class _SpeakerSampleCandidate:
    speaker_label: str
    text: str
    timestamp_label: str
    start_seconds: float | None
    position: int
    useful: bool


@dataclass(frozen=True)
class _PodloveVoiceReferenceSegment:
    speaker_label: str
    start_seconds: Decimal
    end_seconds: Decimal
    text: str
    position: int


class Transcript(CollectionMember, index.Indexed, models.Model):
    """A transcript associated with an Audio instance.

    Supports three formats: Podlove (JSON for the web player), WebVTT
    (for feeds and podcast clients), and DOTe (JSON for feeds).
    """

    audio = models.OneToOneField(Audio, on_delete=models.CASCADE, related_name="transcript")
    podlove = models.FileField(
        upload_to="cast_transcript/",
        storage=get_private_media_storage,
        null=True,
        blank=True,
        verbose_name="Podlove Transcript",
        help_text="The transcript format for the Podlove Web Player",
    )
    vtt = models.FileField(
        upload_to="cast_transcript/",
        storage=get_private_media_storage,
        null=True,
        blank=True,
        verbose_name="WebVTT Transcript",
        help_text="The WebVTT format for feed / podcatchers",
    )
    dote = models.FileField(
        upload_to="cast_transcript/",
        storage=get_private_media_storage,
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
        if self.pk is None:
            return
        speaker_labels = self.get_speaker_labels()
        seen_labels = set(speaker_labels)
        fingerprint = self.transcript_artifact_fingerprint()
        now = timezone.now()
        existing_mappings = {mapping.speaker_label: mapping for mapping in self.speaker_mappings.all()}

        for speaker_label in speaker_labels:
            mapping = existing_mappings.get(speaker_label)
            if mapping is None:
                TranscriptSpeakerMapping.objects.create(
                    transcript=self,
                    speaker_label=speaker_label,
                    source_artifact_fingerprint=fingerprint,
                    last_seen=now,
                )
                continue
            update_fields = []
            if not mapping.active:
                mapping.active = True
                update_fields.append("active")
            if mapping.last_seen != now:
                mapping.last_seen = now
                update_fields.append("last_seen")
            if mapping.review_state == TranscriptSpeakerMapping.ReviewState.APPROVED:
                if mapping.contributor_id is None and not mapping.display_name:
                    mapping.review_state = TranscriptSpeakerMapping.ReviewState.STALE
                    update_fields.append("review_state")
                elif mapping.source_artifact_fingerprint != fingerprint:
                    mapping.review_state = TranscriptSpeakerMapping.ReviewState.STALE
                    update_fields.append("review_state")
            elif mapping.source_artifact_fingerprint != fingerprint:
                mapping.source_artifact_fingerprint = fingerprint
                update_fields.append("source_artifact_fingerprint")
            if update_fields:
                mapping.save(update_fields=update_fields)

        for speaker_label, mapping in existing_mappings.items():
            if speaker_label in seen_labels:
                continue
            update_fields = []
            if mapping.active:
                mapping.active = False
                update_fields.append("active")
            if mapping.review_state == TranscriptSpeakerMapping.ReviewState.APPROVED:
                mapping.review_state = TranscriptSpeakerMapping.ReviewState.STALE
                update_fields.append("review_state")
            if update_fields:
                mapping.save(update_fields=update_fields)

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
        suggestions = sorted(self.get_speaker_suggestions(), key=_segment_sort_key)
        display_names = self._resolve_known_speaker_display_names(suggestions, smooth=smooth)
        names_by_start_ms: dict[int, str] = {}
        rejected_start_ms: set[int] = set()
        for segment, name in zip(suggestions, display_names):
            try:
                start_ms = int(round(float(segment["start"]) * 1000))
            except (TypeError, ValueError, KeyError):
                continue
            if name:
                names_by_start_ms[start_ms] = name
                rejected_start_ms.discard(start_ms)
            elif self._segment_has_reject_decision(segment):
                rejected_start_ms.add(start_ms)
        if not names_by_start_ms and not rejected_start_ms:
            return 0
        replacements = StagedFileReplacementGroup()
        try:
            applied = self._clear_suggestions_from_podlove(rejected_start_ms, replacements=replacements)
            applied += self._clear_suggestions_from_dote(rejected_start_ms, replacements=replacements)
            if self.vtt:
                applied += self._clear_suggestions_from_webvtt(rejected_start_ms, replacements=replacements)
            if names_by_start_ms:
                applied += self._apply_suggestions_to_podlove(names_by_start_ms, replacements=replacements)
                applied += self._apply_suggestions_to_dote(names_by_start_ms, replacements=replacements)
                if self.vtt:
                    applied += self._apply_suggestions_to_webvtt(names_by_start_ms, replacements=replacements)
            if applied:
                if replacements.replacements:
                    replacements.save_model(self)
                else:
                    self.save()
        except Exception:
            replacements.rollback()
            raise
        return applied

    def save_known_speaker_editor_decisions(
        self,
        decisions_by_position: Mapping[int, Mapping[str, str] | None],
    ) -> int:
        """Persist per-segment editor decisions in the private sidecar.

        Decisions are additive metadata on each segment. Raw Voxhelm fields
        such as ``speaker``, ``speaker_uncertain``, candidate lists, confidence,
        margin, and raw diarization labels are never overwritten.
        """
        data = self.speakers_data
        segments = data.get("segments")
        if not isinstance(segments, list):
            return 0
        changed = 0
        suggestion_position = -1
        for segment in segments:
            if not isinstance(segment, dict):
                continue
            suggestion_position += 1
            if suggestion_position not in decisions_by_position:
                continue
            decision = self._normalize_known_speaker_editor_decision(decisions_by_position[suggestion_position])
            existing_decision = self._normalize_known_speaker_editor_decision(
                segment.get(KNOWN_SPEAKER_EDITOR_DECISION_FIELD)
            )
            if decision is None:
                if KNOWN_SPEAKER_EDITOR_DECISION_FIELD in segment:
                    del segment[KNOWN_SPEAKER_EDITOR_DECISION_FIELD]
                    changed += 1
                continue
            if existing_decision == decision:
                continue
            segment[KNOWN_SPEAKER_EDITOR_DECISION_FIELD] = decision
            changed += 1
        if not changed:
            return 0
        replacements = StagedFileReplacementGroup()
        try:
            self._write_speakers_data(data, replacements=replacements)
            replacements.save_model(self, update_fields=["speakers"])
        except Exception:
            replacements.rollback()
            raise
        return changed

    def get_known_speaker_editor_decisions(self) -> dict[int, dict[str, str]]:
        """Return valid per-segment editor decisions keyed by sidecar position."""
        decisions: dict[int, dict[str, str]] = {}
        for position, segment in enumerate(self.get_speaker_suggestions()):
            decision = self._normalize_known_speaker_editor_decision(segment.get(KNOWN_SPEAKER_EDITOR_DECISION_FIELD))
            if decision is not None:
                decisions[position] = decision
        return decisions

    @classmethod
    def _normalize_known_speaker_editor_decision(cls, decision: object) -> dict[str, str] | None:
        if not isinstance(decision, Mapping):
            return None
        action = decision.get("action")
        if action == KNOWN_SPEAKER_DECISION_REJECT:
            return {"action": KNOWN_SPEAKER_DECISION_REJECT, "speaker": ""}
        if action not in {KNOWN_SPEAKER_DECISION_APPROVE, KNOWN_SPEAKER_DECISION_CORRECT}:
            return None
        speaker = cls._clean_speaker_label(decision.get("speaker"))
        if not speaker:
            return None
        return {"action": str(action), "speaker": speaker}

    @classmethod
    def _segment_has_reject_decision(cls, segment: Mapping[str, object]) -> bool:
        decision = cls._normalize_known_speaker_editor_decision(segment.get(KNOWN_SPEAKER_EDITOR_DECISION_FIELD))
        return bool(decision and decision["action"] == KNOWN_SPEAKER_DECISION_REJECT)

    def _write_speakers_data(
        self, data: dict[str, Any], *, replacements: StagedFileReplacementGroup | None = None
    ) -> None:
        content = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self._save_file_content("speakers", content, replacements=replacements)

    @staticmethod
    def _resolve_known_speaker_display_names(suggestions: list[dict], *, smooth: bool) -> list[str | None]:
        """Per-segment display speaker: confident as-is, uncertain smoothed.

        Smoothing carries the previous confident speaker forward over uncertain
        segments, then backfills any leading uncertain run from the first
        confident speaker, so every segment between known speakers is attributed.
        """
        confident: list[str | None] = []
        for segment in suggestions:
            name = segment.get("speaker")
            confident.append(name if (name and not segment.get("speaker_uncertain")) else None)
        display_names: list[str | None]
        if not smooth:
            display_names = confident
        else:
            smoothed: list[str | None] = list(confident)
            last: str | None = None
            for position, name in enumerate(smoothed):
                if name is not None:
                    last = name
                elif last is not None:
                    smoothed[position] = last
            following: str | None = None
            for position in range(len(smoothed) - 1, -1, -1):
                if smoothed[position] is not None:
                    following = smoothed[position]
                elif following is not None:
                    smoothed[position] = following
            display_names = smoothed
        for position, segment in enumerate(suggestions):
            decision = Transcript._normalize_known_speaker_editor_decision(
                segment.get(KNOWN_SPEAKER_EDITOR_DECISION_FIELD)
            )
            if decision is None:
                continue
            display_names[position] = (
                None if decision["action"] == KNOWN_SPEAKER_DECISION_REJECT else decision["speaker"]
            )
        return display_names

    def _apply_suggestions_to_podlove(
        self, names_by_start_ms: dict[int, str], *, replacements: StagedFileReplacementGroup | None = None
    ) -> int:
        data = self._load_transcript_json("podlove")
        segments = data.get("transcripts")
        if not isinstance(segments, list):
            return 0
        applied = 0
        for segment in segments:
            if not isinstance(segment, dict):
                continue
            start_ms = segment.get("start_ms")
            if not isinstance(start_ms, int):
                continue
            name = names_by_start_ms.get(start_ms)
            if name:
                segment["speaker"] = name
                segment["voice"] = name
                applied += 1
        if applied:
            self._write_transcript_json("podlove", data, replacements=replacements)
        return applied

    def _apply_suggestions_to_dote(
        self, names_by_start_ms: dict[int, str], *, replacements: StagedFileReplacementGroup | None = None
    ) -> int:
        data = self._load_transcript_json("dote")
        lines = data.get("lines")
        if not isinstance(lines, list):
            return 0
        applied = 0
        for line in lines:
            if not isinstance(line, dict):
                continue
            start_ms = _dote_timestamp_to_ms(line.get("startTime"))
            if start_ms is None:
                continue
            name = names_by_start_ms.get(start_ms)
            if name:
                line["speakerDesignation"] = name
                applied += 1
        if applied:
            self._write_transcript_json("dote", data, replacements=replacements)
        return applied

    def _clear_suggestions_from_podlove(
        self, start_milliseconds: set[int], *, replacements: StagedFileReplacementGroup | None = None
    ) -> int:
        data = self._load_transcript_json("podlove")
        segments = data.get("transcripts")
        if not isinstance(segments, list):
            return 0
        applied = 0
        changed = False
        for segment in segments:
            if not isinstance(segment, dict):
                continue
            start_ms = segment.get("start_ms")
            if not isinstance(start_ms, int) or start_ms not in start_milliseconds:
                continue
            applied += 1
            changed = changed or segment.get("speaker") != "" or segment.get("voice") != ""
            segment["speaker"] = ""
            segment["voice"] = ""
        if changed:
            self._write_transcript_json("podlove", data, replacements=replacements)
        return applied

    def _clear_suggestions_from_dote(
        self, start_milliseconds: set[int], *, replacements: StagedFileReplacementGroup | None = None
    ) -> int:
        data = self._load_transcript_json("dote")
        lines = data.get("lines")
        if not isinstance(lines, list):
            return 0
        applied = 0
        changed = False
        for line in lines:
            if not isinstance(line, dict):
                continue
            start_ms = _dote_timestamp_to_ms(line.get("startTime"))
            if start_ms is None or start_ms not in start_milliseconds:
                continue
            applied += 1
            changed = changed or line.get("speakerDesignation") != ""
            line["speakerDesignation"] = ""
        if changed:
            self._write_transcript_json("dote", data, replacements=replacements)
        return applied

    def _clear_suggestions_from_webvtt(
        self, start_milliseconds: set[int], *, replacements: StagedFileReplacementGroup | None = None
    ) -> int:
        content = self._load_text_file("vtt")
        rewritten_content, applied, changed = self._clear_suggestions_from_webvtt_content(content, start_milliseconds)
        if changed:
            self._save_text_file("vtt", rewritten_content, replacements=replacements)
        return applied

    @classmethod
    def _clear_suggestions_from_webvtt_content(
        cls, content: str, start_milliseconds: set[int]
    ) -> tuple[str, int, bool]:
        rewritten_lines: list[str] = []
        payload_lines: list[str] | None = None
        should_clear = False
        applied = 0
        changed = False

        def flush_payload() -> None:
            nonlocal applied, changed, payload_lines, should_clear
            if payload_lines is None:
                return
            lines = payload_lines
            if should_clear:
                lines, cue_changed, cue_applied = cls._clear_webvtt_cue_voice(lines)
                if cue_applied:
                    applied += 1
                changed = changed or cue_changed
            rewritten_lines.extend(lines)
            payload_lines = None
            should_clear = False

        for line in content.splitlines(keepends=True):
            if payload_lines is not None:
                if not line.strip():
                    flush_payload()
                    rewritten_lines.append(line)
                else:
                    payload_lines.append(line)
                continue

            if WEBVTT_TIMING_SEPARATOR in line:
                start_ms = _webvtt_timing_line_start_ms(line)
                should_clear = start_ms in start_milliseconds if start_ms is not None else False
                payload_lines = []
            rewritten_lines.append(line)

        flush_payload()
        return "".join(rewritten_lines), applied, changed

    @classmethod
    def _clear_webvtt_cue_voice(cls, lines: list[str]) -> tuple[list[str], bool, bool]:
        if not lines:
            return lines, False, False
        rewritten_lines = []
        changed = False
        for line in lines:
            rewritten_line = WEBVTT_VOICE_OPENING_RE.sub("", line)
            rewritten_line = WEBVTT_VOICE_CLOSING_RE.sub("", rewritten_line)
            changed = changed or rewritten_line != line
            rewritten_lines.append(rewritten_line)
        return rewritten_lines, changed, True

    def _apply_suggestions_to_webvtt(
        self, names_by_start_ms: dict[int, str], *, replacements: StagedFileReplacementGroup | None = None
    ) -> int:
        content = self._load_text_file("vtt")
        rewritten_content, applied, changed = self._apply_suggestions_to_webvtt_content(content, names_by_start_ms)
        if changed:
            self._save_text_file("vtt", rewritten_content, replacements=replacements)
        return applied

    @classmethod
    def _apply_suggestions_to_webvtt_content(
        cls, content: str, names_by_start_ms: Mapping[int, str]
    ) -> tuple[str, int, bool]:
        rewritten_lines: list[str] = []
        payload_lines: list[str] | None = None
        current_name: str | None = None
        applied = 0
        changed = False

        def flush_payload() -> None:
            nonlocal applied, changed, current_name, payload_lines
            if payload_lines is None:
                return
            lines = payload_lines
            if current_name:
                lines, cue_changed, cue_applied = cls._set_webvtt_cue_voice(lines, current_name)
                if cue_applied:
                    applied += 1
                changed = changed or cue_changed
            rewritten_lines.extend(lines)
            current_name = None
            payload_lines = None

        for line in content.splitlines(keepends=True):
            if payload_lines is not None:
                if not line.strip():
                    flush_payload()
                    rewritten_lines.append(line)
                else:
                    payload_lines.append(line)
                continue

            if WEBVTT_TIMING_SEPARATOR in line:
                start_ms = _webvtt_timing_line_start_ms(line)
                current_name = names_by_start_ms.get(start_ms) if start_ms is not None else None
                payload_lines = []
            rewritten_lines.append(line)

        flush_payload()
        return "".join(rewritten_lines), applied, changed

    @classmethod
    def _set_webvtt_cue_voice(cls, lines: list[str], name: str) -> tuple[list[str], bool, bool]:
        rewritten_lines = []
        changed = False
        has_voice_opening = False
        for line in lines:
            rewritten_line, line_changed, line_has_voice_opening = cls._set_webvtt_payload_line_voice(line, name)
            rewritten_lines.append(rewritten_line)
            changed = changed or line_changed
            has_voice_opening = has_voice_opening or line_has_voice_opening
        if has_voice_opening:
            return rewritten_lines, changed, True
        if not rewritten_lines:
            return rewritten_lines, False, False
        rewritten_lines[0] = f"{cls._webvtt_voice_opening(name)}{rewritten_lines[0]}"
        return rewritten_lines, True, True

    @classmethod
    def _set_webvtt_payload_line_voice(cls, line: str, name: str) -> tuple[str, bool, bool]:
        rewritten_line, replacements = WEBVTT_VOICE_OPENING_RE.subn(
            lambda _match: cls._webvtt_voice_opening(name),
            line,
        )
        return rewritten_line, rewritten_line != line, replacements > 0

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
        if self.vtt:
            labels.update(self._get_webvtt_speaker_labels(self._load_text_file("vtt")))
        return sorted(labels)

    @classmethod
    def _get_webvtt_speaker_labels(cls, content: str) -> set[str]:
        labels: set[str] = set()
        in_cue_payload = False
        for line in content.splitlines():
            stripped = line.strip()
            if not stripped:
                in_cue_payload = False
                continue
            if WEBVTT_TIMING_SEPARATOR in line:
                in_cue_payload = True
                continue
            if not in_cue_payload:
                continue
            for match in WEBVTT_VOICE_OPENING_RE.finditer(line):
                label = cls._clean_speaker_label(match.group("label"))
                if label:
                    labels.add(label)
            generic_prefix_match = WEBVTT_GENERIC_SPEAKER_PREFIX_RE.match(stripped)
            if generic_prefix_match is not None:
                label = cls._clean_speaker_label(generic_prefix_match.group("label"))
                labels.add(label)
        return labels

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

    def get_voice_reference_candidates(
        self,
        *,
        target_seconds: Decimal = VOICE_REFERENCE_CANDIDATE_TARGET_SECONDS,
        min_seconds: Decimal = VOICE_REFERENCE_CANDIDATE_MIN_SECONDS,
        max_gap_seconds: Decimal = VOICE_REFERENCE_CANDIDATE_MAX_GAP_SECONDS,
        limit_per_speaker: int = VOICE_REFERENCE_CANDIDATE_LIMIT,
    ) -> list[TranscriptVoiceReferenceCandidate]:
        """Return source-range candidates derived from diarized Podlove segments.

        Candidates are contiguous, same-label Podlove runs with usable start and
        end times. Derivation is read-only: transcript files and private
        known-speaker sidecars are never mutated by this helper.
        """
        if limit_per_speaker <= 0:
            return []
        target_seconds = _quantize_seconds(Decimal(str(target_seconds)))
        min_seconds = _quantize_seconds(Decimal(str(min_seconds)))
        max_gap_seconds = _quantize_seconds(Decimal(str(max_gap_seconds)))
        if target_seconds <= 0 or min_seconds <= 0 or max_gap_seconds < 0:
            return []

        candidates_by_speaker: dict[str, list[TranscriptVoiceReferenceCandidate]] = {}
        for run in self._get_podlove_voice_reference_runs(max_gap_seconds=max_gap_seconds):
            candidate = self._build_voice_reference_candidate_from_run(
                run,
                target_seconds=target_seconds,
                min_seconds=min_seconds,
            )
            if candidate is None:
                continue
            candidates_by_speaker.setdefault(candidate.speaker_label, []).append(candidate)

        ranked_candidates: list[TranscriptVoiceReferenceCandidate] = []
        for speaker_label in sorted(candidates_by_speaker):
            speaker_candidates = sorted(
                candidates_by_speaker[speaker_label],
                key=lambda candidate: (-candidate.duration_seconds, candidate.start_seconds, candidate.end_seconds),
            )
            for rank, candidate in enumerate(speaker_candidates[:limit_per_speaker], start=1):
                ranked_candidates.append(replace(candidate, rank=rank))
        return ranked_candidates

    def rewrite_speaker_labels(self, mapping: Mapping[str, str]) -> bool:
        """Rewrite speaker labels in stored transcript artifacts.

        The mapping is destructive: matching Podlove ``speaker``/``voice``,
        DOTe ``speakerDesignation``, and WebVTT voice-label values are replaced
        in-place.
        """
        cleaned_mapping: dict[str, str] = {}
        for source, target in mapping.items():
            source_label = self._clean_speaker_label(source)
            target_label = self._clean_speaker_label(target)
            if source_label and target_label and source_label != target_label:
                cleaned_mapping[source_label] = target_label
        if not cleaned_mapping:
            return False

        changed_fields = []
        replacements = StagedFileReplacementGroup()
        try:
            podlove_data = self._load_transcript_json("podlove")
            if self._rewrite_podlove_speakers(podlove_data, cleaned_mapping):
                self._save_json_file("podlove", podlove_data, replacements=replacements)
                changed_fields.append("podlove")

            dote_data = self._load_transcript_json("dote")
            if self._rewrite_dote_speakers(dote_data, cleaned_mapping):
                self._save_json_file("dote", dote_data, replacements=replacements)
                changed_fields.append("dote")

            if self.vtt:
                vtt_content = self._load_text_file("vtt")
                rewritten_vtt_content, vtt_changed = self._rewrite_webvtt_speakers(vtt_content, cleaned_mapping)
                if vtt_changed:
                    self._save_text_file("vtt", rewritten_vtt_content, replacements=replacements)
                    changed_fields.append("vtt")

            if not changed_fields:
                return False
            replacements.save_model(self, update_fields=changed_fields)
        except Exception:
            replacements.rollback()
            raise
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

    def _get_podlove_voice_reference_runs(
        self, *, max_gap_seconds: Decimal = VOICE_REFERENCE_CANDIDATE_MAX_GAP_SECONDS
    ) -> list[list[_PodloveVoiceReferenceSegment]]:
        runs: list[list[_PodloveVoiceReferenceSegment]] = []
        current_run: list[_PodloveVoiceReferenceSegment] = []
        podlove_data = self._load_transcript_json("podlove")
        for position, segment in enumerate(podlove_data.get("transcripts", [])):
            parsed_segment = self._parse_podlove_voice_reference_segment(segment, position=position)
            if parsed_segment is None:
                if current_run:
                    runs.append(current_run)
                    current_run = []
                continue
            if (
                current_run
                and parsed_segment.speaker_label == current_run[-1].speaker_label
                and Decimal("0") <= parsed_segment.start_seconds - current_run[-1].end_seconds <= max_gap_seconds
            ):
                current_run.append(parsed_segment)
            else:
                if current_run:
                    runs.append(current_run)
                current_run = [parsed_segment]
        if current_run:
            runs.append(current_run)
        return runs

    @classmethod
    def _parse_podlove_voice_reference_segment(
        cls, segment: Any, *, position: int
    ) -> _PodloveVoiceReferenceSegment | None:
        if not isinstance(segment, dict):
            return None
        speaker_labels = {
            label
            for field_name in ("speaker", "voice")
            if (label := cls._clean_speaker_label(segment.get(field_name)))
        }
        if len(speaker_labels) != 1:
            return None
        text = cls._clean_sample_text(segment.get("text"))
        if not text:
            return None
        start_seconds = cls._parse_record_decimal_seconds(
            segment,
            millisecond_field="start_ms",
            timestamp_fields=("start", "startTime"),
        )
        end_seconds = cls._parse_record_decimal_seconds(
            segment,
            millisecond_field="end_ms",
            timestamp_fields=("end", "endTime"),
        )
        if start_seconds is None or end_seconds is None or start_seconds >= end_seconds:
            return None
        return _PodloveVoiceReferenceSegment(
            speaker_label=next(iter(speaker_labels)),
            start_seconds=start_seconds,
            end_seconds=end_seconds,
            text=text,
            position=position,
        )

    @classmethod
    def _build_voice_reference_candidate_from_run(
        cls,
        run: list[_PodloveVoiceReferenceSegment],
        *,
        target_seconds: Decimal,
        min_seconds: Decimal,
    ) -> TranscriptVoiceReferenceCandidate | None:
        if not run:
            return None
        start_seconds = run[0].start_seconds
        uncapped_end_seconds = run[-1].end_seconds
        end_seconds = min(uncapped_end_seconds, start_seconds + target_seconds)
        duration_seconds = _quantize_seconds(end_seconds - start_seconds)
        if duration_seconds < min_seconds:
            return None
        text = cls._truncate_sample_text(
            " ".join(segment.text for segment in run if segment.start_seconds < end_seconds),
            max_chars=VOICE_REFERENCE_CANDIDATE_MAX_CHARS,
        )
        return TranscriptVoiceReferenceCandidate(
            speaker_label=run[0].speaker_label,
            start_seconds=start_seconds,
            end_seconds=end_seconds,
            duration_seconds=duration_seconds,
            text=text,
            rank=0,
        )

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

    @classmethod
    def _parse_record_decimal_seconds(
        cls,
        record: dict[str, Any],
        *,
        millisecond_field: str,
        timestamp_fields: tuple[str, ...],
    ) -> Decimal | None:
        milliseconds = record.get(millisecond_field)
        if not isinstance(milliseconds, bool) and isinstance(milliseconds, int | float) and milliseconds >= 0:
            return _quantize_seconds(Decimal(str(milliseconds)) / Decimal("1000"))
        for field_name in timestamp_fields:
            seconds = cls._parse_timestamp_decimal_seconds(record.get(field_name))
            if seconds is not None:
                return seconds
        return None

    @staticmethod
    def _parse_timestamp_decimal_seconds(value: Any) -> Decimal | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, int | float):
            return _quantize_seconds(Decimal(str(value))) if value >= 0 else None
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
                seconds = Decimal(parts[2])
            elif len(parts) == 2:
                hours = 0
                minutes = int(parts[0])
                seconds = Decimal(parts[1])
            elif len(parts) == 1:
                seconds = Decimal(timestamp)
                return _quantize_seconds(seconds) if seconds >= 0 else None
            else:
                return None
        except (ValueError, ArithmeticError):
            return None
        total_seconds = (Decimal(hours) * Decimal("3600")) + (Decimal(minutes) * Decimal("60")) + seconds
        return _quantize_seconds(total_seconds) if total_seconds >= 0 else None

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

    @classmethod
    def _rewrite_webvtt_speakers(cls, content: str, mapping: Mapping[str, str]) -> tuple[str, bool]:
        rewritten_lines = []
        changed = False
        in_cue_payload = False
        for line in content.splitlines(keepends=True):
            stripped = line.strip()
            if not stripped:
                in_cue_payload = False
                rewritten_lines.append(line)
            elif WEBVTT_TIMING_SEPARATOR in line:
                in_cue_payload = True
                rewritten_lines.append(line)
            elif in_cue_payload:
                line, line_changed = cls._rewrite_webvtt_payload_line(line, mapping)
                changed = changed or line_changed
                rewritten_lines.append(line)
            else:
                rewritten_lines.append(line)
        return "".join(rewritten_lines), changed

    @classmethod
    def _rewrite_webvtt_payload_line(cls, line: str, mapping: Mapping[str, str]) -> tuple[str, bool]:
        def replace_voice_opening(match: re.Match[str]) -> str:
            label = cls._clean_speaker_label(match.group("label"))
            target_label = mapping.get(label)
            if target_label is None:
                return match.group(0)
            return cls._webvtt_voice_opening(target_label, classes=match.group("classes"))

        rewritten_line = WEBVTT_VOICE_OPENING_RE.sub(replace_voice_opening, line)
        return rewritten_line, rewritten_line != line

    @staticmethod
    def _webvtt_voice_opening(label: str, *, classes: str = "") -> str:
        return f"<v{classes} {label}>"


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
        return Transcript._clean_speaker_label(self.display_name)

    def clean(self) -> None:
        super().clean()
        self.speaker_label = Transcript._clean_speaker_label(self.speaker_label)
        self.display_name = Transcript._clean_speaker_label(self.display_name)
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
