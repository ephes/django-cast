from __future__ import annotations

from django.core.exceptions import ImproperlyConfigured
from django.dispatch import receiver
from django.utils.functional import SimpleLazyObject
from django.utils.module_loading import import_string
from django_comments import signals

from . import appsettings


class NullModerator:
    def __init__(self, model) -> None:
        self.model = model

    def allow(self, comment, content_object, request) -> bool:
        return True

    def moderate(self, comment, content_object, request) -> bool:
        return False


def load_default_moderator():
    value = str(appsettings.DEFAULT_MODERATOR).strip()
    if value.lower() in {"none", "null"}:
        return NullModerator(None)
    if "." in value:
        return import_string(value)(None)
    if value.lower() in {"default", ""}:
        return NullModerator(None)
    raise ImproperlyConfigured(
        "Bad CAST_COMMENTS_DEFAULT_MODERATOR/FLUENT_COMMENTS_DEFAULT_MODERATOR value. Provide 'none' or a dotted path."
    )


default_moderator = SimpleLazyObject(load_default_moderator)


@receiver(signals.comment_will_be_posted)
def on_comment_will_be_posted(sender, comment, request, **kwargs):
    content_object = comment.content_object
    if not default_moderator.allow(comment, content_object, request):
        return False
    default_moderator.moderate(comment, content_object, request)
    return None
