from django import forms
from django.forms.models import modelform_factory

from wagtail.admin import widgets
from wagtail.core.models import Collection
from wagtail.admin.forms.collections import BaseCollectionMemberForm

from .models import Video


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
