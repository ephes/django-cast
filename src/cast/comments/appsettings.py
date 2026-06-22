from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.conf import settings

if TYPE_CHECKING:
    USE_THREADEDCOMMENTS: bool
    EXCLUDE_FIELDS: tuple[str, ...]
    DEFAULT_MODERATOR: str
    CRISPY_TEMPLATE_PACK: str
    FORM_CSS_CLASS: str
    LABEL_CSS_CLASS: str
    FIELD_CSS_CLASS: str
    ALLOW_AUTHOR_EDITS: bool
    OWNED_IDS_CAP: int
    EDIT_RATE_LIMIT: int
    EDIT_RATE_WINDOW: int


def __getattr__(name: str) -> Any:
    if name == "USE_THREADEDCOMMENTS":
        return "threadedcomments" in settings.INSTALLED_APPS
    if name == "EXCLUDE_FIELDS":
        # Prefer CAST_* settings, but allow existing deployments to keep their
        # historic FLUENT_* names while migrating.
        return tuple(
            getattr(settings, "CAST_COMMENTS_EXCLUDE_FIELDS", getattr(settings, "FLUENT_COMMENTS_EXCLUDE_FIELDS", ()))
            or ()
        )
    if name == "DEFAULT_MODERATOR":
        return getattr(
            settings,
            "CAST_COMMENTS_DEFAULT_MODERATOR",
            getattr(settings, "FLUENT_COMMENTS_DEFAULT_MODERATOR", "cast.moderation.Moderator"),
        )
    if name == "CRISPY_TEMPLATE_PACK":
        return getattr(settings, "CRISPY_TEMPLATE_PACK", "bootstrap4")
    if name == "FORM_CSS_CLASS":
        return getattr(settings, "CAST_COMMENTS_FORM_CSS_CLASS", "comments-form form-horizontal")
    if name == "LABEL_CSS_CLASS":
        return getattr(settings, "CAST_COMMENTS_LABEL_CSS_CLASS", "col-sm-2")
    if name == "FIELD_CSS_CLASS":
        return getattr(settings, "CAST_COMMENTS_FIELD_CSS_CLASS", "col-sm-10")
    if name == "ALLOW_AUTHOR_EDITS":
        # Strict: only the literal ``True`` enables this opt-in privacy/security
        # feature, so a misconfigured string such as "False" (e.g. from an env
        # var) cannot silently turn it on — ``bool("False")`` is ``True``. A
        # non-bool value is surfaced loudly by the cast.E001 type check.
        return getattr(settings, "CAST_COMMENTS_ALLOW_AUTHOR_EDITS", False) is True
    if name == "OWNED_IDS_CAP":
        return int(getattr(settings, "CAST_COMMENTS_OWNED_IDS_CAP", 200))
    if name == "EDIT_RATE_LIMIT":
        return int(getattr(settings, "CAST_COMMENTS_EDIT_RATE_LIMIT", 30))
    if name == "EDIT_RATE_WINDOW":
        return int(getattr(settings, "CAST_COMMENTS_EDIT_RATE_WINDOW", 60))
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
