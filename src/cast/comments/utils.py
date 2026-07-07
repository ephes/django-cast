from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib.contenttypes.models import ContentType

from . import appsettings

if TYPE_CHECKING:
    from .models import BaseComment


def get_comment_template_name(comment: BaseComment) -> list[str]:
    ctype = ContentType.objects.get_for_id(comment.content_type_id)
    return [
        f"comments/{ctype.app_label}/{ctype.model}/comment.html",
        f"comments/{ctype.app_label}/comment.html",
        "comments/comment.html",
    ]


def get_comment_context_data(comment: BaseComment, action: str | None = None) -> dict[str, object]:
    return {
        "comment": comment,
        "action": action,
        "preview": (action == "preview"),
        "USE_THREADEDCOMMENTS": appsettings.USE_THREADEDCOMMENTS,
    }


def comments_are_open(content_object: object) -> bool:
    value = getattr(content_object, "comments_are_enabled", None)
    if callable(value):
        return bool(value())
    if value is not None:
        return bool(value)
    return True


def comments_are_moderated(content_object: object) -> bool:
    return False
