from django import forms

from wagtail.admin import widgets
from wagtail.admin.forms.collections import BaseCollectionMemberForm

from wagtailmedia.permissions import permission_policy as media_permission_policy


class BaseMediaForm(BaseCollectionMemberForm):
    class Meta:
        widgets = {
            "tags": widgets.AdminTagWidget,
            "file": forms.FileInput,
            "thumbnail": forms.ClearableFileInput,
        }

    permission_policy = media_permission_policy

    def __init__(self, *args, **kwargs):
        super(BaseMediaForm, self).__init__(*args, **kwargs)

        if self.instance.type == "audio":
            for name in ("width", "height"):
                # these fields might be editable=False so verify before accessing
                if name in self.fields:
                    del self.fields[name]
