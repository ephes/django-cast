"""Forms for managing cast media, chapter marks, transcripts, and themes.

Provides model forms for Audio, Video, and Transcript CRUD in the Wagtail
admin, chapter mark parsing and validation, a theme selection form, and
a search form that rejects empty queries.
"""

import json
import logging
import subprocess
from datetime import datetime, time
from typing import IO, Any, NoReturn, cast

from django import forms
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import UploadedFile
from django.forms.models import modelform_factory
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from wagtail.admin import widgets
from wagtail.admin.forms.collections import BaseCollectionMemberForm
from wagtail.admin.forms.search import SearchForm
from wagtail.permission_policies.collections import CollectionOwnershipPermissionPolicy, CollectionPermissionPolicy

from .media_validation import validate_audio_upload, validate_video_upload
from .media_derivation import (
    save_audio_with_derivations,
    save_transcript_with_derivations,
    save_video_with_derivations,
)
from .models import (
    Audio,
    ChapterMark,
    Contributor,
    EpisodeContributor,
    Transcript,
    TranscriptSpeakerMapping,
    Video,
    get_template_base_dir_choices,
)
from .models.contributors import ContributorVoiceReference
from .transcripts import known_speakers, parsing
from .transcripts.known_speakers import (
    KNOWN_SPEAKER_DECISION_APPROVE,
    KNOWN_SPEAKER_DECISION_CORRECT,
    KNOWN_SPEAKER_DECISION_REJECT,
    KNOWN_SPEAKER_EDITOR_DECISION_FIELD,
)

logger = logging.getLogger(__name__)


SPEAKER_MAPPING_ACTION = "map-speakers"
KNOWN_SPEAKER_APPLY_ACTION = "apply-known-speakers"
KNOWN_SPEAKER_REVIEW_ACTION = "review-known-speakers"
VOICE_REFERENCE_CREATE_ACTION = "create-voice-reference"
DRAFT_SPEAKER_ASSIGNMENT_PREFIX = "draft:"
KNOWN_SPEAKER_REVIEW_BULK_VALUE = "__bulk__"
KNOWN_SPEAKER_REVIEW_BLANK_VALUE = "__blank__"


class VideoUploadValidationMixin:
    cleaned_data: dict[str, Any]

    def clean_original(self) -> Any:
        original = self.cleaned_data.get("original")
        if isinstance(original, UploadedFile):
            validate_video_upload(original)
        return original

    def save(self, commit: bool = True) -> Video:
        video = super().save(commit=False)  # type: ignore[misc]
        if commit:
            save_video_with_derivations(video)
            self._save_m2m()  # type: ignore[attr-defined]
        return video


class VideoForm(VideoUploadValidationMixin, forms.ModelForm):
    """Simple model form for Video with only the ``original`` file field."""

    class Meta:
        model = Video
        fields = ["original"]


class BaseVideoForm(VideoUploadValidationMixin, BaseCollectionMemberForm):
    """Base form for Video admin views with tag and file widgets, plus collection support."""

    class Meta:
        widgets = {
            "tags": widgets.AdminTagWidget,
            "original": forms.FileInput,
            "poster": forms.ClearableFileInput,
        }

    permission_policy = CollectionOwnershipPermissionPolicy(Video, auth_model=Video, owner_field_name="user")


def get_video_form() -> type[forms.ModelForm]:
    """Return a model form class for Video, ensuring the collection field is included."""
    fields = Video.admin_form_fields
    if "collection" not in fields:
        # force addition of the 'collection' field, because leaving it out can
        # cause dubious results when multiple collections exist (e.g. adding the
        # media to the root collection where the user may not have permission) -
        # and when only one collection exists, it will get hidden anyway.
        fields = cast(tuple[str, str, str, str], tuple(list(fields) + ["collection"]))

    return modelform_factory(
        Video,
        form=BaseVideoForm,
        fields=fields,
    )


class ChapterMarkForm(forms.ModelForm):
    """Model form for manually creating or editing a single chapter mark."""

    class Meta:
        model = ChapterMark
        fields = ("start", "title", "link", "image")


class FFProbeStartField(forms.TimeField):
    """Time field that converts an ffprobe-style seconds-since-epoch float to a ``time`` object."""

    def to_python(self, value: Any) -> time | None:
        if value in self.empty_values or isinstance(value, time):
            return super().to_python(value)
        try:
            # utcfromtimestamp, super important!
            return datetime.utcfromtimestamp(float(value)).time()
        except (TypeError, ValueError):
            raise ValidationError(
                _(f"Invalid chaptermark start: {value}"),
                code="invalid",
                params={"start": value},
            )


