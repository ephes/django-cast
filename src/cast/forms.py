"""Forms for managing cast media, chapter marks, transcripts, and themes.

Provides model forms for Audio, Video, and Transcript CRUD in the Wagtail
admin, chapter mark parsing and validation, a theme selection form, and
a search form that rejects empty queries.
"""

import json
from datetime import datetime, time
from typing import Any, cast

from django import forms
from django.core.exceptions import ValidationError
from django.forms.models import modelform_factory
from django.utils.translation import gettext_lazy as _
from wagtail.admin import widgets
from wagtail.admin.forms.collections import BaseCollectionMemberForm
from wagtail.admin.forms.search import SearchForm
from wagtail.permission_policies.collections import CollectionOwnershipPermissionPolicy, CollectionPermissionPolicy

from .models import Audio, ChapterMark, EpisodeContributor, Transcript, Video, get_template_base_dir_choices
from .models.contributors import ContributorVoiceReference
from .models.transcript import (
    KNOWN_SPEAKER_DECISION_APPROVE,
    KNOWN_SPEAKER_DECISION_CORRECT,
    KNOWN_SPEAKER_DECISION_REJECT,
    KNOWN_SPEAKER_EDITOR_DECISION_FIELD,
)


SPEAKER_MAPPING_ACTION = "map-speakers"
KNOWN_SPEAKER_APPLY_ACTION = "apply-known-speakers"
KNOWN_SPEAKER_REVIEW_ACTION = "review-known-speakers"
VOICE_REFERENCE_CREATE_ACTION = "create-voice-reference"
DRAFT_SPEAKER_ASSIGNMENT_PREFIX = "draft:"
KNOWN_SPEAKER_REVIEW_BULK_VALUE = "__bulk__"
KNOWN_SPEAKER_REVIEW_BLANK_VALUE = "__blank__"


class VideoForm(forms.ModelForm):
    """Simple model form for Video with only the ``original`` file field."""

    class Meta:
        model = Video
        fields = ["original"]


class BaseVideoForm(BaseCollectionMemberForm):
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

    def to_python(self, value) -> time:
        try:
            # utcfromtimestamp, super important!
            return datetime.utcfromtimestamp(float(value)).time()
        except ValueError:
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

    def raise_line_validation_error():
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

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.fields["transcript_diarization_mode"].required = False

    def clean_transcript_diarization_mode(self) -> str:
        return self.cleaned_data.get("transcript_diarization_mode") or Audio.TranscriptDiarizationMode.INHERIT

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
            chaptermark_data = audio.get_chaptermark_data_from_file(changed_audio_formats[0])
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

    def save(self, commit=True) -> Audio:
        audio = super().save(commit=commit)
        if commit:
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

    def clean_podlove(self):
        podlove = self.cleaned_data.get("podlove")
        if not podlove:
            return podlove
        data = self._load_json(podlove, field_label="Podlove")
        if not isinstance(data, dict) or "transcripts" not in data:
            raise ValidationError(_("Podlove transcript must include a top-level 'transcripts' key."))
        if not isinstance(data["transcripts"], list):
            raise ValidationError(_("Podlove transcript 'transcripts' must be a list."))
        return podlove

    def clean_dote(self):
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

    def clean_vtt(self):
        vtt = self.cleaned_data.get("vtt")
        if not vtt:
            return vtt
        header = self._read_header(vtt)
        if not header.startswith("WEBVTT"):
            raise ValidationError(_("WebVTT transcripts must start with the WEBVTT header."))
        return vtt

    @staticmethod
    def _load_json(uploaded_file, *, field_label: str):
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
    def _read_header(uploaded_file, size: int = 32) -> str:
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
    """Dynamic form mapping transcript speaker labels to episode contributors."""

    action = forms.CharField(initial=SPEAKER_MAPPING_ACTION, widget=forms.HiddenInput())
    speaker_mapping: dict[str, str]

    def __init__(
        self,
        *args,
        speaker_labels: list[str],
        contributor_assignments: list[EpisodeContributor],
        multiple_episodes: bool = False,
        source_episode: Any | None = None,
        **kwargs,
    ) -> None:
        del source_episode
        super().__init__(*args, **kwargs)
        self.speaker_labels = speaker_labels
        self.contributor_assignments = contributor_assignments
        self.assignment_lookup: dict[str, EpisodeContributor] = {}
        choices: list[tuple[str, str]] = [("", str(_("Leave unchanged")))]
        for assignment in contributor_assignments:
            assignment_value = self._assignment_value(assignment)
            self.assignment_lookup[assignment_value] = assignment
            choices.append((assignment_value, self._assignment_label(assignment, multiple_episodes=multiple_episodes)))
        self.speaker_field_names = {}
        for index, speaker_label in enumerate(speaker_labels):
            field_name = f"speaker_{index}"
            self.speaker_field_names[field_name] = speaker_label
            self.fields[field_name] = forms.ChoiceField(label=speaker_label, choices=choices, required=False)

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
        for field_name, speaker_label in self.speaker_field_names.items():
            assignment_id = cleaned_data.get(field_name)
            if assignment_id:
                speaker_mapping[speaker_label] = self.assignment_lookup[assignment_id].display_name
        self.speaker_mapping = speaker_mapping
        return cleaned_data


class KnownSpeakerSegmentReviewForm(forms.Form):
    """Dynamic form for per-segment known-speaker editor decisions."""

    action = forms.CharField(initial=KNOWN_SPEAKER_REVIEW_ACTION, widget=forms.HiddenInput())
    segment_decisions: dict[int, dict[str, str] | None]

    def __init__(
        self,
        *args,
        segments: list[dict],
        contributor_assignments: list[EpisodeContributor],
        multiple_episodes: bool = False,
        **kwargs,
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
        segments: list[dict],
        contributor_assignments: list[EpisodeContributor],
    ) -> list[str]:
        names: list[str] = []
        for segment in segments:
            cls._append_name(names, segment.get("speaker"))
            cls._append_candidate_names(names, segment.get("candidates"))
            decision = Transcript._normalize_known_speaker_editor_decision(
                segment.get(KNOWN_SPEAKER_EDITOR_DECISION_FIELD)
            )
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
        name = Transcript._clean_speaker_label(value)
        if name and name not in names:
            names.append(name)

    @staticmethod
    def _speaker_choice_value(name: str) -> str:
        return f"speaker:{name}"

    def _initial_value(self, segment: dict) -> str:
        decision = Transcript._normalize_known_speaker_editor_decision(
            segment.get(KNOWN_SPEAKER_EDITOR_DECISION_FIELD)
        )
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
                suggested_speaker = Transcript._clean_speaker_label(self.segments[position].get("speaker"))
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

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.fields["template_base_dir"].choices = get_template_base_dir_choices()  # type: ignore
