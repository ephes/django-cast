from __future__ import annotations

from django.conf import settings

USE_THREADEDCOMMENTS: bool = "threadedcomments" in settings.INSTALLED_APPS

# Prefer CAST_* settings, but allow existing deployments to keep their historic
# FLUENT_* names while migrating.
EXCLUDE_FIELDS: tuple[str, ...] = tuple(
    getattr(settings, "CAST_COMMENTS_EXCLUDE_FIELDS", getattr(settings, "FLUENT_COMMENTS_EXCLUDE_FIELDS", ())) or ()
)

DEFAULT_MODERATOR: str = getattr(
    settings,
    "CAST_COMMENTS_DEFAULT_MODERATOR",
    getattr(settings, "FLUENT_COMMENTS_DEFAULT_MODERATOR", "cast.moderation.Moderator"),
)

CRISPY_TEMPLATE_PACK: str = getattr(settings, "CRISPY_TEMPLATE_PACK", "bootstrap")

FORM_CSS_CLASS: str = getattr(settings, "CAST_COMMENTS_FORM_CSS_CLASS", "comments-form form-horizontal")
LABEL_CSS_CLASS: str = getattr(settings, "CAST_COMMENTS_LABEL_CSS_CLASS", "col-sm-2")
FIELD_CSS_CLASS: str = getattr(settings, "CAST_COMMENTS_FIELD_CSS_CLASS", "col-sm-10")
