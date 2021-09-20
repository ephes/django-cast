from django import forms
from django.core.exceptions import ValidationError
from django.forms.models import modelform_factory
from django.utils.translation import gettext_lazy as _

from wagtail.admin import widgets
from wagtail.admin.forms.collections import BaseCollectionMemberForm
from wagtail.core.models import Collection

from .models import Audio, ChapterMark, Video


class FakePermissionPolicy:
    def collections_user_has_permission_for(self, user, action):
        return Collection.objects.all()


class BaseVideoForm(BaseCollectionMemberForm):
    class Meta:
        widgets = {
            "tags": widgets.AdminTagWidget,
            "original": forms.FileInput,
            "poster": forms.ClearableFileInput,
        }

    permission_policy = FakePermissionPolicy()


def get_video_form():
    fields = Video.admin_form_fields
    if "collection" not in fields:
        # force addition of the 'collection' field, because leaving it out can
        # cause dubious results when multiple collections exist (e.g adding the
        # media to the root collection where the user may not have permission) -
        # and when only one collection exists, it will get hidden anyway.
        fields = list(fields) + ["collection"]

    return modelform_factory(
        Video,
        form=BaseVideoForm,
        fields=fields,
    )


class ChapterMarkForm(forms.ModelForm):
    class Meta:
        model = ChapterMark
        fields = ("start", "title", "link", "image")


def parse_chaptermark_line(line):
    def raise_line_validation_error():
        raise ValidationError(
            _(f"Invalid chaptermark line: {line}"),
            code="invalid",
            params={"line": line},
        )

    splitted = line.split()
    if len(splitted) < 2:
        raise_line_validation_error()
    start, *parts = splitted
    title = " ".join(parts)
    form = ChapterMarkForm({"start": start, "title": title})
    if form.is_valid():
        return form.save(commit=False)
    else:
        raise_line_validation_error()


class ChapterMarksField(forms.CharField):
    def to_python(self, value):
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

    def save_chaptermarks(self, audio):
        # only save if chaptermarks from form and from audio are
        # different - maybe only update old chaptermarks, but overwrite
        # all for now..
        audio.chaptermarks.all().delete()
        chaptermarks = self.cleaned_data.get("chaptermarks", [])
        for cm in chaptermarks:
            cm.audio = audio
            cm.save()

    def save(self, commit=True):
        audio = super().save(commit=commit)
        if commit:
            self.save_chaptermarks(audio)
        return audio