class FFProbeChapterMarkForm(forms.ModelForm):
    """Model form for chapter marks extracted from audio files via ffprobe."""

    start = FFProbeStartField()

    class Meta:
        model = ChapterMark
        fields = ("start", "title")


def parse_chaptermark_line(line: str) -> ChapterMark:
    """Parse a single ``HH:MM:SS Title text`` line into an unsaved ChapterMark."""

    def raise_line_validation_error() -> NoReturn:
        raise ValidationError(
            _(f"Invalid chaptermark line: {line}"),
            code="invalid",
            params={"line": line},
        )

    line_parts = line.split()
    if len(line_parts) < 2:
        raise_line_validation_error()
    start, *parts = line_parts
    title = " ".join(parts)
    form = ChapterMarkForm({"start": start, "title": title})
    if form.is_valid():
        return form.save(commit=False)
    else:
        return raise_line_validation_error()


class ChapterMarksField(forms.CharField):
    """Multi-line text field that parses each line into a ChapterMark instance."""

    def to_python(self, value: str | None) -> list[ChapterMark]:  # type: ignore[override]
        if value is None:
            return []
        chaptermarks = []
        for line in value.split("\n"):
            if len(line) == 0:
                # skip empty lines
                continue
            chaptermarks.append(parse_chaptermark_line(line))
        return chaptermarks


class AudioForm(BaseCollectionMemberForm):
    """Form for creating and editing Audio objects in the Wagtail admin.

    Includes a ``chaptermarks`` text area where editors can paste chapter
    marks line by line. On save, chapter marks are synced: manually entered
    marks take priority, otherwise marks are extracted from uploaded audio
    files via ffprobe.
    """

    chaptermarks = ChapterMarksField(widget=forms.Textarea, required=False)
    permission_policy = CollectionOwnershipPermissionPolicy(Audio, auth_model=Audio, owner_field_name="user")

    class Meta:
        model = Audio
        fields = list(Audio.admin_form_fields) + ["collection"]
        widgets = {
            "tags": widgets.AdminTagWidget,
            "m4a": forms.ClearableFileInput,
            "mp3": forms.ClearableFileInput,
            "oga": forms.ClearableFileInput,
            "opus": forms.ClearableFileInput,
        }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fields["transcript_diarization_mode"].required = False

    def clean_transcript_diarization_mode(self) -> str:
        return self.cleaned_data.get("transcript_diarization_mode") or Audio.TranscriptDiarizationMode.INHERIT

    def clean_m4a(self) -> Any:
        return self._clean_audio_upload("m4a")

    def clean_mp3(self) -> Any:
        return self._clean_audio_upload("mp3")

    def clean_oga(self) -> Any:
        return self._clean_audio_upload("oga")

    def clean_opus(self) -> Any:
        return self._clean_audio_upload("opus")

    def _clean_audio_upload(self, audio_format: str) -> Any:
        upload = self.cleaned_data.get(audio_format)
        if isinstance(upload, UploadedFile):
            validate_audio_upload(upload, audio_format=audio_format)
        return upload

    def get_chaptermarks_from_field_or_files(self, audio: Audio) -> list[ChapterMark]:
        chaptermarks = self.cleaned_data["chaptermarks"]
        if len(chaptermarks) == 0:
            # get chaptermarks from one of the changed files
            changed_audio_formats = []
            for audio_format in audio.audio_formats:
                form_file = self.cleaned_data.get(audio_format)
                if form_file is None:
                    continue
                if form_file != getattr(audio, audio_format):
                    changed_audio_formats.append(audio_format)
            if len(changed_audio_formats) == 0:
                return []
            try:
                chaptermark_data = audio.get_chaptermark_data_from_file(changed_audio_formats[0])
            except (subprocess.TimeoutExpired, subprocess.CalledProcessError, OSError, ValueError, KeyError):
                logger.warning("Skipping audio chapter extraction after probe failure", exc_info=True)
                return []
            for data in chaptermark_data:
                form = FFProbeChapterMarkForm(data)
                if form.is_valid():
                    chaptermarks.append(form.save(commit=False))
        return chaptermarks

    def save_chaptermarks(self, audio: Audio) -> None:
        # Chapter marks should be saved following this logic:
        #  1. If there are manually added chapter marks in the form, just use them
        #  2. If the form has no chapter marks, but an audio file was changed or
        #     added, look for chapter marks in the audio content
        #  3. Sync changed chapter marks back to database
        chaptermarks = self.get_chaptermarks_from_field_or_files(audio)
        for cm in chaptermarks:
            cm.audio = audio
        ChapterMark.objects.sync_chaptermarks(audio, chaptermarks)

    def save(self, commit: bool = True) -> Audio:
        audio = super().save(commit=False)
        if commit:
            save_audio_with_derivations(audio)
            self._save_m2m()
            self.save_chaptermarks(audio)
        return audio


