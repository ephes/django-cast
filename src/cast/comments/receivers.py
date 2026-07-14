from __future__ import annotations

from typing import Any

from django.core.exceptions import ImproperlyConfigured
from django.db.models import Model
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from django.http import HttpRequest
from django.utils.functional import SimpleLazyObject
from django.utils.module_loading import import_string
from django_comments import signals

from . import appsettings, author_edits


class NullModerator:
    def __init__(self, model: type[Model] | None) -> None:
        self.model = model

    def allow(self, comment: Any, content_object: Any, request: HttpRequest | None) -> bool:
        return True

    def moderate(self, comment: Any, content_object: Any, request: HttpRequest | None) -> bool:
        return False


def load_default_moderator() -> Any:
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
def on_comment_will_be_posted(sender: Any, comment: Any, request: HttpRequest | None, **kwargs: Any) -> bool | None:
    content_object = comment.content_object
    if not default_moderator.allow(comment, content_object, request):
        return False
    default_moderator.moderate(comment, content_object, request)
    return None


@receiver(signals.comment_was_posted)
def record_owned_comment(sender: Any, comment: Any, request: HttpRequest | None, **kwargs: Any) -> None:
    """Record session ownership of a freshly posted comment (all post paths).

    Lives on the shared ``comment_was_posted`` signal so comments created through
    the stock ``django_comments`` post view are owned by their author too, not
    only those posted through the AJAX view.
    """
    if request is None or not author_edits.author_edits_enabled():
        return
    session = getattr(request, "session", None)
    if session is None:
        return
    author_edits.record_owned_id(session, comment.pk)


def on_comment_saved(sender: type[Model], instance: Any, **kwargs: Any) -> None:
    """Maintain the ``deleted_at`` invariant for the author-edits feature.

    Author deletion sets ``is_removed=True``; un-removing a comment (staff
    restoring it via the normal admin save or the django_comments approve action)
    therefore means it is no longer author-deleted, so clear any author-deletion
    marker. Keyed on ``is_removed`` alone — not also ``is_public`` — so a plain
    un-remove that leaves the comment non-public still clears the marker.
    """
    if not getattr(instance, "is_removed", False):
        author_edits.clear_deleted(instance.pk)


def on_comment_deleted(sender: type[Model], instance: Any, **kwargs: Any) -> None:
    """Drop orphaned metadata when a comment is hard-deleted (e.g. by staff)."""
    author_edits.delete_meta(instance.pk)


def connect_comment_meta_receivers() -> None:
    """Connect the metadata receivers to the active comment model(s).

    Saving a proxy instance dispatches ``post_save`` with the proxy as sender, so
    connect to both the configured comment model and its concrete base.
    """
    import django_comments

    from .models import get_base_comment_model

    senders = {django_comments.get_model(), get_base_comment_model()}
    for sender in senders:
        label = sender._meta.label
        post_save.connect(on_comment_saved, sender=sender, dispatch_uid=f"cast_comment_meta_saved:{label}")
        post_delete.connect(on_comment_deleted, sender=sender, dispatch_uid=f"cast_comment_meta_deleted:{label}")


connect_comment_meta_receivers()
