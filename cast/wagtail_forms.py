from django import forms
from django.forms.models import modelform_factory

from wagtail.admin import widgets
from wagtail.admin.forms.collections import BaseCollectionMemberForm

from wagtailmedia.permissions import permission_policy as media_permission_policy

from .models import Video


class BaseVideoForm(BaseCollectionMemberForm):
    class Meta:
        widgets = {
            "tags": widgets.AdminTagWidget,
            "original": forms.FileInput,
            "poster": forms.ClearableFileInput,
        }

    permission_policy = media_permission_policy


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
