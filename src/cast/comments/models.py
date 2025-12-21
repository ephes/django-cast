from __future__ import annotations

from typing import TYPE_CHECKING, TypeAlias

from django.utils.translation import gettext_lazy as _
from django_comments.managers import CommentManager
from django_comments.models import Comment as DjangoComment

from . import appsettings

try:
    from threadedcomments.models import ThreadedComment as ThreadedCommentModel
except ImportError:  # pragma: no cover
    ThreadedCommentModel = None


def get_base_comment_model() -> type[DjangoComment]:
    if appsettings.USE_THREADEDCOMMENTS and ThreadedCommentModel is not None:
        return ThreadedCommentModel
    return DjangoComment


if TYPE_CHECKING:
    BaseComment: TypeAlias = DjangoComment
else:
    BaseComment = get_base_comment_model()


class CastCommentManager(CommentManager):
    def get_queryset(self):
        return super().get_queryset().select_related("user")


class CastComment(BaseComment):
    objects = CastCommentManager()

    class Meta:
        verbose_name = _("Comment")
        verbose_name_plural = _("Comments")
        proxy = True
        managed = False
