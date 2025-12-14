from __future__ import annotations

from django.apps import AppConfig


class CastCommentsConfig(AppConfig):
    name = "cast.comments"
    label = "cast_comments"

    def ready(self) -> None:
        # Register signal receivers.
        from . import receivers as _receivers  # noqa: F401
