from django import forms
from django.forms.models import modelform_factory

from wagtail.admin import widgets
from wagtail.admin.forms.collections import BaseCollectionMemberForm
from wagtail.core.models import Collection

from .forms import ChapterMarkForm
from .models import Audio, Video


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


class BaseAudioForm(BaseCollectionMemberForm):
    chaptermarks = forms.CharField(widget=forms.Textarea, required=False)

    class Meta:
        widgets = {
            "tags": widgets.AdminTagWidget,
            "m4a": forms.ClearableFileInput,
            "mp3": forms.ClearableFileInput,
            "oga": forms.ClearableFileInput,
            "opus": forms.ClearableFileInput,
        }

    permission_policy = FakePermissionPolicy()

    def _clean_chaptermarks(self, cleaned_data):
        print("audio instance: ", self.instance)
        print("cleaned data: ", cleaned_data.get("chaptermarks"))
        errors = []
        lines = cleaned_data.get("chaptermarks", "").split("\n")
        if len(lines) > 0:
            self.instance.chaptermarks.all().delete()
        for line in lines:
            splitted = line.split()
            if len(splitted) < 2:
                continue
            start, *parts = splitted
            title = " ".join(parts)
            row = {
                "audio": self.instance.pk,
                "start": start,
                "title": title,
                # "link": None,
                # "image": None
            }
            form = ChapterMarkForm(row)
            if form.is_valid():
                form.save()
            else:
                errors.append(form.errors)
            # TODO:
            # * image/link handling + tests
        if len(errors) > 0:
            self.add_error("chaptermarks", errors)
        return cleaned_data

    def clean(self):
        cleaned_data = super().clean()
        self._clean_chaptermarks(cleaned_data)
        return cleaned_data


def get_audio_form():
    fields = Audio.admin_form_fields
    if "collection" not in fields:
        # force addition of the 'collection' field, because leaving it out can
        # cause dubious results when multiple collections exist (e.g adding the
        # media to the root collection where the user may not have permission) -
        # and when only one collection exists, it will get hidden anyway.
        fields = list(fields) + ["collection"]

    return modelform_factory(
        Audio,
        form=BaseAudioForm,
        fields=fields,
    )
