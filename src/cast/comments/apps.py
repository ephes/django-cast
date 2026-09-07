from __future__ import annotations

from django.apps import AppConfig


class CastCommentsConfig(AppConfig):
    name = "cast.comments"
    label = "cast_comments"

    def ready(self) -> None:
        # Register signal receivers.
        from . import receivers as _receivers  # noqa: F401
        from threadedcomments.templatetags import threadedcomments_tags

        from .templatetags.fluent_comments_tags import safe_fill_tree

        # Existing project/theme overrides commonly load threadedcomments_tags
        # and call fill_tree directly. Replace that unsafe ancestor expansion at
        # the library boundary so those templates receive the same protection.
        threadedcomments_tags.register.filter("fill_tree", safe_fill_tree)
