from __future__ import annotations

from collections import OrderedDict
from typing import TYPE_CHECKING, Any, TypeAlias

from django import forms
from django.core.exceptions import ImproperlyConfigured

from . import appsettings
from .helper import CommentFormHelper


if TYPE_CHECKING:
    from django_comments.forms import CommentForm


def _get_base_form() -> type[CommentForm]:
    if appsettings.USE_THREADEDCOMMENTS:
        from threadedcomments.forms import ThreadedCommentForm

        return ThreadedCommentForm
    from django_comments.forms import CommentForm

    return CommentForm


if TYPE_CHECKING:
    BaseCommentForm: TypeAlias = CommentForm
else:
    BaseCommentForm = _get_base_form()


class CastCommentForm(BaseCommentForm):
    fields: dict[str, forms.Field]
    helper = CommentFormHelper()

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.is_preview = bool(kwargs.pop("is_preview", False))
        super().__init__(*args, **kwargs)

        for name in appsettings.EXCLUDE_FIELDS:
            try:
                self.fields.pop(name)
            except KeyError as exc:
                raise ImproperlyConfigured(
                    f"Field name '{name}' in CAST_COMMENTS_EXCLUDE_FIELDS/FLUENT_COMMENTS_EXCLUDE_FIELDS is invalid; "
                    f"it does not exist in '{self.__class__.__name__}'."
                ) from exc

        self._reorder_fields()

    def _reorder_fields(self) -> None:
        base_fields_top = ["content_type", "object_pk", "timestamp", "security_hash"]
        base_fields_end = ["honeypot"]
        if appsettings.USE_THREADEDCOMMENTS:
            base_fields_top.append("parent")

        ordering = [name for name in base_fields_top if name in self.fields]
        ordering += [name for name in self.fields.keys() if name not in ordering and name not in base_fields_end]
        ordering += [name for name in base_fields_end if name in self.fields]

        self.fields = OrderedDict((name, self.fields[name]) for name in ordering)

    def get_comment_create_data(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        # Fill fake values for excluded fields to prevent KeyError access in base implementations.
        for name in appsettings.EXCLUDE_FIELDS:
            if name not in self.cleaned_data:
                self.cleaned_data[name] = ""
        return super().get_comment_create_data(*args, **kwargs)