class TranscriptForm(BaseCollectionMemberForm):
    """Form for creating and editing Transcript objects in the Wagtail admin.

    Validates uploaded transcript files: Podlove JSON must contain a
    ``transcripts`` key, DOTe JSON must contain ``lines`` with required
    fields, and WebVTT files must start with the ``WEBVTT`` header.
    """

    permission_policy = CollectionPermissionPolicy(Transcript)

    class Meta:
        model = Transcript
        fields = list(Transcript.admin_form_fields) + ["collection"]
        widgets = {
            "podlove": forms.ClearableFileInput,
            "vtt": forms.ClearableFileInput,
            "dote": forms.ClearableFileInput,
        }

    def clean_podlove(self) -> Any:
        podlove = self.cleaned_data.get("podlove")
        if not podlove:
            return podlove
        data = self._load_json(podlove, field_label="Podlove")
        if not isinstance(data, dict) or "transcripts" not in data:
            raise ValidationError(_("Podlove transcript must include a top-level 'transcripts' key."))
        if not isinstance(data["transcripts"], list):
            raise ValidationError(_("Podlove transcript 'transcripts' must be a list."))
        return podlove

    def clean_dote(self) -> Any:
        dote = self.cleaned_data.get("dote")
        if not dote:
            return dote
        data = self._load_json(dote, field_label="DOTe")
        if not isinstance(data, dict) or "lines" not in data:
            raise ValidationError(_("DOTe transcript must include a top-level 'lines' key."))
        lines = data["lines"]
        if not isinstance(lines, list):
            raise ValidationError(_("DOTe transcript 'lines' must be a list."))
        required_keys = {"startTime", "endTime", "speakerDesignation", "text"}
        for line in lines:
            if not isinstance(line, dict):
                raise ValidationError(_("DOTe transcript lines must be objects."))
            missing_keys = required_keys.difference(line.keys())
            if missing_keys:
                missing_display = ", ".join(sorted(missing_keys))
                raise ValidationError(
                    _("DOTe transcript lines must include keys: %(keys)s."),
                    params={"keys": missing_display},
                )
        return dote

    def clean_vtt(self) -> Any:
        vtt = self.cleaned_data.get("vtt")
        if not vtt:
            return vtt
        header = self._read_header(vtt)
        if not header.startswith("WEBVTT"):
            raise ValidationError(_("WebVTT transcripts must start with the WEBVTT header."))
        return vtt

    def save(self, commit: bool = True) -> Transcript:
        transcript = super().save(commit=False)
        if commit:
            save_transcript_with_derivations(transcript)
            self._save_m2m()
        return transcript

    @staticmethod
    def _load_json(uploaded_file: UploadedFile | IO[str] | IO[bytes], *, field_label: str) -> Any:
        try:
            uploaded_file.seek(0)
            return json.load(uploaded_file)
        except (json.JSONDecodeError, TypeError, UnicodeDecodeError):
            raise ValidationError(_("%(field)s transcript is not valid JSON."), params={"field": field_label})
        finally:
            try:
                uploaded_file.seek(0)
            except Exception:
                pass

    @staticmethod
    def _read_header(uploaded_file: UploadedFile | IO[str] | IO[bytes], size: int = 32) -> str:
        try:
            uploaded_file.seek(0)
            header = uploaded_file.read(size)
        finally:
            try:
                uploaded_file.seek(0)
            except Exception:
                pass
        if isinstance(header, bytes):
            return header.decode("utf-8-sig", errors="ignore").lstrip()
        return str(header).lstrip()


