"""
Custom comments app for django-contrib-comments.

Configured via ``COMMENTS_APP = "cast.comments"``.
"""

from __future__ import annotations


def get_model():  # django-contrib-comments hook
    from .models import CastComment

    return CastComment


def get_form():  # django-contrib-comments hook
    from .forms import CastCommentForm

    return CastCommentForm
