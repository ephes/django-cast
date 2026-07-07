from __future__ import annotations

from typing import TYPE_CHECKING, TypeAlias

from django.db import models
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
    def get_queryset(self) -> models.QuerySet[DjangoComment]:
        return super().get_queryset().select_related("user")


class CastComment(BaseComment):
    objects = CastCommentManager()

    class Meta:
        verbose_name = _("Comment")
        verbose_name_plural = _("Comments")
        proxy = True
        managed = False


class CommentAuthorMeta(models.Model):
    """Per-comment metadata for the author self-editing/deletion feature.

    Deliberately *not* a ``ForeignKey``: the concrete comment model varies by
    deployment (``django_comments`` / ``threadedcomments`` / a custom
    ``COMMENTS_APP``), so a migration must not freeze a relation to one table,
    and the comment PK type is not guaranteed to be a 32-bit int. The PK is
    stored as text (mirroring how ``django_comments`` references arbitrary-PK
    objects via ``object_pk``); 255 chars covers integers, big integers and UUIDs.
    """

    comment_pk = models.CharField(max_length=255, unique=True)
    edited = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("Comment author metadata")
        verbose_name_plural = _("Comment author metadata")

    def __str__(self) -> str:
        return f"CommentAuthorMeta(comment_pk={self.comment_pk!r})"
