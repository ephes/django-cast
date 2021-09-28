import django
from django import forms
from django.conf import settings
from django.utils.translation import gettext_lazy as _
from django_comments.forms import CommentForm

from .models import ThreadedComment


class ThreadedCommentForm(CommentForm):
    title = forms.CharField(
        label=_("Title"), required=False, max_length=getattr(settings, "COMMENTS_TITLE_MAX_LENGTH", 255)
    )
    parent = forms.IntegerField(required=False, widget=forms.HiddenInput)

    def __init__(self, target_object, parent=None, data=None, initial=None):
        # Using collections.OrderedDict from Python 2.7+
        # This class does not have an insert method, have to replace it.
        from collections import OrderedDict

        keys = list(self.base_fields.keys())
        keys.remove("title")
        keys.insert(keys.index("comment"), "title")

        self.base_fields = OrderedDict((k, self.base_fields[k]) for k in keys)
        self.parent = parent
        if initial is None:
            initial = {}
        initial.update({"parent": self.parent})
        super().__init__(target_object, data=data, initial=initial)

    def get_comment_model(self):
        return ThreadedComment

    def get_comment_create_data(self, *args, **kwargs):
        d = super().get_comment_create_data(*args, **kwargs)
        d["parent_id"] = self.cleaned_data["parent"]
        d["title"] = self.cleaned_data.get("title", "")  # title can be removed
        return d