class SpeakerContributorMappingForm(forms.Form):
    """Dynamic form mapping raw transcript speaker labels to durable targets."""

    action = forms.CharField(initial=SPEAKER_MAPPING_ACTION, widget=forms.HiddenInput())
    speaker_mapping: dict[str, str]
    mapping_updates: dict[str, dict[str, Any]]

    def __init__(
        self,
        *args: Any,
        speaker_mappings: list[TranscriptSpeakerMapping] | None = None,
        speaker_labels: list[str] | None = None,
        contributor_assignments: list[EpisodeContributor],
        multiple_episodes: bool = False,
        source_episode: Any | None = None,
        **kwargs: Any,
    ) -> None:
        del source_episode
        super().__init__(*args, **kwargs)
        self.speaker_mappings = speaker_mappings or []
        self.speaker_labels = speaker_labels or [mapping.speaker_label for mapping in self.speaker_mappings]
        self.contributor_assignments = contributor_assignments
        self.contributor_lookup: dict[str, Contributor] = {}
        self.contributor_value_by_id: dict[int, str] = {}
        choices: list[tuple[str, str]] = [("", str(_("Unmapped")))]
        seen_contributor_values = set()
        for assignment in contributor_assignments:
            assignment_value = self._assignment_value(assignment)
            if assignment_value in seen_contributor_values:
                continue
            seen_contributor_values.add(assignment_value)
            self.contributor_lookup[assignment_value] = assignment.contributor
            if assignment.contributor_id is not None:
                self.contributor_value_by_id.setdefault(assignment.contributor_id, assignment_value)
            choices.append((assignment_value, self._assignment_label(assignment, multiple_episodes=multiple_episodes)))
        self.speaker_field_names: dict[str, str] = {}
        self.display_field_names: dict[str, str] = {}
        self.mapping_by_label = {mapping.speaker_label: mapping for mapping in self.speaker_mappings}
        for index, speaker_label in enumerate(self.speaker_labels):
            field_name = f"speaker_{index}"
            display_field_name = f"speaker_display_name_{index}"
            mapping = self.mapping_by_label.get(speaker_label)
            self.speaker_field_names[field_name] = speaker_label
            self.display_field_names[display_field_name] = speaker_label
            target_field = forms.ChoiceField(label=speaker_label, choices=choices, required=False)
            display_field = forms.CharField(label=_("One-off display name"), max_length=128, required=False)
            if mapping is not None:
                if mapping.contributor_id is not None:
                    target_field.initial = self.contributor_value_by_id.get(mapping.contributor_id, "")
                elif mapping.display_name:
                    display_field.initial = mapping.display_name
            self.fields[field_name] = target_field
            self.fields[display_field_name] = display_field

    @staticmethod
    def _assignment_value(assignment: EpisodeContributor) -> str:
        if assignment.pk is not None:
            return str(assignment.pk)
        # Draft revision inline children do not have primary keys yet; use the episode/contributor/role tuple
        # that uniquely identifies persisted episode contributor assignments instead of a request-local index.
        return (
            f"{DRAFT_SPEAKER_ASSIGNMENT_PREFIX}{assignment.episode.pk}:{assignment.contributor_id}:{assignment.role}"
        )

    @staticmethod
    def _assignment_label(assignment: EpisodeContributor, *, multiple_episodes: bool) -> str:
        label = f"{assignment.display_name} ({assignment.get_role_display()})"
        if multiple_episodes:
            label = f"{label} — {assignment.episode.title}"
        return label

    def clean(self) -> dict[str, Any]:
        cleaned_data = super().clean() or {}
        speaker_mapping = {}
        mapping_updates: dict[str, dict[str, Any]] = {}
        raw_speaker_labels = {parsing.clean_speaker_label(label) for label in self.speaker_labels}
        display_field_by_label = {
            speaker_label: field_name for field_name, speaker_label in self.display_field_names.items()
        }
        for field_name, speaker_label in self.speaker_field_names.items():
            contributor_value = cleaned_data.get(field_name)
            display_name = parsing.clean_speaker_label(cleaned_data.get(display_field_by_label[speaker_label]))
            contributor = self.contributor_lookup.get(contributor_value) if contributor_value else None
            if contributor_value and contributor is None:
                self.add_error(field_name, _("Select a valid contributor."))
                continue
            if contributor is not None and display_name:
                self.add_error(display_field_by_label[speaker_label], _("Use either a contributor or a display name."))
                continue
            if display_name and display_name in raw_speaker_labels:
                self.add_error(
                    display_field_by_label[speaker_label],
                    _("Use a display name that does not match a raw transcript speaker label."),
                )
                continue
            if contributor is not None:
                speaker_mapping[speaker_label] = contributor.display_name
            elif display_name:
                speaker_mapping[speaker_label] = display_name
            mapping_updates[speaker_label] = {
                "mapping": self.mapping_by_label.get(speaker_label),
                "contributor": contributor,
                "display_name": display_name,
            }
        self.speaker_mapping = speaker_mapping
        self.mapping_updates = mapping_updates
        return cleaned_data

    def save(self) -> int:
        changed = 0
        now = timezone.now()
        fingerprints_by_transcript_id: dict[int, str] = {}
        for update in self.mapping_updates.values():
            mapping = update["mapping"]
            if mapping is None:
                continue
            contributor = update["contributor"]
            display_name = update["display_name"]
            if contributor is not None or display_name:
                review_state = TranscriptSpeakerMapping.ReviewState.APPROVED
                reviewed_at = now
            else:
                review_state = TranscriptSpeakerMapping.ReviewState.UNMAPPED
                reviewed_at = None
            if mapping.transcript_id not in fingerprints_by_transcript_id:
                fingerprints_by_transcript_id[mapping.transcript_id] = (
                    mapping.transcript.transcript_artifact_fingerprint()
                )
            source_artifact_fingerprint = fingerprints_by_transcript_id[mapping.transcript_id]
            next_values = {
                "contributor": contributor,
                "display_name": display_name,
                "review_state": review_state,
                "reviewed_at": reviewed_at,
                "source_artifact_fingerprint": source_artifact_fingerprint,
                "active": True,
            }
            update_fields = []
            for field_name, value in next_values.items():
                if getattr(mapping, field_name) != value:
                    setattr(mapping, field_name, value)
                    update_fields.append(field_name)
            if update_fields:
                mapping.full_clean()
                mapping.save(update_fields=update_fields)
                changed += 1
        return changed


