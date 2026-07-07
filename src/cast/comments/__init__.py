"""
Custom comments app for django-contrib-comments.

Configured via ``COMMENTS_APP = "cast.comments"``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from .forms import CastCommentForm
    from .models import CastComment


def get_model() -> type[CastComment]:  # django-contrib-comments hook
    from .models import CastComment

    return CastComment


def get_form() -> type[CastCommentForm]:  # django-contrib-comments hook
    from .forms import CastCommentForm

    return CastCommentForm
