from __future__ import annotations

from django.contrib import admin

from .models import CommentAuthorMeta


@admin.register(CommentAuthorMeta)
class CommentAuthorMetaAdmin(admin.ModelAdmin):
    """Lets staff see author-edited/deleted comments and clear ``deleted_at``.

    Restoring a soft-deleted comment is done in the comment admin (un-remove it),
    which clears ``deleted_at`` automatically; this view is for visibility and the
    occasional manual fix.
    """

    list_display = ("comment_pk", "edited", "deleted_at")
    list_filter = ("edited",)
    search_fields = ("comment_pk",)
    readonly_fields = ("comment_pk", "edited")