class KnownSpeakerSegmentReviewForm(forms.Form):
    """Dynamic form for per-segment known-speaker editor decisions."""

    action = forms.CharField(initial=KNOWN_SPEAKER_REVIEW_ACTION, widget=forms.HiddenInput())
    segment_decisions: dict[int, dict[str, str] | None]

    def __init__(
        self,
        *args: Any,
        segments: list[dict[str, Any]],
        contributor_assignments: list[EpisodeContributor],
        multiple_episodes: bool = False,
        **kwargs: Any,
    ) -> None:
        del multiple_episodes
        super().__init__(*args, **kwargs)
        self.segments = segments
        self.segment_field_names: dict[str, int] = {}
        self.speaker_choice_lookup: dict[str, str] = {}
        self.speaker_value_by_name: dict[str, str] = {}
        speaker_names = self._speaker_names(segments, contributor_assignments)
        choices: list[tuple[str, str]] = [
            (KNOWN_SPEAKER_REVIEW_BULK_VALUE, str(_("Use bulk result"))),
            (KNOWN_SPEAKER_REVIEW_BLANK_VALUE, str(_("Leave blank"))),
        ]
        for name in speaker_names:
            value = self._speaker_choice_value(name)
            self.speaker_choice_lookup[value] = name
            self.speaker_value_by_name[name] = value
            choices.append((value, name))
        for position, segment in enumerate(segments):
            field_name = f"known_speaker_segment_{position}"
            self.segment_field_names[field_name] = position
            field = forms.ChoiceField(
                label=_("Resolution"),
                choices=choices,
                required=False,
            )
            field.initial = self._initial_value(segment)
            self.fields[field_name] = field

    @classmethod
    def _speaker_names(
        cls,
        segments: list[dict[str, Any]],
        contributor_assignments: list[EpisodeContributor],
    ) -> list[str]:
        names: list[str] = []
        for segment in segments:
            cls._append_name(names, segment.get("speaker"))
            cls._append_candidate_names(names, segment.get("candidates"))
            decision = known_speakers.normalize_editor_decision(segment.get(KNOWN_SPEAKER_EDITOR_DECISION_FIELD))
            if decision is not None:
                cls._append_name(names, decision["speaker"])
        for assignment in contributor_assignments:
            cls._append_name(names, assignment.display_name)
        return names

    @classmethod
    def _append_candidate_names(cls, names: list[str], candidates: object) -> None:
        if not isinstance(candidates, list):
            return
        for candidate in candidates:
            if isinstance(candidate, dict):
                cls._append_name(
                    names,
                    candidate.get("speaker") or candidate.get("name") or candidate.get("display_name"),
                )
            else:
                cls._append_name(names, candidate)

    @staticmethod
    def _append_name(names: list[str], value: object) -> None:
        name = parsing.clean_speaker_label(value)
        if name and name not in names:
            names.append(name)

    @staticmethod
    def _speaker_choice_value(name: str) -> str:
        return f"speaker:{name}"

    def _initial_value(self, segment: dict[str, Any]) -> str:
        decision = known_speakers.normalize_editor_decision(segment.get(KNOWN_SPEAKER_EDITOR_DECISION_FIELD))
        if decision is None:
            return KNOWN_SPEAKER_REVIEW_BULK_VALUE
        if decision["action"] == KNOWN_SPEAKER_DECISION_REJECT:
            return KNOWN_SPEAKER_REVIEW_BLANK_VALUE
        return self.speaker_value_by_name[decision["speaker"]]

    def clean(self) -> dict[str, Any]:
        cleaned_data = super().clean() or {}
        segment_decisions: dict[int, dict[str, str] | None] = {}
        for field_name, position in self.segment_field_names.items():
            value = cleaned_data.get(field_name) or KNOWN_SPEAKER_REVIEW_BULK_VALUE
            if value == KNOWN_SPEAKER_REVIEW_BULK_VALUE:
                segment_decisions[position] = None
            elif value == KNOWN_SPEAKER_REVIEW_BLANK_VALUE:
                segment_decisions[position] = {"action": KNOWN_SPEAKER_DECISION_REJECT, "speaker": ""}
            else:
                speaker = self.speaker_choice_lookup[value]
                suggested_speaker = parsing.clean_speaker_label(self.segments[position].get("speaker"))
                action = (
                    KNOWN_SPEAKER_DECISION_APPROVE if speaker == suggested_speaker else KNOWN_SPEAKER_DECISION_CORRECT
                )
                segment_decisions[position] = {"action": action, "speaker": speaker}
        self.segment_decisions = segment_decisions
        return cleaned_data


