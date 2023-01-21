from datetime import datetime, time
from typing import Optional

from django import forms
from django.core.exceptions import ValidationError
from django.db.models import QuerySet
from django.forms.models import modelform_factory
from django.utils.translation import gettext_lazy as _
from wagtail.admin import widgets
from wagtail.admin.forms.collections import BaseCollectionMemberForm
from wagtail.core.models import Collection

from .models import Audio, ChapterMark, Video


class VideoForm(forms.ModelForm):
    class Meta:
        model = Video
        fields = ["original"]


class FakePermissionPolicy:
    def collections_user_has_permission_for(self, _user, _action) -> QuerySet[Collection]:
        return Collection.objects.all()


class BaseVideoForm(BaseCollectionMemberForm):
    class Meta:
        widgets = {
            "tags": widgets.AdminTagWidget,
            "original": forms.FileInput,
            "poster": forms.ClearableFileInput,
        }

    permission_policy = FakePermissionPolicy()


def get_video_form() -> type[forms.ModelForm]:
    fields = Video.admin_form_fields
    if "collection" not in fields:
        # force addition of the 'collection' field, because leaving it out can
        # cause dubious results when multiple collections exist (e.g. adding the
        # media to the root collection where the user may not have permission) -
        # and when only one collection exists, it will get hidden anyway.
        fields = tuple(list(fields) + ["collection"])  # type: ignore

    return modelform_factory(
        Video,
        form=BaseVideoForm,
        fields=fields,
    )


class ChapterMarkForm(forms.ModelForm):
    class Meta:
        model = ChapterMark
        fields = ("start", "title", "link", "image")


class FFProbeStartField(forms.TimeField):
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
    start = FFProbeStartField()

    class Meta:
        model = ChapterMark
        fields = ("start", "title")


def parse_chaptermark_line(line: str) -> Optional[ChapterMark]:
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
        raise_line_validation_error()
        return None


class ChapterMarksField(forms.CharField):
    def to_python(self, value: Optional[str]) -> list[ChapterMark]:  # type: ignore
        if value is None:
            return []
        chaptermarks = []
        for line in value.split("\n"):
            if len(line) == 0:
                # skip empty lines
                continue
            chaptermark = parse_chaptermark_line(line)
            if chaptermark is not None:
                chaptermarks.append(chaptermark)
        return chaptermarks


class AudioForm(BaseCollectionMemberForm):
    chaptermarks = ChapterMarksField(widget=forms.Textarea, required=False)
    permission_policy = FakePermissionPolicy()

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