class VoiceReferenceCandidateCreateForm(forms.Form):
    """Validate a transcript voice-reference candidate create action."""

    action = forms.CharField(initial=VOICE_REFERENCE_CREATE_ACTION, widget=forms.HiddenInput())
    speaker_label = forms.CharField(widget=forms.HiddenInput())
    candidate_rank = forms.IntegerField(min_value=1, widget=forms.HiddenInput())
    voice_reference_status = forms.ChoiceField(
        choices=(
            (ContributorVoiceReference.Status.PENDING, _("Save pending reference")),
            (ContributorVoiceReference.Status.APPROVED, _("Create approved reference")),
        )
    )
    consent_confirmed = forms.BooleanField(required=False)

    def clean(self) -> dict[str, Any]:
        cleaned_data = super().clean() or {}
        status = cleaned_data.get("voice_reference_status")
        consent_confirmed = bool(cleaned_data.get("consent_confirmed"))
        if status == ContributorVoiceReference.Status.APPROVED and not consent_confirmed:
            raise ValidationError(_("Creating an approved voice reference requires confirmed contributor consent."))
        return cleaned_data


class NonEmptySearchForm(SearchForm):
    """
    A simple search form that takes a single search term.

    It raises an ValidationError if the search term is empty
    or only consists of spaces. Needed after SearchForm changed
    behaviour in Wagtail 4.2.
    """

    def clean_q(self) -> str:
        """
        Make sure the search term is not empty.
        """
        query = self.cleaned_data["q"].strip()
        if not query:
            raise forms.ValidationError(_("Please enter a search term"))
        return query


class SelectThemeForm(forms.Form):
    """Form for selecting the active template theme via the theme switcher view."""

    template_base_dir = forms.ChoiceField(
        choices=[],
        label=_("Theme"),
        help_text=_("Select a theme for this site."),
        required=True,
    )
    next = forms.CharField(widget=forms.HiddenInput, required=False)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fields["template_base_dir"].choices = get_template_base_dir_choices()  # type: ignore
